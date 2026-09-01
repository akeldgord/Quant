"""P4-R4 remediation acceptance tests -- proves honest provider-failure and
provider-capacity classification actually holds against REAL adapters, not
just the project-internal fake `ShadowQuoteError` family.

Unlike `tests/integration/test_shadow_phase4.py` (which uses the fake
`QueuedExecutionProvider` for every gate it covers), every test in this
file drives `argus.shadow.quote_jobs` through a REAL `JupiterClient`
backed by `httpx.MockTransport` (no live network -- see
`tests/unit/test_provider_adapters.py`/`tests/unit/test_probes.py` for the
same idiom already used elsewhere in this project) and, where relevant, a
REAL `argus.providers.scheduler.PriorityScheduler` -- proving the exact
seam P4-R4 touched: `_classify_provider_exception` on a genuine
`httpx.HTTPStatusError`/`RequestDropped`, and `_classify_quote`'s route/
identity checks on a genuine Jupiter-shaped response body.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from argus.clock import Clock
from argus.config import load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.chain_events import ChainEvent
from argus.domain.commitment import COMMITMENT_CONFIRMED, CommitmentObservation
from argus.domain.shadow_quote_probes import (
    OUTCOME_NO_ROUTE,
    OUTCOME_PROVIDER_CAPACITY_MISS,
    OUTCOME_QUOTE_FAILED,
    OUTCOME_SUCCESS,
)
from argus.domain.swaps import Swap
from argus.domain.wallet_score_snapshots import WalletScoreSnapshot
from argus.domain.wallet_tier_history import WalletTierTransition
from argus.domain.wallets import Wallet
from argus.providers.jupiter.client import JupiterClient
from argus.providers.retry import RetryPolicy
from argus.providers.scheduler import PriorityScheduler
from argus.providers.usage import SqlUsageRecorder, UsageRecorder
from argus.shadow.monitor import run_prospective_monitoring_pass
from argus.shadow.quote_jobs import PRIORITY_CLASS_ENTRY_DELAY, run_due_entry_probes

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 6, 1, tzinfo=UTC)
_TEST_GIT_COMMIT = "TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB"
SOL_MINT = "So11111111111111111111111111111111111111112"


# ---------------------------------------------------------------------
# Fixture/helper scaffolding -- copied from tests/integration/
# test_shadow_phase4.py's own established pattern, with a distinct
# wallet-address prefix ("P4RP") so parallel test files never collide.
# ---------------------------------------------------------------------


def _unique_wallet() -> str:
    return f"P4RP{uuid.uuid4().hex[:38]}"


def _sessionmaker():
    config = load_config()
    info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(info.as_asyncpg_url())
    return config, engine, async_sessionmaker(engine, expire_on_commit=False)


async def _cleanup_wallet(admin_engine: Any, wallet_address: str) -> None:
    async with admin_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT wallet_id FROM wallets WHERE wallet_address = :w"),
                {"w": wallet_address},
            )
        ).fetchone()
        if row is not None:
            wid = row[0]
            await conn.execute(
                text(
                    "DELETE FROM shadow_mark_outcomes WHERE shadow_position_id IN "
                    "(SELECT shadow_position_id FROM shadow_positions WHERE wallet_id = :w)"
                ),
                {"w": wid},
            )
            await conn.execute(
                text(
                    "DELETE FROM shadow_quote_probes WHERE shadow_position_id IN "
                    "(SELECT shadow_position_id FROM shadow_positions WHERE wallet_id = :w) "
                    "OR shadow_intent_id IN "
                    "(SELECT shadow_intent_id FROM shadow_intents WHERE wallet_id = :w)"
                ),
                {"w": wid},
            )
            await conn.execute(
                text("DELETE FROM shadow_positions WHERE wallet_id = :w"), {"w": wid}
            )
            await conn.execute(text("DELETE FROM shadow_intents WHERE wallet_id = :w"), {"w": wid})
            await conn.execute(
                text("DELETE FROM prospective_events WHERE wallet_id = :w"), {"w": wid}
            )
            await conn.execute(
                text("DELETE FROM wallet_tier_history WHERE wallet_id = :w"), {"w": wid}
            )
            await conn.execute(
                text("DELETE FROM wallet_score_snapshots WHERE wallet_id = :w"), {"w": wid}
            )
            await conn.execute(
                text("DELETE FROM swaps WHERE wallet_address = :addr"), {"addr": wallet_address}
            )
            await conn.execute(
                text(
                    "DELETE FROM commitment_observations WHERE event_id IN "
                    "(SELECT event_id FROM chain_events WHERE wallet_address = :addr)"
                ),
                {"addr": wallet_address},
            )
            await conn.execute(
                text("DELETE FROM chain_events WHERE wallet_address = :addr"),
                {"addr": wallet_address},
            )
            await conn.execute(text("DELETE FROM wallets WHERE wallet_id = :w"), {"w": wid})
        await conn.commit()


async def _seed_tracked_wallet_with_buy_swap(
    session, *, wallet_address: str, tier: str, score: Decimal, mint: str, at: datetime
) -> tuple[uuid.UUID, uuid.UUID]:
    """Real chain_events/swaps/commitment_observations/wallets/wallet_score_snapshots
    rows -- a genuine SWAP_SIMPLE buy (SOL -> mint) from a tracked wallet."""
    wallet_id = uuid.uuid4()
    session.add(
        Wallet(
            wallet_id=wallet_id,
            wallet_address=wallet_address,
            first_discovered_at=at,
            current_tier=tier,
            created_at=at,
        )
    )
    await session.flush()
    score_id = uuid.uuid4()
    session.add(
        WalletScoreSnapshot(
            score_id=score_id,
            wallet_id=wallet_id,
            as_of=at,
            score_version="test-v1",
            descriptive_score=score,
            qualification_score=score,
            component_values={},
            penalties={},
            confidence="HIGH",
            excluded_discovery_token_ids=[],
            eligible_for_qualification=True,
            sample_gate_reason="test",
            build_hash="test-build",
            config_hash="test-config",
            master_spec_hash="test-spec",
            git_commit=_TEST_GIT_COMMIT,
            created_at=at,
        )
    )
    session.add(
        WalletTierTransition(
            transition_id=uuid.uuid4(),
            wallet_id=wallet_id,
            source_score_id=score_id,
            from_tier=None,
            to_tier=tier,
            reason="test",
            transitioned_at=at,
            created_at=at,
        )
    )
    event_id = uuid.uuid4()
    session.add(
        ChainEvent(
            event_id=event_id,
            chain="solana",
            slot=1,
            block_time=at,
            first_seen_at=at,
            provider="helius",
            provider_received_at=at,
            transaction_signature=f"p4rp-buy-{uuid.uuid4()}",
            event_type="TRANSACTION_OBSERVED",
            wallet_address=wallet_address,
            raw_payload={},
            payload_hash="h",
            parser_version="v1",
            created_at=at,
        )
    )
    await session.flush()
    session.add(
        CommitmentObservation(
            observation_id=uuid.uuid4(),
            event_id=event_id,
            commitment_level=COMMITMENT_CONFIRMED,
            transaction_succeeded=True,
            observed_at=at,
            provider="helius",
            provider_received_at=at,
            created_at=at,
        )
    )
    swap_id = uuid.uuid4()
    session.add(
        Swap(
            swap_id=swap_id,
            event_id=event_id,
            wallet_address=wallet_address,
            classification="SWAP_SIMPLE",
            input_mint=SOL_MINT,
            input_amount_raw=100_000_000,
            input_amount_ui=Decimal("0.1"),
            output_mint=mint,
            output_amount_raw=1_000_000,
            output_amount_ui=Decimal("1"),
            network_fee_raw=5000,
            slot=1,
            block_time=at,
            first_seen_at=at,
            confidence=Decimal("1.000"),
            parser_version="v1",
            build_hash="test-build",
            created_at=at,
        )
    )
    await session.flush()
    return wallet_id, swap_id


async def _seed_intent_with_entry_probes(sessionmaker, config, *, wallet_address: str, mint: str):
    """Seeds a tracked A-tier wallet's buy swap and runs one monitoring
    pass, returning the resulting shadow intent (with its 6 due
    ENTRY_DELAY probes already scheduled)."""
    async with sessionmaker() as session, session.begin():
        await _seed_tracked_wallet_with_buy_swap(
            session,
            wallet_address=wallet_address,
            tier="A",
            score=Decimal("90.000"),
            mint=mint,
            at=_NOW,
        )
    result = await run_prospective_monitoring_pass(sessionmaker, config=config, now=_NOW)
    return result.shadow_intents[0]


# ---------------------------------------------------------------------
# Real-Jupiter-shaped response body builders and a MockTransport-backed
# JupiterClient factory -- the "real no-live-network" idiom this project
# already uses in tests/unit/test_provider_adapters.py and
# tests/unit/test_probes.py, applied here to the real adapter that P4-R4
# actually fixed classification for.
# ---------------------------------------------------------------------


def _valid_route_plan(
    *, input_mint: str, output_mint: str, in_amount: int, out_amount: int
) -> list[dict[str, Any]]:
    return [
        {
            "swapInfo": {
                "ammKey": "AMMkey1111111111111111111111111111111111",
                "label": "Raydium",
                "inputMint": input_mint,
                "outputMint": output_mint,
                "inAmount": str(in_amount),
                "outAmount": str(out_amount),
                "feeAmount": "1000",
                "feeMint": input_mint,
            },
            "percent": 100,
        }
    ]


def _jupiter_quote_body(
    *,
    input_mint: str,
    output_mint: str,
    in_amount: int,
    out_amount: int,
    price_impact_pct: str | None = "0.01",
    empty_route_plan: bool = False,
    omit_route_plan: bool = False,
) -> dict[str, Any]:
    """A genuine Jupiter v6 `/quote` 200 response shape. `empty_route_plan`/
    `omit_route_plan` produce the two malformed "positive outAmount, no
    real route evidence" shapes P4-R4's `_classify_quote` must reject."""
    body: dict[str, Any] = {
        "inputMint": input_mint,
        "inAmount": str(in_amount),
        "outputMint": output_mint,
        "outAmount": str(out_amount),
        "otherAmountThreshold": str(max(out_amount - 1000, 0)),
        "swapMode": "ExactIn",
        "slippageBps": 50,
        "contextSlot": 123_456_789,
        "timeTaken": 0.012,
    }
    if price_impact_pct is not None:
        body["priceImpactPct"] = price_impact_pct
    if not omit_route_plan:
        body["routePlan"] = (
            []
            if empty_route_plan
            else _valid_route_plan(
                input_mint=input_mint,
                output_mint=output_mint,
                in_amount=in_amount,
                out_amount=out_amount,
            )
        )
    return body


def _jupiter_client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    usage_recorder: UsageRecorder | None = None,
    clock: Clock | None = None,
) -> tuple[JupiterClient, httpx.AsyncClient]:
    """Real `JupiterClient` over `httpx.MockTransport` -- no live network,
    but the SAME `send_with_usage` -> retry -> `raise_for_status()` ->
    contract-validation path production traffic goes through.
    `max_attempts=1` keeps failure-path tests deterministic and fast (a
    5xx would otherwise be retried by the default policy)."""
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = JupiterClient(
        http_client=http_client,
        retry_policy=RetryPolicy(max_attempts=1),
        usage_recorder=usage_recorder,
        clock=clock,
    )
    return client, http_client


def _counting_handler(
    respond: Callable[[httpx.Request], httpx.Response],
) -> Callable[[httpx.Request], httpx.Response]:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return respond(request)

    handler.calls = calls  # type: ignore[attr-defined]
    return handler


# ---------------------------------------------------------------------
# 1. Success with a real-format route.
# ---------------------------------------------------------------------


async def test_real_jupiter_success_records_success_and_route(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4RPMint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    http_client: httpx.AsyncClient | None = None
    try:
        intent = await _seed_intent_with_entry_probes(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_jupiter_quote_body(
                    input_mint=intent.input_mint,
                    output_mint=intent.output_mint,
                    in_amount=intent.notional_input_amount_raw,
                    out_amount=500_000,
                    price_impact_pct="0.01",
                ),
            )

        handler = _counting_handler(respond)
        provider, http_client = _jupiter_client(handler)

        far_future = _NOW + timedelta(seconds=400)
        processed = await run_due_entry_probes(
            sessionmaker, provider, config=config, clock=Clock(), now=far_future, limit=1
        )
        assert len(processed) == 1
        probe = processed[0]
        assert probe.target_label == "1s"
        assert probe.outcome == OUTCOME_SUCCESS
        assert probe.route_present is True
        assert probe.expected_output_amount_raw == 500_000
        assert probe.price_impact_pct == Decimal("0.01")
        assert len(handler.calls) == 1  # type: ignore[attr-defined]
    finally:
        if http_client is not None:
            await http_client.aclose()
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# 2. HTTP no-route failure -> OUTCOME_NO_ROUTE.
# ---------------------------------------------------------------------


async def test_real_jupiter_http_400_no_route_error_code_maps_to_no_route(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4RPMint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    http_client: httpx.AsyncClient | None = None
    try:
        await _seed_intent_with_entry_probes(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                json={
                    "errorCode": "COULD_NOT_FIND_ANY_ROUTE",
                    "error": "Could not find any route for the given input and output mints",
                },
            )

        handler = _counting_handler(respond)
        provider, http_client = _jupiter_client(handler)

        far_future = _NOW + timedelta(seconds=400)
        processed = await run_due_entry_probes(
            sessionmaker, provider, config=config, clock=Clock(), now=far_future, limit=1
        )
        assert len(processed) == 1
        assert processed[0].outcome == OUTCOME_NO_ROUTE
        assert processed[0].expected_output_amount_raw is None
        assert len(handler.calls) == 1  # type: ignore[attr-defined]
    finally:
        if http_client is not None:
            await http_client.aclose()
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# 3. An unrecognized Jupiter error body/code -> the honest QUOTE_FAILED
#    catch-all (never a fabricated TOKEN_RESTRICTED -- the real adapter
#    has no positive signal for that).
# ---------------------------------------------------------------------


async def test_real_jupiter_http_400_unrecognized_error_code_stays_honest_quote_failed(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4RPMint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    http_client: httpx.AsyncClient | None = None
    try:
        await _seed_intent_with_entry_probes(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )

        def respond(request: httpx.Request) -> httpx.Response:
            # A plausible restricted-token-shaped Jupiter error this
            # project does NOT positively recognize -- some OTHER
            # errorCode than COULD_NOT_FIND_ANY_ROUTE.
            return httpx.Response(
                400,
                json={
                    "errorCode": "TOKEN_NOT_TRADABLE",
                    "error": "This token is currently restricted from trading",
                },
            )

        handler = _counting_handler(respond)
        provider, http_client = _jupiter_client(handler)

        far_future = _NOW + timedelta(seconds=400)
        processed = await run_due_entry_probes(
            sessionmaker, provider, config=config, clock=Clock(), now=far_future, limit=1
        )
        assert len(processed) == 1
        assert processed[0].outcome == OUTCOME_QUOTE_FAILED
        assert len(handler.calls) == 1  # type: ignore[attr-defined]
    finally:
        if http_client is not None:
            await http_client.aclose()
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# 4. Rate/capacity HTTP failure (429) -> OUTCOME_PROVIDER_CAPACITY_MISS.
# ---------------------------------------------------------------------


async def test_real_jupiter_http_429_maps_to_provider_capacity_miss(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4RPMint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    http_client: httpx.AsyncClient | None = None
    try:
        await _seed_intent_with_entry_probes(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "Too Many Requests"})

        handler = _counting_handler(respond)
        provider, http_client = _jupiter_client(handler)

        far_future = _NOW + timedelta(seconds=400)
        processed = await run_due_entry_probes(
            sessionmaker, provider, config=config, clock=Clock(), now=far_future, limit=1
        )
        assert len(processed) == 1
        assert processed[0].outcome == OUTCOME_PROVIDER_CAPACITY_MISS
        assert processed[0].expected_output_amount_raw is None
        assert processed[0].route_present is False
        assert len(handler.calls) == 1  # type: ignore[attr-defined]
    finally:
        if http_client is not None:
            await http_client.aclose()
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# 5. Ordinary unparseable/unknown failure -> honest QUOTE_FAILED, never
#    a guessed classification.
# ---------------------------------------------------------------------


async def test_real_jupiter_http_500_unparseable_body_stays_quote_failed(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4RPMint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    http_client: httpx.AsyncClient | None = None
    try:
        await _seed_intent_with_entry_probes(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

        handler = _counting_handler(respond)
        provider, http_client = _jupiter_client(handler)

        far_future = _NOW + timedelta(seconds=400)
        processed = await run_due_entry_probes(
            sessionmaker, provider, config=config, clock=Clock(), now=far_future, limit=1
        )
        assert len(processed) == 1
        assert processed[0].outcome == OUTCOME_QUOTE_FAILED
        # max_attempts=1 keeps this deterministic: exactly one real call,
        # never a guessed multi-attempt retry count muddying the assertion.
        assert len(handler.calls) == 1  # type: ignore[attr-defined]
    finally:
        if http_client is not None:
            await http_client.aclose()
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# 6. Malformed 200: positive outAmount but no real route evidence ->
#    NO_ROUTE, route_present=False -- never a fabricated SUCCESS.
# ---------------------------------------------------------------------


@pytest.mark.parametrize("empty_route_plan,omit_route_plan", [(True, False), (False, True)])
async def test_real_jupiter_positive_output_without_route_plan_is_no_route(
    admin_engine, empty_route_plan: bool, omit_route_plan: bool
) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4RPMint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    http_client: httpx.AsyncClient | None = None
    try:
        intent = await _seed_intent_with_entry_probes(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_jupiter_quote_body(
                    input_mint=intent.input_mint,
                    output_mint=intent.output_mint,
                    in_amount=intent.notional_input_amount_raw,
                    out_amount=500_000,  # positive -- must NOT be trusted alone
                    empty_route_plan=empty_route_plan,
                    omit_route_plan=omit_route_plan,
                ),
            )

        handler = _counting_handler(respond)
        provider, http_client = _jupiter_client(handler)

        far_future = _NOW + timedelta(seconds=400)
        processed = await run_due_entry_probes(
            sessionmaker, provider, config=config, clock=Clock(), now=far_future, limit=1
        )
        assert len(processed) == 1
        probe = processed[0]
        assert probe.outcome == OUTCOME_NO_ROUTE
        assert probe.route_present is False
        assert probe.expected_output_amount_raw is None
    finally:
        if http_client is not None:
            await http_client.aclose()
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# 7. Wrong quote notional (identity mismatch) -> honest QUOTE_FAILED,
#    never trusted as a success regardless of outAmount/routePlan.
# ---------------------------------------------------------------------


async def test_real_jupiter_in_amount_mismatch_is_quote_failed_not_trusted(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4RPMint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    http_client: httpx.AsyncClient | None = None
    try:
        intent = await _seed_intent_with_entry_probes(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )

        def respond(request: httpx.Request) -> httpx.Response:
            # A well-formed, positive, routed quote -- but echoing an
            # inAmount that does NOT match what this probe actually
            # requested.
            return httpx.Response(
                200,
                json=_jupiter_quote_body(
                    input_mint=intent.input_mint,
                    output_mint=intent.output_mint,
                    in_amount=intent.notional_input_amount_raw + 1,
                    out_amount=500_000,
                ),
            )

        handler = _counting_handler(respond)
        provider, http_client = _jupiter_client(handler)

        far_future = _NOW + timedelta(seconds=400)
        processed = await run_due_entry_probes(
            sessionmaker, provider, config=config, clock=Clock(), now=far_future, limit=1
        )
        assert len(processed) == 1
        probe = processed[0]
        assert probe.outcome == OUTCOME_QUOTE_FAILED
        assert probe.route_present is False
        assert probe.expected_output_amount_raw is None
    finally:
        if http_client is not None:
            await http_client.aclose()
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# 8. Malformed/nonfinite price-impact data must be treated leniently
#    (impact -> None, not automatically excessive) and must never crash
#    the batch, per _classify_quote's own documented behavior.
#
#    This test file originally found that a genuine literal-"NaN"
#    priceImpactPct crashed with an uncaught decimal.InvalidOperation --
#    Decimal("NaN") parses successfully (no exception at parse time) but
#    the subsequent `price_impact > max_impact` comparison raises when
#    comparing a nonfinite Decimal. Fixed directly in _classify_quote
#    (src/argus/shadow/quote_jobs.py): a parsed-but-nonfinite
#    (NaN/Infinity) price_impact is now folded into the same honest
#    `None` leniency path as a genuinely unparseable string, immediately
#    after the parse and before any comparison.
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate_body",
    [
        pytest.param(lambda body: body.pop("priceImpactPct"), id="missing"),
        pytest.param(
            lambda body: body.__setitem__("priceImpactPct", "not-a-number"), id="unparseable"
        ),
        pytest.param(lambda body: body.__setitem__("priceImpactPct", "NaN"), id="literal-nan"),
        pytest.param(
            lambda body: body.__setitem__("priceImpactPct", "Infinity"), id="literal-infinity"
        ),
    ],
)
async def test_real_jupiter_malformed_price_impact_is_lenient_not_a_crash(
    admin_engine, mutate_body: Callable[[dict[str, Any]], None]
) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4RPMint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    http_client: httpx.AsyncClient | None = None
    try:
        intent = await _seed_intent_with_entry_probes(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )

        def respond(request: httpx.Request) -> httpx.Response:
            body = _jupiter_quote_body(
                input_mint=intent.input_mint,
                output_mint=intent.output_mint,
                in_amount=intent.notional_input_amount_raw,
                out_amount=500_000,
            )
            mutate_body(body)
            return httpx.Response(200, json=body)

        handler = _counting_handler(respond)
        provider, http_client = _jupiter_client(handler)

        far_future = _NOW + timedelta(seconds=400)
        processed = await run_due_entry_probes(
            sessionmaker, provider, config=config, clock=Clock(), now=far_future, limit=1
        )
        assert len(processed) == 1
        probe = processed[0]
        # An honestly-unknown impact never disqualifies an otherwise
        # valid, routed, identity-matched quote.
        assert probe.outcome == OUTCOME_SUCCESS
        assert probe.price_impact_pct is None
        assert probe.route_present is True
        assert probe.expected_output_amount_raw == 500_000
    finally:
        if http_client is not None:
            await http_client.aclose()
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# 9. A real PriorityScheduler drop under load never reaches the network
#    and is recorded as an honest PROVIDER_CAPACITY_MISS; an accepted
#    request on a non-saturated scheduler still reaches it normally.
# ---------------------------------------------------------------------


async def test_real_scheduler_drop_never_reaches_network_accepted_request_still_does(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4RPMint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    http_client: httpx.AsyncClient | None = None
    http_client_2: httpx.AsyncClient | None = None
    blocker_task: asyncio.Task | None = None
    queued_task: asyncio.Task | None = None
    try:
        intent = await _seed_intent_with_entry_probes(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )

        # --- Part A: saturate a real scheduler's droppable-class queue,
        # then prove the NEXT submission through _execute_and_record_probe
        # is dropped WITHOUT ever invoking the HTTP handler. -----------
        scheduler = PriorityScheduler(max_concurrency=1, max_queue_depth_per_droppable_class=1)

        block_event = asyncio.Event()
        queued_event = asyncio.Event()

        async def _blocker() -> None:
            await block_event.wait()

        async def _queued() -> None:
            await queued_event.wait()

        # Occupies the scheduler's single concurrency slot (dispatched,
        # not merely queued) so the item below stays genuinely pending.
        blocker_task = asyncio.create_task(scheduler.submit(PRIORITY_CLASS_ENTRY_DELAY, _blocker))
        await asyncio.sleep(0.1)
        # Fills the droppable class's own queue depth (1) while capacity
        # is held by the blocker above.
        queued_task = asyncio.create_task(scheduler.submit(PRIORITY_CLASS_ENTRY_DELAY, _queued))
        await asyncio.sleep(0.1)
        assert scheduler.pending_count(PRIORITY_CLASS_ENTRY_DELAY) == 1

        def respond(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must never run
            return httpx.Response(
                200,
                json=_jupiter_quote_body(
                    input_mint=intent.input_mint,
                    output_mint=intent.output_mint,
                    in_amount=intent.notional_input_amount_raw,
                    out_amount=500_000,
                ),
            )

        handler = _counting_handler(respond)
        provider, http_client = _jupiter_client(handler)

        far_future = _NOW + timedelta(seconds=400)
        processed = await run_due_entry_probes(
            sessionmaker,
            provider,
            config=config,
            clock=Clock(),
            now=far_future,
            limit=1,
            scheduler=scheduler,
        )
        assert len(processed) == 1
        probe = processed[0]
        assert probe.target_label == "1s"
        assert probe.outcome == OUTCOME_PROVIDER_CAPACITY_MISS
        assert probe.expected_output_amount_raw is None
        assert probe.route_present is False
        # The critical assertion: a scheduler-level drop never reaches
        # the network at all.
        assert len(handler.calls) == 0  # type: ignore[attr-defined]

        block_event.set()
        queued_event.set()
        await asyncio.wait_for(asyncio.gather(blocker_task, queued_task), timeout=5)
        blocker_task = None
        queued_task = None

        # --- Part B: same integration seam, a scheduler with room --
        # normal priority-ordering behavior (not re-tested here -- that
        # is scheduler.py's own job) still lets an accepted request
        # reach the real network and succeed. -----------------------
        scheduler_2 = PriorityScheduler()

        def respond_2(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_jupiter_quote_body(
                    input_mint=intent.input_mint,
                    output_mint=intent.output_mint,
                    in_amount=intent.notional_input_amount_raw,
                    out_amount=750_000,
                ),
            )

        handler_2 = _counting_handler(respond_2)
        provider_2, http_client_2 = _jupiter_client(handler_2)

        processed_2 = await run_due_entry_probes(
            sessionmaker,
            provider_2,
            config=config,
            clock=Clock(),
            now=far_future,
            limit=1,
            scheduler=scheduler_2,
        )
        assert len(processed_2) == 1
        probe_2 = processed_2[0]
        assert probe_2.target_label == "5s"
        assert probe_2.outcome == OUTCOME_SUCCESS
        assert probe_2.expected_output_amount_raw == 750_000
        assert len(handler_2.calls) == 1  # type: ignore[attr-defined]
    finally:
        # A failed assertion above must never leak a still-pending task.
        if blocker_task is not None and not blocker_task.done():
            blocker_task.cancel()
        if queued_task is not None and not queued_task.done():
            queued_task.cancel()
        if http_client is not None:
            await http_client.aclose()
        if http_client_2 is not None:
            await http_client_2.aclose()
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# 10. Real market/quote usage accounting: a real JupiterClient call
#     through this path, with a real SqlUsageRecorder supplied, actually
#     writes a provider_usage row (provider/endpoint/status).
# ---------------------------------------------------------------------


async def test_real_jupiter_call_through_probe_path_records_usage(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4RPMint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    http_client: httpx.AsyncClient | None = None
    test_start = datetime.now(UTC) - timedelta(seconds=5)
    try:
        intent = await _seed_intent_with_entry_probes(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_jupiter_quote_body(
                    input_mint=intent.input_mint,
                    output_mint=intent.output_mint,
                    in_amount=intent.notional_input_amount_raw,
                    out_amount=500_000,
                ),
            )

        handler = _counting_handler(respond)
        # SqlUsageRecorder writes via its own independent session/
        # transaction per record (argus.providers.usage), reusing the
        # same real sessionmaker the probe path itself uses.
        usage_recorder = SqlUsageRecorder(sessionmaker)
        provider, http_client = _jupiter_client(handler, usage_recorder=usage_recorder)

        far_future = _NOW + timedelta(seconds=400)
        processed = await run_due_entry_probes(
            sessionmaker, provider, config=config, clock=Clock(), now=far_future, limit=1
        )
        assert len(processed) == 1
        assert processed[0].outcome == OUTCOME_SUCCESS
        assert len(handler.calls) == 1  # type: ignore[attr-defined]

        async with admin_engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT provider, endpoint, request_class, status "
                        "FROM provider_usage WHERE provider = 'jupiter' AND requested_at >= :start"
                    ),
                    {"start": test_start},
                )
            ).fetchall()
        assert len(rows) == 1
        provider_name, endpoint, request_class, status = rows[0]
        assert provider_name == "jupiter"
        assert endpoint == "get_quote"
        assert request_class == "quote"
        assert status == "ok"
    finally:
        if http_client is not None:
            await http_client.aclose()
        async with admin_engine.connect() as conn:
            await conn.execute(
                text(
                    "DELETE FROM provider_usage WHERE provider = 'jupiter' AND requested_at >= :start"
                ),
                {"start": test_start},
            )
            await conn.commit()
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()

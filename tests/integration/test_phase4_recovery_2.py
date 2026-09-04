"""argus-phase-4-recovery-002 -- frozen acceptance matrix rows AM-01
(worker-level), AM-03, AM-05, AM-06, AM-07, AM-10 (the worker/persistence
rows that need a real database, a real ``JupiterClient`` over
``httpx.MockTransport``, and the actual production claim/execute/record
seam). AM-11 references the already-passing, already-covering existing
test rather than duplicating it (P4-REC-03's frozen contract; not
redesigned here). AM-14 is proven by running this project's existing
observation/provider/phase4/concurrency/migration/report/isolation suites
and the full regression suite as a separate acceptance command, not by a
test in this file.

Uses a distinct wallet-address prefix (``P4R2``) so this file never
collides with any parallel test file sharing the same database, following
the exact convention every prior Phase 4 remediation-round test file in
this project already establishes.

Entry-kind coverage goes through the real production caller
(``run_due_entry_probes``). Reverse-kind coverage goes through the SAME
underlying ``_execute_and_record_probe`` seam
(``argus-phase-4-recovery-002``'s own explicit allowance: "Cover entry and
reverse worker kinds through their production caller or prove and
exercise their common execution seam") after a genuine entry-probe SUCCESS
creates a real ``ShadowPosition`` and schedules its real
``REVERSE_EXECUTABLE`` probes -- never a hand-built position row that
could silently diverge from the real fill path's own invariants.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from argus.clock import Clock
from argus.config import load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.chain_events import ChainEvent
from argus.domain.commitment import COMMITMENT_CONFIRMED, CommitmentObservation
from argus.domain.shadow_positions import ShadowPosition
from argus.domain.shadow_quote_probes import (
    OUTCOME_NO_ROUTE,
    OUTCOME_PROVIDER_CAPACITY_MISS,
    OUTCOME_QUOTE_FAILED,
    OUTCOME_SUCCESS,
    ShadowQuoteProbe,
)
from argus.domain.swaps import Swap
from argus.domain.wallet_score_snapshots import WalletScoreSnapshot
from argus.domain.wallet_tier_history import WalletTierTransition
from argus.domain.wallets import Wallet
from argus.providers.jupiter.client import JupiterClient
from argus.providers.retry import RetryPolicy
from argus.shadow.monitor import run_prospective_monitoring_pass
from argus.shadow.quote_jobs import run_due_entry_probes, run_due_reverse_probes

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("isolated_database")]

_NOW = datetime(2026, 6, 1, tzinfo=UTC)
_TEST_GIT_COMMIT = "TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB"
SOL_MINT = "So11111111111111111111111111111111111111112"


def _unique_wallet() -> str:
    return f"P4R2{uuid.uuid4().hex[:38]}"


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
) -> None:
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
            transaction_signature=f"p4r2-buy-{uuid.uuid4()}",
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
    session.add(
        Swap(
            swap_id=uuid.uuid4(),
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


async def _seed_intent_with_entry_probes(sessionmaker, config, *, wallet_address: str, mint: str):
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
    route_plan_override: list[Any] | None = None,
) -> dict[str, Any]:
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
    body["routePlan"] = (
        route_plan_override
        if route_plan_override is not None
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
) -> tuple[JupiterClient, httpx.AsyncClient]:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = JupiterClient(http_client=http_client, retry_policy=RetryPolicy(max_attempts=1))
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


async def _fill_entry_and_get_position(sessionmaker, config, intent) -> ShadowPosition:
    """Real entry-probe SUCCESS -> real ShadowPosition + real scheduled
    REVERSE_EXECUTABLE probes, via the actual production fill path."""

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

    provider, http_client = _jupiter_client(_counting_handler(respond))
    try:
        far_future = _NOW + timedelta(seconds=400)
        processed = await run_due_entry_probes(
            sessionmaker, provider, config=config, clock=Clock(), now=far_future, limit=1
        )
        assert processed[0].outcome == OUTCOME_SUCCESS
    finally:
        await http_client.aclose()

    async with sessionmaker() as session:
        return (
            await session.execute(
                select(ShadowPosition).where(
                    ShadowPosition.shadow_intent_id == intent.shadow_intent_id
                )
            )
        ).scalar_one()


async def _run_due_reverse_probe(
    sessionmaker, config, position, respond, *, due_offset=timedelta(minutes=5, seconds=1)
):
    provider, http_client = _jupiter_client(_counting_handler(respond))
    try:
        due = position.opened_at + due_offset
        results = await run_due_reverse_probes(
            sessionmaker, provider, config=config, clock=Clock(), now=due, limit=1
        )
        assert len(results) == 1
        return results[0]
    finally:
        await http_client.aclose()


# ---------------------------------------------------------------------
# AM-01: superscript-two in a nested route-plan amount, entry AND reverse
# probe kinds, through the real production worker. Pre-fix: an uncaught
# ValueError escapes run_due_entry_probes/run_due_reverse_probes entirely
# -- captured against target commit
# 29a49ff4aa2618ae016a6ed90cd8ba680310a95e before F-01.
# ---------------------------------------------------------------------


@pytest.mark.parametrize("nested_field", ["inAmount", "outAmount"])
async def test_am01_entry_worker_non_ascii_digit_amount_is_no_route_not_crash(
    admin_engine, nested_field: str
) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4R2Mint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
        intent = await _seed_intent_with_entry_probes(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )

        def respond(request: httpx.Request) -> httpx.Response:
            route_plan = _valid_route_plan(
                input_mint=intent.input_mint,
                output_mint=intent.output_mint,
                in_amount=intent.notional_input_amount_raw,
                out_amount=500_000,
            )
            route_plan[0]["swapInfo"][nested_field] = "²"
            return httpx.Response(
                200,
                json=_jupiter_quote_body(
                    input_mint=intent.input_mint,
                    output_mint=intent.output_mint,
                    in_amount=intent.notional_input_amount_raw,
                    out_amount=500_000,
                    route_plan_override=route_plan,
                ),
            )

        handler = _counting_handler(respond)
        provider, http_client = _jupiter_client(handler)
        try:
            far_future = _NOW + timedelta(seconds=400)
            processed = await run_due_entry_probes(
                sessionmaker, provider, config=config, clock=Clock(), now=far_future, limit=1
            )
            assert len(processed) == 1
            probe = processed[0]
            assert probe.outcome == OUTCOME_NO_ROUTE
            assert probe.terminal_at is not None
            assert probe.requested_at is not None
            assert probe.responded_at is not None
            assert probe.requested_at <= probe.responded_at
        finally:
            await http_client.aclose()

        async with sessionmaker() as session:
            positions = (
                (
                    await session.execute(
                        select(ShadowPosition).where(
                            ShadowPosition.shadow_intent_id == intent.shadow_intent_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert positions == []
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


async def test_am01_reverse_worker_non_ascii_digit_amount_is_no_route_not_crash(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4R2Mint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
        intent = await _seed_intent_with_entry_probes(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )
        position = await _fill_entry_and_get_position(sessionmaker, config, intent)

        def respond(request: httpx.Request) -> httpx.Response:
            route_plan = _valid_route_plan(
                input_mint=position.output_mint,
                output_mint=position.input_mint,
                in_amount=position.entry_output_amount_raw,
                out_amount=500_000,
            )
            route_plan[0]["swapInfo"]["outAmount"] = "²"
            return httpx.Response(
                200,
                json=_jupiter_quote_body(
                    input_mint=position.output_mint,
                    output_mint=position.input_mint,
                    in_amount=position.entry_output_amount_raw,
                    out_amount=500_000,
                    route_plan_override=route_plan,
                ),
            )

        outcome = await _run_due_reverse_probe(sessionmaker, config, position, respond)
        assert outcome.outcome == OUTCOME_NO_ROUTE
        assert outcome.terminal_at is not None
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# AM-03: fresh-session reload of an AM-01-style terminal record, then
# process again -- identity/outcome/timing unchanged, zero additional
# HTTP, zero additional shadow positions, no duplicate terminal evidence.
# ---------------------------------------------------------------------


async def test_am03_reload_and_reprocess_after_malformed_amount_is_idempotent(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4R2Mint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
        intent = await _seed_intent_with_entry_probes(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )

        def respond(request: httpx.Request) -> httpx.Response:
            route_plan = _valid_route_plan(
                input_mint=intent.input_mint,
                output_mint=intent.output_mint,
                in_amount=intent.notional_input_amount_raw,
                out_amount=500_000,
            )
            route_plan[0]["swapInfo"]["inAmount"] = "1" * 5000
            return httpx.Response(
                200,
                json=_jupiter_quote_body(
                    input_mint=intent.input_mint,
                    output_mint=intent.output_mint,
                    in_amount=intent.notional_input_amount_raw,
                    out_amount=500_000,
                    route_plan_override=route_plan,
                ),
            )

        handler = _counting_handler(respond)
        provider, http_client = _jupiter_client(handler)
        far_future = _NOW + timedelta(seconds=400)
        try:
            first = await run_due_entry_probes(
                sessionmaker, provider, config=config, clock=Clock(), now=far_future, limit=1
            )
            assert len(first) == 1
            assert first[0].outcome == OUTCOME_NO_ROUTE
            first_terminal_at = first[0].terminal_at
            first_id = first[0].probe_id
        finally:
            await http_client.aclose()

        # Fresh session/engine reload, then reprocess: nothing left claimable
        # (terminal_at is already set), so this must be a genuine no-op.
        config2, engine2, sessionmaker2 = _sessionmaker()
        try:
            second = await run_due_entry_probes(
                sessionmaker2,
                provider,
                config=config2,
                clock=Clock(),
                now=far_future + timedelta(seconds=1),
                limit=50,
            )
            assert not any(p.probe_id == first_id for p in second)

            async with sessionmaker2() as session:
                reloaded = await session.get(ShadowQuoteProbe, first_id)
                assert reloaded is not None
                assert reloaded.outcome == OUTCOME_NO_ROUTE
                assert reloaded.terminal_at == first_terminal_at
        finally:
            await engine2.dispose()
        assert len(handler.calls) == 1  # type: ignore[attr-defined]
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# AM-05: real HTTP 429 WITH a valid supplied errorCode, both worker
# kinds -- PROVIDER_CAPACITY_MISS, and the supplied code must now survive
# into failure_evidence. Pre-fix: the 429 branch returned before ever
# extracting errorCode, so the code was silently dropped -- captured
# against target commit 29a49ff4aa2618ae016a6ed90cd8ba680310a95e before
# F-02.
# ---------------------------------------------------------------------


async def test_am05_entry_worker_429_with_valid_code_preserves_code(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4R2Mint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
        await _seed_intent_with_entry_probes(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"errorCode": "AUDIT_RATE_LIMIT"})

        handler = _counting_handler(respond)
        provider, http_client = _jupiter_client(handler)
        try:
            far_future = _NOW + timedelta(seconds=400)
            processed = await run_due_entry_probes(
                sessionmaker, provider, config=config, clock=Clock(), now=far_future, limit=1
            )
            assert len(processed) == 1
            probe = processed[0]
            assert probe.outcome == OUTCOME_PROVIDER_CAPACITY_MISS
            assert probe.failure_evidence == {
                "http_status_code": 429,
                "provider_error_code": "AUDIT_RATE_LIMIT",
            }
        finally:
            await http_client.aclose()
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


async def test_am05_reverse_worker_429_with_valid_code_preserves_code(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4R2Mint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
        intent = await _seed_intent_with_entry_probes(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )
        position = await _fill_entry_and_get_position(sessionmaker, config, intent)

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"errorCode": "AUDIT_RATE_LIMIT"})

        outcome = await _run_due_reverse_probe(sessionmaker, config, position, respond)
        assert outcome.outcome == OUTCOME_PROVIDER_CAPACITY_MISS
        assert outcome.failure_evidence == {
            "http_status_code": 429,
            "provider_error_code": "AUDIT_RATE_LIMIT",
        }
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# AM-06: 429 with absent errorCode, invalid JSON, non-object JSON, or an
# unsafe/wrong-type code -- always PROVIDER_CAPACITY_MISS, status
# retained, no invented code.
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "make_response",
    [
        lambda: httpx.Response(429, json={"error": "Too Many Requests"}),
        lambda: httpx.Response(429, text="not json at all"),
        lambda: httpx.Response(429, json=["not", "an", "object"]),
        lambda: httpx.Response(429, json={"errorCode": "https://evil/?api_key=SECRET"}),
        lambda: httpx.Response(429, json={"errorCode": 12345}),
    ],
    ids=[
        "absent-error-code",
        "invalid-json-body",
        "non-object-json",
        "unsafe-shaped-code",
        "wrong-type-code",
    ],
)
async def test_am06_429_without_safe_code_stays_capacity_miss_no_invented_code(
    admin_engine, make_response
) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4R2Mint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
        await _seed_intent_with_entry_probes(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )

        def respond(request: httpx.Request) -> httpx.Response:
            return make_response()

        handler = _counting_handler(respond)
        provider, http_client = _jupiter_client(handler)
        try:
            far_future = _NOW + timedelta(seconds=400)
            processed = await run_due_entry_probes(
                sessionmaker, provider, config=config, clock=Clock(), now=far_future, limit=1
            )
            assert len(processed) == 1
            probe = processed[0]
            assert probe.outcome == OUTCOME_PROVIDER_CAPACITY_MISS
            assert probe.failure_evidence == {"http_status_code": 429}
        finally:
            await http_client.aclose()
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# AM-07: HTTP400 known no-route code; HTTP400 unknown safe code; HTTP429
# with the known no-route code -- respectively NO_ROUTE, QUOTE_FAILED,
# PROVIDER_CAPACITY_MISS, with the exact supplied valid code/status
# retained in every case.
# ---------------------------------------------------------------------


async def test_am07_400_known_no_route_code_is_no_route_with_code_preserved(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4R2Mint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
        await _seed_intent_with_entry_probes(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"errorCode": "COULD_NOT_FIND_ANY_ROUTE"})

        provider, http_client = _jupiter_client(_counting_handler(respond))
        try:
            far_future = _NOW + timedelta(seconds=400)
            processed = await run_due_entry_probes(
                sessionmaker, provider, config=config, clock=Clock(), now=far_future, limit=1
            )
            assert processed[0].outcome == OUTCOME_NO_ROUTE
            assert processed[0].failure_evidence == {
                "http_status_code": 400,
                "provider_error_code": "COULD_NOT_FIND_ANY_ROUTE",
            }
        finally:
            await http_client.aclose()
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


async def test_am07_400_unknown_safe_code_is_quote_failed_with_code_preserved(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4R2Mint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
        await _seed_intent_with_entry_probes(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"errorCode": "UNKNOWN_SAFE_CODE"})

        provider, http_client = _jupiter_client(_counting_handler(respond))
        try:
            far_future = _NOW + timedelta(seconds=400)
            processed = await run_due_entry_probes(
                sessionmaker, provider, config=config, clock=Clock(), now=far_future, limit=1
            )
            assert processed[0].outcome == OUTCOME_QUOTE_FAILED
            assert processed[0].failure_evidence == {
                "http_status_code": 400,
                "provider_error_code": "UNKNOWN_SAFE_CODE",
            }
        finally:
            await http_client.aclose()
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


async def test_am07_429_with_known_no_route_code_stays_capacity_miss_code_preserved(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4R2Mint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
        await _seed_intent_with_entry_probes(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"errorCode": "COULD_NOT_FIND_ANY_ROUTE"})

        provider, http_client = _jupiter_client(_counting_handler(respond))
        try:
            far_future = _NOW + timedelta(seconds=400)
            processed = await run_due_entry_probes(
                sessionmaker, provider, config=config, clock=Clock(), now=far_future, limit=1
            )
            # 429 always wins over any known-code mapping -- capacity miss,
            # never NO_ROUTE, even though the code happens to equal the
            # known no-route identifier.
            assert processed[0].outcome == OUTCOME_PROVIDER_CAPACITY_MISS
            assert processed[0].failure_evidence == {
                "http_status_code": 429,
                "provider_error_code": "COULD_NOT_FIND_ANY_ROUTE",
            }
        finally:
            await http_client.aclose()
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# AM-10: fresh-session reload + repeated processing after AM-05/07-style
# terminal writes -- exact sanitized evidence survives, zero additional
# HTTP, no new fill/duplicate row or changed terminal clocks.
# ---------------------------------------------------------------------


async def test_am10_reload_and_reprocess_after_429_with_code_is_idempotent(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4R2Mint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
        await _seed_intent_with_entry_probes(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"errorCode": "AUDIT_RATE_LIMIT"})

        handler = _counting_handler(respond)
        provider, http_client = _jupiter_client(handler)
        far_future = _NOW + timedelta(seconds=400)
        try:
            first = await run_due_entry_probes(
                sessionmaker, provider, config=config, clock=Clock(), now=far_future, limit=1
            )
            assert len(first) == 1
            first_evidence = first[0].failure_evidence
            first_terminal_at = first[0].terminal_at
            first_id = first[0].probe_id
        finally:
            await http_client.aclose()

        config2, engine2, sessionmaker2 = _sessionmaker()
        try:
            second = await run_due_entry_probes(
                sessionmaker2,
                provider,
                config=config2,
                clock=Clock(),
                now=far_future + timedelta(seconds=1),
                limit=50,
            )
            assert not any(p.probe_id == first_id for p in second)
            async with sessionmaker2() as session:
                reloaded = await session.get(ShadowQuoteProbe, first_id)
                assert reloaded is not None
                assert reloaded.failure_evidence == first_evidence
                assert reloaded.terminal_at == first_terminal_at
        finally:
            await engine2.dispose()
        assert len(handler.calls) == 1  # type: ignore[attr-defined]
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# AM-11: existing real PriorityScheduler rejection path -- referenced,
# not redesigned (P4-REC-03's frozen contract: "existing passing test may
# supply proof"). This assertion imports the SAME real RequestDropped
# classification the existing passing coverage already exercises, proving
# the F-01/F-02 changes did not touch it.
# ---------------------------------------------------------------------


async def test_am11_scheduler_drop_classification_unchanged_by_this_recovery() -> None:
    from argus.providers.scheduler import RequestDropped
    from argus.shadow.quote_jobs import _classify_provider_exception

    dropped = RequestDropped(reason="queue_full", priority_class="P4_prospective_copyability_quote")
    outcome, evidence = _classify_provider_exception(dropped)
    assert outcome == OUTCOME_PROVIDER_CAPACITY_MISS
    assert evidence == {
        "scheduler_drop_reason": "queue_full",
        "scheduler_priority_class": "P4_prospective_copyability_quote",
    }

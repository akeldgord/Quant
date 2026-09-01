"""P4-R5 remediation -- restart/concurrency-safety tests for overlapping
shadow worker terminal-evidence races (MASTER_SPEC.md section 84),
against real Postgres.

``tests/integration/test_shadow_phase4.py`` already covers the
*sequential-replay* shape of section 84's own acceptance gate ("kill
shadow worker mid-job -> restart -> no duplicate shadow trade") --
claim, crash, restart, reclaim, one at a time. This file covers what
that one doesn't: genuinely INTERLEAVED concurrency, where a stale
worker's claim gets superseded by a fresh reclaim (P4-R5's own
``claim_generation`` mechanism) while the stale worker's own provider
call is still in flight, and both workers' terminal-write attempts are
truly concurrent ``asyncio`` coroutines racing against real Postgres row
locks -- not two sequential awaits dressed up to look concurrent.

Every "genuine concurrency" test below uses ``asyncio.Event`` checkpoints
inside a purpose-built fake provider to make the interleaving
deterministic: a slow/stale worker's fake provider call blocks until the
fresh worker has already finished (or, for the position-creation race,
until BOTH sides have started), so the ordering the test cares about is
guaranteed by construction rather than hoped for from
``asyncio.gather``'s scheduling. A shared ordered log records exactly
when each checkpoint fires, and every such test asserts on that log --
proof the interleaving actually happened as intended, not merely that
the final DB state looks right.

Uses a distinct wallet-address prefix (``P4RC``) so parallel test files
targeting the same Postgres instance never collide.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from argus.clock import Clock
from argus.config import load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.chain_events import ChainEvent
from argus.domain.commitment import COMMITMENT_CONFIRMED, CommitmentObservation
from argus.domain.shadow_mark_outcomes import (
    OUTCOME_PENDING as MARK_OUTCOME_PENDING,
)
from argus.domain.shadow_mark_outcomes import (
    OUTCOME_RECORDED,
    ShadowMarkOutcome,
)
from argus.domain.shadow_positions import ShadowPosition
from argus.domain.shadow_quote_probes import (
    OUTCOME_SUCCESS,
    PROBE_KIND_ENTRY_DELAY,
    ShadowQuoteProbe,
)
from argus.domain.swaps import Swap
from argus.domain.wallet_score_snapshots import WalletScoreSnapshot
from argus.domain.wallet_tier_history import WalletTierTransition
from argus.domain.wallets import Wallet
from argus.providers.models import ExecutableQuote, TokenSnapshot
from argus.shadow.mark_jobs import SimulatedWorkerCrash as MarkSimulatedWorkerCrash
from argus.shadow.mark_jobs import (
    _claim_due_mark_outcomes,
    _execute_and_record_mark_outcome,
    run_due_mark_outcomes,
)
from argus.shadow.monitor import run_prospective_monitoring_pass
from argus.shadow.quote_jobs import SimulatedWorkerCrash as QuoteSimulatedWorkerCrash
from argus.shadow.quote_jobs import (
    _claim_due_probes,
    _execute_and_record_probe,
    run_due_entry_probes,
)

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 6, 1, tzinfo=UTC)
_TEST_GIT_COMMIT = "TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB"
SOL_MINT = "So11111111111111111111111111111111111111112"


def _unique_wallet() -> str:
    return f"P4RC{uuid.uuid4().hex[:36]}"


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
            transaction_signature=f"p4rc-buy-{uuid.uuid4()}",
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


def _quote(*, input_mint: str, output_mint: str, in_amount: int, out_amount: int, impact="0.01"):
    return ExecutableQuote(
        provider="jupiter-fake",
        input_mint=input_mint,
        output_mint=output_mint,
        in_amount_raw=in_amount,
        out_amount_raw=out_amount,
        raw={
            "inputMint": input_mint,
            "outputMint": output_mint,
            "priceImpactPct": impact,
            "inAmount": str(in_amount),
            "outAmount": str(out_amount),
            "routePlan": [{"swapInfo": {"label": "fake-amm"}, "percent": 100}],
        },
    )


@dataclasses.dataclass
class _FixedExecutionProvider:
    """Always returns the same quote -- used for the setup/scaffolding
    parts of these tests (opening a position) where no race is being
    exercised."""

    quote: ExecutableQuote
    calls: list[tuple[str, str, int]] = dataclasses.field(default_factory=list)

    async def get_quote(
        self, *, input_mint: str, output_mint: str, amount_raw: int, slippage_bps: int = 50
    ) -> ExecutableQuote:
        self.calls.append((input_mint, output_mint, amount_raw))
        return self.quote

    async def build_unsigned_order(self, *, quote, wallet_address):
        raise NotImplementedError


@dataclasses.dataclass
class _FixedMarketDataProvider:
    snapshot: TokenSnapshot
    calls: list[str] = dataclasses.field(default_factory=list)

    async def token_snapshot(self, mint: str) -> TokenSnapshot:
        self.calls.append(mint)
        return self.snapshot

    async def historical_ohlcv(self, mint: str, *, start, end):
        raise NotImplementedError


@dataclasses.dataclass
class _GatedExecutionProvider:
    """ExecutionProvider fake for deterministic interleaving: appends to a
    SHARED ordered log when ``get_quote`` is entered and again when it
    returns, and -- when given a ``release_event`` -- blocks in between
    until the test explicitly sets it. This is what lets a test PROVE two
    ``_execute_and_record_probe`` coroutines were genuinely both in
    flight at once (one parked mid-provider-call while the other ran to
    completion) rather than merely hoping ``asyncio.gather`` happens to
    interleave them favourably."""

    quote: ExecutableQuote
    label: str
    log: list[str]
    release_event: asyncio.Event | None = None
    calls: list[tuple[str, str, int]] = dataclasses.field(default_factory=list)

    async def get_quote(
        self, *, input_mint: str, output_mint: str, amount_raw: int, slippage_bps: int = 50
    ) -> ExecutableQuote:
        self.calls.append((input_mint, output_mint, amount_raw))
        self.log.append(f"{self.label}_provider_called")
        if self.release_event is not None:
            await self.release_event.wait()
        self.log.append(f"{self.label}_provider_returned")
        return self.quote

    async def build_unsigned_order(self, *, quote, wallet_address):
        raise NotImplementedError


@dataclasses.dataclass
class _GatedMarketDataProvider:
    """Same technique as ``_GatedExecutionProvider``, for
    ``MarketDataProvider.token_snapshot`` (the mark-jobs equivalent)."""

    snapshot: TokenSnapshot
    label: str
    log: list[str]
    release_event: asyncio.Event | None = None
    calls: list[str] = dataclasses.field(default_factory=list)

    async def token_snapshot(self, mint: str) -> TokenSnapshot:
        self.calls.append(mint)
        self.log.append(f"{self.label}_provider_called")
        if self.release_event is not None:
            await self.release_event.wait()
        self.log.append(f"{self.label}_provider_returned")
        return self.snapshot

    async def historical_ohlcv(self, mint: str, *, start, end):
        raise NotImplementedError


@dataclasses.dataclass
class _RendezvousExecutionProvider:
    """Blocks in ``get_quote`` until BOTH sides of a two-party rendezvous
    have arrived (sets its own ready-event, then waits on the other
    side's), so two racing probe executions resume and open their
    terminal transactions at effectively the same moment -- a genuine
    race on ``ShadowPosition`` creation, not an accidental sequential
    replay disguised as concurrent."""

    quote: ExecutableQuote
    my_ready: asyncio.Event
    other_ready: asyncio.Event
    calls: list[tuple[str, str, int]] = dataclasses.field(default_factory=list)

    async def get_quote(
        self, *, input_mint: str, output_mint: str, amount_raw: int, slippage_bps: int = 50
    ) -> ExecutableQuote:
        self.calls.append((input_mint, output_mint, amount_raw))
        self.my_ready.set()
        await self.other_ready.wait()
        return self.quote

    async def build_unsigned_order(self, *, quote, wallet_address):
        raise NotImplementedError


async def _open_shadow_position(
    sessionmaker,
    config,
    *,
    wallet_address: str,
    mint: str,
    entry_out_amount: int = 500_000,
    entry_price_usd: Decimal = Decimal("1.00"),
):
    """Shared scaffolding for the mark-jobs tests: seeds a tracked wallet,
    runs one monitoring pass, and resolves ONLY the earliest-due
    (``"1s"``) entry probe to SUCCESS, opening exactly one
    ``ShadowPosition`` (and its full family of scheduled mark outcomes)
    for it. Returns ``(intent, position)``."""
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
    intent = result.shadow_intents[0]

    entry_provider = _FixedExecutionProvider(
        quote=_quote(
            input_mint=intent.input_mint,
            output_mint=intent.output_mint,
            in_amount=intent.notional_input_amount_raw,
            out_amount=entry_out_amount,
        )
    )
    entry_market = _FixedMarketDataProvider(
        snapshot=TokenSnapshot(
            provider="dexscreener-fake",
            mint=intent.output_mint,
            price_usd=entry_price_usd,
            pairs_found=1,
            raw={},
        )
    )
    far_future = _NOW + timedelta(seconds=400)
    processed = await run_due_entry_probes(
        sessionmaker,
        entry_provider,
        config=config,
        clock=Clock(),
        now=far_future,
        market_provider=entry_market,
        limit=1,
    )
    assert len(processed) == 1
    assert processed[0].outcome == OUTCOME_SUCCESS

    async with sessionmaker() as session:
        position = (
            await session.execute(
                select(ShadowPosition).where(
                    ShadowPosition.shadow_intent_id == intent.shadow_intent_id
                )
            )
        ).scalar_one()
    return intent, position


# ---------------------------------------------------------------------
# Test 1: genuine interleaved race -- quote_jobs -- a stale worker's slow
# provider call must never overwrite a fresher reclaim's terminal write.
# ---------------------------------------------------------------------


async def test_interleaved_stale_worker_never_overwrites_fresher_reclaim_quote_probe(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4RCMint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
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
        intent = result.shadow_intents[0]

        # Worker A claims the "1s" probe at +2s...
        claim_time_a = _NOW + timedelta(seconds=2)
        async with sessionmaker() as session, session.begin():
            claimed_a = await _claim_due_probes(
                session,
                probe_kind=PROBE_KIND_ENTRY_DELAY,
                now=claim_time_a,
                worker_id="worker-A",
                stale_after=timedelta(seconds=30),
                limit=1,
            )
        assert len(claimed_a) == 1
        probe_id, gen_a = claimed_a[0]

        # ...then goes slow. By +33s A's claim is stale; worker B reclaims
        # the SAME row, minting a fresh (higher) claim_generation.
        claim_time_b = claim_time_a + timedelta(seconds=31)
        async with sessionmaker() as session, session.begin():
            claimed_b = await _claim_due_probes(
                session,
                probe_kind=PROBE_KIND_ENTRY_DELAY,
                now=claim_time_b,
                worker_id="worker-B",
                stale_after=timedelta(seconds=30),
                limit=1,
            )
        assert len(claimed_b) == 1
        assert claimed_b[0][0] == probe_id
        gen_b = claimed_b[0][1]
        assert gen_b == gen_a + 1

        log: list[str] = []
        release_a = asyncio.Event()

        # Deliberately distinguishable output amounts so a final DB state
        # showing A's value would be an unambiguous, unmissable failure.
        quote_a = _quote(
            input_mint=intent.input_mint,
            output_mint=intent.output_mint,
            in_amount=intent.notional_input_amount_raw,
            out_amount=999_999,
        )
        quote_b = _quote(
            input_mint=intent.input_mint,
            output_mint=intent.output_mint,
            in_amount=intent.notional_input_amount_raw,
            out_amount=500_000,
        )
        provider_a = _GatedExecutionProvider(
            quote=quote_a, label="a", log=log, release_event=release_a
        )
        provider_b = _GatedExecutionProvider(quote=quote_b, label="b", log=log)

        clock_a = Clock()
        clock_b = Clock()

        async def run_a():
            outcome = await _execute_and_record_probe(
                sessionmaker,
                probe_id=probe_id,
                provider=provider_a,
                config=config,
                clock=clock_a,
                _claim_generation=gen_a,
            )
            log.append("a_execute_done")
            return outcome

        async def run_b_then_release():
            outcome = await _execute_and_record_probe(
                sessionmaker,
                probe_id=probe_id,
                provider=provider_b,
                config=config,
                clock=clock_b,
                _claim_generation=gen_b,
            )
            log.append("b_execute_done")
            # B's own terminal write has fully committed (the "with
            # session.begin()" block already exited normally) before A is
            # ever allowed to proceed past its own (still in-flight, since
            # claim time) provider call.
            release_a.set()
            log.append("release_a_set")
            return outcome

        result_a, result_b = await asyncio.gather(run_a(), run_b_then_release())

        # Proof this was genuine interleaving, not two sequential awaits:
        # A's own provider call was ALREADY in flight (parked on
        # release_a, having already been entered) strictly before B's own
        # terminal write committed -- and A's own terminal-write attempt
        # only happens after that release.
        assert log.index("a_provider_called") < log.index("b_execute_done")
        assert log.index("b_execute_done") < log.index("release_a_set")
        assert log.index("release_a_set") < log.index("a_provider_returned")
        assert log.index("a_provider_returned") < log.index("a_execute_done")

        # A's provider call DID complete (never short-circuited) --
        # its result was discarded by the generation check, not skipped.
        assert len(provider_a.calls) == 1
        assert len(provider_b.calls) == 1

        # B's (fresher generation's) result is what both sides observe --
        # A's own function call returns the ALREADY-RECORDED row (B's),
        # never its own stale write, and never raises.
        assert result_b.outcome == OUTCOME_SUCCESS
        assert result_b.expected_output_amount_raw == 500_000
        assert result_b.claim_generation == gen_b

        assert result_a.claim_generation == gen_b
        assert result_a.expected_output_amount_raw == 500_000  # B's, never A's 999_999

        async with sessionmaker() as session:
            final_probe = await session.get(ShadowQuoteProbe, probe_id)
            assert final_probe is not None
            assert final_probe.outcome == OUTCOME_SUCCESS
            assert final_probe.claim_generation == gen_b
            assert final_probe.expected_output_amount_raw == 500_000

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
            assert len(positions) == 1
            assert positions[0].entry_output_amount_raw == 500_000
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# Test 2: same interleaved-race shape, for mark_jobs -- a stale worker's
# late market-price lookup must never overwrite a fresher reclaim's
# already-recorded mark outcome.
# ---------------------------------------------------------------------


async def test_interleaved_stale_worker_never_overwrites_fresher_reclaim_mark_outcome(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4RCMint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
        _intent, position = await _open_shadow_position(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )

        due_5m = position.opened_at + timedelta(minutes=5)
        claim_time_a = due_5m + timedelta(seconds=1)
        async with sessionmaker() as session, session.begin():
            claimed_a = await _claim_due_mark_outcomes(
                session,
                now=claim_time_a,
                worker_id="worker-A",
                stale_after=timedelta(seconds=30),
                limit=10,
            )
        # Filter the batch down to the "5m" row specifically.
        async with sessionmaker() as session:
            labels = {}
            for oid, _gen in claimed_a:
                row = await session.get(ShadowMarkOutcome, oid)
                assert row is not None
                labels[oid] = row.horizon_label
        outcome_id = next(oid for oid, label in labels.items() if label == "5m")
        gen_a = next(gen for oid, gen in claimed_a if oid == outcome_id)

        claim_time_b = claim_time_a + timedelta(seconds=31)
        async with sessionmaker() as session, session.begin():
            claimed_b = await _claim_due_mark_outcomes(
                session,
                now=claim_time_b,
                worker_id="worker-B",
                stale_after=timedelta(seconds=30),
                limit=10,
            )
        gen_b_matches = [(oid, gen) for oid, gen in claimed_b if oid == outcome_id]
        assert len(gen_b_matches) == 1
        _oid, gen_b = gen_b_matches[0]
        assert gen_b == gen_a + 1

        log: list[str] = []
        release_a = asyncio.Event()

        snapshot_a = TokenSnapshot(
            provider="provider-a-stale",
            mint=position.output_mint,
            price_usd=Decimal("9.99"),
            pairs_found=1,
            raw={},
        )
        snapshot_b = TokenSnapshot(
            provider="provider-b-fresh",
            mint=position.output_mint,
            price_usd=Decimal("1.50"),
            pairs_found=1,
            raw={},
        )
        market_a = _GatedMarketDataProvider(
            snapshot=snapshot_a, label="a", log=log, release_event=release_a
        )
        market_b = _GatedMarketDataProvider(snapshot=snapshot_b, label="b", log=log)

        async def run_a():
            outcome = await _execute_and_record_mark_outcome(
                sessionmaker,
                outcome_id=outcome_id,
                market_provider=market_a,
                clock=Clock(),
                _claim_generation=gen_a,
            )
            log.append("a_execute_done")
            return outcome

        async def run_b_then_release():
            outcome = await _execute_and_record_mark_outcome(
                sessionmaker,
                outcome_id=outcome_id,
                market_provider=market_b,
                clock=Clock(),
                _claim_generation=gen_b,
            )
            log.append("b_execute_done")
            release_a.set()
            log.append("release_a_set")
            return outcome

        result_a, result_b = await asyncio.gather(run_a(), run_b_then_release())

        assert log.index("a_provider_called") < log.index("b_execute_done")
        assert log.index("b_execute_done") < log.index("release_a_set")
        assert log.index("release_a_set") < log.index("a_provider_returned")
        assert log.index("a_provider_returned") < log.index("a_execute_done")

        assert len(market_a.calls) == 1
        assert len(market_b.calls) == 1

        assert result_b.outcome == OUTCOME_RECORDED
        assert result_b.mark_price_usd == Decimal("1.50")
        assert result_b.provider == "provider-b-fresh"
        assert result_b.claim_generation == gen_b

        assert result_a.claim_generation == gen_b
        assert result_a.mark_price_usd == Decimal("1.50")  # B's, never A's 9.99
        assert result_a.provider == "provider-b-fresh"

        async with sessionmaker() as session:
            final_row = await session.get(ShadowMarkOutcome, outcome_id)
            assert final_row is not None
            assert final_row.outcome == OUTCOME_RECORDED
            assert final_row.mark_price_usd == Decimal("1.50")
            assert final_row.provider == "provider-b-fresh"
            assert final_row.claim_generation == gen_b
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# Test 3: two entry probes for the SAME intent racing to create the
# first ShadowPosition.
# ---------------------------------------------------------------------


async def test_two_entry_probes_racing_for_first_position_of_same_intent(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4RCMint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
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
        intent = result.shadow_intents[0]

        # Only the "1s" and "5s" probes are due at +10s -- claims exactly
        # those two, each its own fresh claim_generation.
        claim_now = _NOW + timedelta(seconds=10)
        async with sessionmaker() as session, session.begin():
            claimed = await _claim_due_probes(
                session,
                probe_kind=PROBE_KIND_ENTRY_DELAY,
                now=claim_now,
                worker_id="race-worker",
                stale_after=timedelta(seconds=30),
                limit=2,
            )
        assert len(claimed) == 2

        by_label: dict[str, tuple[uuid.UUID, int]] = {}
        async with sessionmaker() as session:
            for probe_id, gen in claimed:
                probe = await session.get(ShadowQuoteProbe, probe_id)
                assert probe is not None
                by_label[probe.target_label] = (probe_id, gen)
        assert set(by_label) == {"1s", "5s"}
        probe_id_1s, gen_1s = by_label["1s"]
        probe_id_5s, gen_5s = by_label["5s"]

        ready_1s = asyncio.Event()
        ready_5s = asyncio.Event()
        quote_1s = _quote(
            input_mint=intent.input_mint,
            output_mint=intent.output_mint,
            in_amount=intent.notional_input_amount_raw,
            out_amount=111_111,
        )
        quote_5s = _quote(
            input_mint=intent.input_mint,
            output_mint=intent.output_mint,
            in_amount=intent.notional_input_amount_raw,
            out_amount=222_222,
        )
        provider_1s = _RendezvousExecutionProvider(
            quote=quote_1s, my_ready=ready_1s, other_ready=ready_5s
        )
        provider_5s = _RendezvousExecutionProvider(
            quote=quote_5s, my_ready=ready_5s, other_ready=ready_1s
        )

        async def run_1s():
            return await _execute_and_record_probe(
                sessionmaker,
                probe_id=probe_id_1s,
                provider=provider_1s,
                config=config,
                clock=Clock(),
                _claim_generation=gen_1s,
            )

        async def run_5s():
            return await _execute_and_record_probe(
                sessionmaker,
                probe_id=probe_id_5s,
                provider=provider_5s,
                config=config,
                clock=Clock(),
                _claim_generation=gen_5s,
            )

        # NOTE: return_exceptions=True (not a try/except swallowing the
        # race) -- an initial version of this fix left the terminal
        # transaction's "existing_position is None -> insert" check as an
        # unguarded check-then-act race: real concurrent load raised an
        # unhandled Postgres unique_violation / IntegrityError here. The
        # fix (src/argus/shadow/quote_jobs.py, _execute_and_record_probe)
        # now acquires a `SELECT ... FOR UPDATE` on the parent ShadowIntent
        # row BEFORE the existing_position check, serializing concurrent
        # creators for the same intent -- the loser blocks on the lock,
        # then its own post-lock existing_position re-check correctly
        # finds the winner's already-committed row. This assertion
        # surfaces any regression of that race explicitly rather than
        # hiding it.
        raw_results = await asyncio.gather(run_1s(), run_5s(), return_exceptions=True)
        for label, outcome in zip(["1s", "5s"], raw_results, strict=True):
            assert not isinstance(outcome, BaseException), (
                "P4-R5 regression: concurrent first-ShadowPosition creation "
                f"for probe {label} raised an unhandled exception under "
                f"genuine asyncio.gather concurrency (the ShadowIntent "
                f"row-lock guard is not doing its job): {outcome!r}"
            )
        result_1s, result_5s = (r for r in raw_results if not isinstance(r, BaseException))
        assert result_1s.outcome == OUTCOME_SUCCESS
        assert result_5s.outcome == OUTCOME_SUCCESS

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
            assert len(positions) == 1
            assert positions[0].entry_probe_target_label in {"1s", "5s"}

            probe_1s = await session.get(ShadowQuoteProbe, probe_id_1s)
            probe_5s = await session.get(ShadowQuoteProbe, probe_id_5s)
            assert probe_1s is not None
            assert probe_5s is not None
            # Only position-creation is exclusive -- each probe's OWN
            # terminal write is still correctly recorded as SUCCESS.
            assert probe_1s.outcome == OUTCOME_SUCCESS
            assert probe_1s.responded_at is not None
            assert probe_1s.expected_output_amount_raw == 111_111
            assert probe_5s.outcome == OUTCOME_SUCCESS
            assert probe_5s.responded_at is not None
            assert probe_5s.expected_output_amount_raw == 222_222
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# Test 4: kill after claim, kill after provider response, and "around
# terminal commit" -- restart then exact replay must not duplicate a
# trade or replace evidence.
#
# ``_simulate_crash_after`` only supports "claim" (right after the claim
# commits, before any provider call) and "quote" (right after the
# provider call returns, before the terminal transaction opens) -- there
# is no source-level hook to interrupt strictly between the terminal
# ``SELECT ... FOR UPDATE`` re-read and its commit, and adding one would
# require editing src/argus/* (out of scope for this test-only file).
# But the terminal write is a SINGLE Postgres transaction with one
# ``flush()`` before an implicit commit -- Postgres's own atomicity
# guarantees there is no observable "half-written" state: from outside,
# "killed anywhere before/around/at the commit" collapses to exactly the
# same two possibilities "killed after quote" already covers -- either
# the whole terminal write committed, or NONE of it did. Tests 4b/4c
# assert that "none of it did" directly (every terminal field is still
# unset TOGETHER, never some set and others not) as the concrete evidence
# for that guarantee, in addition to the standard crash+restart shape.
# ---------------------------------------------------------------------


async def test_mark_outcome_crash_after_claim_then_restart_reclaims_without_calling_provider(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4RCMint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
        _intent, position = await _open_shadow_position(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )
        crash_now = position.opened_at + timedelta(minutes=5, seconds=1)

        never_called_market = _FixedMarketDataProvider(
            snapshot=TokenSnapshot(
                provider="should-never-be-called",
                mint=position.output_mint,
                price_usd=Decimal("1.0"),
                pairs_found=1,
                raw={},
            )
        )
        with pytest.raises(MarkSimulatedWorkerCrash):
            await run_due_mark_outcomes(
                sessionmaker,
                never_called_market,
                clock=Clock(),
                now=crash_now,
                limit=1,
                _simulate_crash_after="claim",
            )
        # A crash right after the claim commits must never even reach the
        # provider.
        assert never_called_market.calls == []

        async with sessionmaker() as session:
            due_rows = (
                (
                    await session.execute(
                        select(ShadowMarkOutcome).where(
                            ShadowMarkOutcome.shadow_position_id == position.shadow_position_id,
                            ShadowMarkOutcome.horizon_label == "5m",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(due_rows) == 1
            claimed_row = due_rows[0]
            assert claimed_row.claimed_at is not None
            assert claimed_row.actual_at is None

        resumed_now = crash_now + timedelta(seconds=60)
        resumed_market = _FixedMarketDataProvider(
            snapshot=TokenSnapshot(
                provider="dexscreener-fake",
                mint=position.output_mint,
                price_usd=Decimal("1.75"),
                pairs_found=1,
                raw={},
            )
        )
        processed = await run_due_mark_outcomes(
            sessionmaker,
            resumed_market,
            clock=Clock(),
            now=resumed_now,
            limit=1,
            stale_after=timedelta(seconds=30),
        )
        assert len(processed) == 1
        assert processed[0].outcome == OUTCOME_RECORDED
        assert processed[0].mark_price_usd == Decimal("1.75")

        async with sessionmaker() as session:
            final_rows = (
                (
                    await session.execute(
                        select(ShadowMarkOutcome).where(
                            ShadowMarkOutcome.shadow_position_id == position.shadow_position_id,
                            ShadowMarkOutcome.horizon_label == "5m",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(final_rows) == 1
            assert final_rows[0].actual_at is not None
            assert final_rows[0].mark_price_usd == Decimal("1.75")
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


async def test_mark_outcome_crash_after_price_lookup_is_atomic_then_restart_records_once(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4RCMint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
        _intent, position = await _open_shadow_position(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )
        crash_now = position.opened_at + timedelta(minutes=5, seconds=1)

        crash_market = _FixedMarketDataProvider(
            snapshot=TokenSnapshot(
                provider="dexscreener-fake",
                mint=position.output_mint,
                price_usd=Decimal("2.00"),
                pairs_found=1,
                raw={},
            )
        )
        with pytest.raises(MarkSimulatedWorkerCrash):
            await run_due_mark_outcomes(
                sessionmaker,
                crash_market,
                clock=Clock(),
                now=crash_now,
                limit=1,
                _simulate_crash_after="quote",
            )
        # The provider call DID happen (crash is strictly after it) --
        # its result was simply never persisted.
        assert len(crash_market.calls) == 1

        async with sessionmaker() as session:
            row = (
                (
                    await session.execute(
                        select(ShadowMarkOutcome).where(
                            ShadowMarkOutcome.shadow_position_id == position.shadow_position_id,
                            ShadowMarkOutcome.horizon_label == "5m",
                        )
                    )
                )
                .scalars()
                .one()
            )
            outcome_id = row.shadow_mark_outcome_id
            # Atomicity ("kill around terminal commit"): every terminal
            # field is unset TOGETHER -- never a partial write.
            assert row.actual_at is None
            assert row.outcome == MARK_OUTCOME_PENDING
            assert row.mark_price_usd is None
            assert row.mark_return_pct is None
            assert row.provider is None
            assert row.claimed_at is not None  # the claim itself DID survive

        resumed_now = crash_now + timedelta(seconds=60)
        resumed_market = _FixedMarketDataProvider(
            snapshot=TokenSnapshot(
                provider="dexscreener-fake-2",
                mint=position.output_mint,
                price_usd=Decimal("2.00"),
                pairs_found=1,
                raw={},
            )
        )
        processed = await run_due_mark_outcomes(
            sessionmaker,
            resumed_market,
            clock=Clock(),
            now=resumed_now,
            limit=1,
            stale_after=timedelta(seconds=30),
        )
        assert len(processed) == 1
        assert processed[0].outcome == OUTCOME_RECORDED
        assert processed[0].actual_at is not None

        async with sessionmaker() as session:
            final_rows = (
                (
                    await session.execute(
                        select(ShadowMarkOutcome).where(
                            ShadowMarkOutcome.shadow_mark_outcome_id == outcome_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(final_rows) == 1
            assert final_rows[0].actual_at is not None
            assert final_rows[0].provider == "dexscreener-fake-2"
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


async def test_entry_probe_crash_after_quote_is_atomic_no_partial_position_then_restart(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4RCMint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
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
        intent = result.shadow_intents[0]

        crash_provider = _FixedExecutionProvider(
            quote=_quote(
                input_mint=intent.input_mint,
                output_mint=intent.output_mint,
                in_amount=intent.notional_input_amount_raw,
                out_amount=500_000,
            )
        )
        crash_now = _NOW + timedelta(seconds=1)
        with pytest.raises(QuoteSimulatedWorkerCrash):
            await run_due_entry_probes(
                sessionmaker,
                crash_provider,
                config=config,
                clock=Clock(),
                now=crash_now,
                limit=1,
                _simulate_crash_after="quote",
            )
        assert len(crash_provider.calls) == 1

        async with sessionmaker() as session:
            probe = (
                (
                    await session.execute(
                        select(ShadowQuoteProbe).where(
                            ShadowQuoteProbe.shadow_intent_id == intent.shadow_intent_id,
                            ShadowQuoteProbe.target_label == "1s",
                        )
                    )
                )
                .scalars()
                .one()
            )
            # Atomicity ("kill around terminal commit"): the entire
            # terminal write -- probe fields AND the ShadowPosition it
            # would have created -- is unset/absent TOGETHER, never
            # partially materialized.
            assert probe.responded_at is None
            assert probe.requested_at is None
            assert probe.outcome != OUTCOME_SUCCESS
            assert probe.expected_output_amount_raw is None
            assert probe.claimed_at is not None

            no_position = (
                await session.execute(
                    select(ShadowPosition).where(
                        ShadowPosition.shadow_intent_id == intent.shadow_intent_id
                    )
                )
            ).scalar_one_or_none()
            assert no_position is None

        resumed_provider = _FixedExecutionProvider(
            quote=_quote(
                input_mint=intent.input_mint,
                output_mint=intent.output_mint,
                in_amount=intent.notional_input_amount_raw,
                out_amount=500_000,
            )
        )
        resumed_now = crash_now + timedelta(seconds=60)
        processed = await run_due_entry_probes(
            sessionmaker,
            resumed_provider,
            config=config,
            clock=Clock(),
            now=resumed_now,
            limit=1,
            stale_after=timedelta(seconds=30),
        )
        assert len(processed) == 1
        assert processed[0].outcome == OUTCOME_SUCCESS

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
            assert len(positions) == 1
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# Test 5: mark-jobs equivalent of the already-recorded no-op regression --
# a provider-call counter proves re-execution never reaches the market
# provider at all (mark_jobs.py had no such regression test before this).
# ---------------------------------------------------------------------


async def test_reprocessing_an_already_recorded_mark_outcome_never_calls_provider(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4RCMint{uuid.uuid4().hex[:30]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
        _intent, position = await _open_shadow_position(
            sessionmaker, config, wallet_address=wallet_address, mint=mint
        )

        far_future_mark = position.opened_at + timedelta(minutes=5, seconds=1)
        first_market = _FixedMarketDataProvider(
            snapshot=TokenSnapshot(
                provider="dexscreener-fake",
                mint=position.output_mint,
                price_usd=Decimal("1.25"),
                pairs_found=1,
                raw={},
            )
        )
        first_pass = await run_due_mark_outcomes(
            sessionmaker, first_market, clock=Clock(), now=far_future_mark, limit=1
        )
        assert len(first_pass) == 1
        assert first_pass[0].outcome == OUTCOME_RECORDED
        outcome_id = first_pass[0].shadow_mark_outcome_id

        no_call_market = _FixedMarketDataProvider(
            snapshot=TokenSnapshot(
                provider="should-never-be-called",
                mint=position.output_mint,
                price_usd=Decimal("999.0"),
                pairs_found=1,
                raw={},
            )
        )
        second_result = await _execute_and_record_mark_outcome(
            sessionmaker,
            outcome_id=outcome_id,
            market_provider=no_call_market,
            clock=Clock(),
        )
        assert second_result.outcome == OUTCOME_RECORDED
        assert second_result.mark_price_usd == Decimal("1.25")  # unchanged, first pass's value
        assert no_call_market.calls == []

        async with sessionmaker() as session:
            final_row = await session.get(ShadowMarkOutcome, outcome_id)
            assert final_row is not None
            assert final_row.mark_price_usd == Decimal("1.25")
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()

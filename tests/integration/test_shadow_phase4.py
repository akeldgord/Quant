"""Phase 4 (PROSPECTIVE MONITORING + SHADOW COPYING) focused acceptance
tests against real Postgres -- MASTER_SPEC.md sections 44-48, 84, per
orchestrator instruction `argus-phase-4-001`'s own frozen acceptance
gate table.

Covers, against the real production service functions (never a
duplicated test-only reimplementation):

- observation timestamp / point-in-time score-context freezing (gates 1-2)
- actual quote latency recorded, never asserted (gate 3)
- executable return distinct from mark return (gate 4)
- unsellable outcomes preserved as real, distinct rows (gate 5)
- provider-capacity miss is honest missing data (gate 6)
- shadow restart/no-duplicate-fill (gate 9, section 84)
"""

from __future__ import annotations

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
from argus.domain.prospective_events import ProspectiveEvent
from argus.domain.shadow_intents import STATUS_NO_FILL, ShadowIntent
from argus.domain.shadow_mark_outcomes import OUTCOME_RECORDED
from argus.domain.shadow_positions import ShadowPosition
from argus.domain.shadow_quote_probes import (
    OUTCOME_INSUFFICIENT_LIQUIDITY,
    OUTCOME_NO_ROUTE,
    OUTCOME_PROVIDER_CAPACITY_MISS,
    OUTCOME_SUCCESS,
    OUTCOME_TOKEN_RESTRICTED,
    ShadowQuoteProbe,
)
from argus.domain.swaps import Swap
from argus.domain.wallet_score_snapshots import WalletScoreSnapshot
from argus.domain.wallet_tier_history import WalletTierTransition
from argus.domain.wallets import Wallet
from argus.providers.models import ExecutableQuote, TokenSnapshot
from argus.shadow.errors import (
    InsufficientLiquidityError,
    NoRouteError,
    ProviderCapacityMissError,
    TokenRestrictedError,
)
from argus.shadow.intents import entry_probe_label
from argus.shadow.mark_jobs import run_due_mark_outcomes
from argus.shadow.monitor import run_prospective_monitoring_pass
from argus.shadow.prospective import scan_for_new_prospective_events
from argus.shadow.quote_jobs import (
    SimulatedWorkerCrash,
    run_due_entry_probes,
    run_due_reverse_probes,
)

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 6, 1, tzinfo=UTC)
_TEST_GIT_COMMIT = "TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB"
SOL_MINT = "So11111111111111111111111111111111111111112"


def _unique_wallet() -> str:
    return f"P4W{uuid.uuid4().hex[:38]}"


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
    # P4-R1 remediation: wallet_tier_snapshot is resolved from real
    # WalletTierTransition history as-of first_seen_at, never trusted
    # from wallets.current_tier alone -- every test wallet needs a real
    # transition row for its tier to be honestly picked up.
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
            transaction_signature=f"p4-buy-{uuid.uuid4()}",
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
            # A real Jupiter quote's non-empty routePlan -- required
            # route evidence since P4-R4's _classify_quote fix.
            # P4-REC-02: swapInfo must carry its own genuine
            # inputMint/outputMint/inAmount/outAmount fields (not merely
            # be a dict) to be structurally valid route evidence.
            "routePlan": [
                {
                    "swapInfo": {
                        "label": "fake-amm",
                        "inputMint": input_mint,
                        "outputMint": output_mint,
                        "inAmount": str(in_amount),
                        "outAmount": str(out_amount),
                    },
                    "percent": 100,
                }
            ],
        },
    )


@dataclasses.dataclass
class QueuedExecutionProvider:
    queue: list[ExecutableQuote | Exception] = dataclasses.field(default_factory=list)
    calls: list[tuple[str, str, int]] = dataclasses.field(default_factory=list)

    async def get_quote(
        self, *, input_mint: str, output_mint: str, amount_raw: int, slippage_bps: int = 50
    ) -> ExecutableQuote:
        self.calls.append((input_mint, output_mint, amount_raw))
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def build_unsigned_order(self, *, quote, wallet_address):
        raise NotImplementedError


@dataclasses.dataclass
class QueuedMarketDataProvider:
    queue: list[TokenSnapshot | Exception] = dataclasses.field(default_factory=list)
    calls: list[str] = dataclasses.field(default_factory=list)

    async def token_snapshot(self, mint: str) -> TokenSnapshot:
        self.calls.append(mint)
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def historical_ohlcv(self, mint: str, *, start, end):
        raise NotImplementedError


class _ScriptedClock(Clock):
    def __init__(self, times: list[datetime]) -> None:
        super().__init__()
        self._times = iter(times)

    def utc_now(self) -> datetime:
        return next(self._times)


# ---------------------------------------------------------------------
# Gates 1-2: observation timestamp / point-in-time score-context frozen.
# ---------------------------------------------------------------------


async def test_prospective_event_snapshot_is_frozen_after_later_rescoring(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4Mint{uuid.uuid4().hex[:32]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            wallet_id, swap_id = await _seed_tracked_wallet_with_buy_swap(
                session,
                wallet_address=wallet_address,
                tier="A",
                score=Decimal("90.000"),
                mint=mint,
                at=_NOW,
            )

        async with sessionmaker() as session, session.begin():
            created = await scan_for_new_prospective_events(
                session, tier_allowed=["A", "S"], now=_NOW
            )
        assert len(created) == 1
        event = created[0]
        assert event.swap_id == swap_id
        assert event.wallet_score_snapshot == Decimal("90.000")
        assert event.wallet_tier_snapshot == "A"
        assert event.first_seen_at == _NOW
        assert event.confirmation_time == _NOW
        assert event.leader_transaction_time == _NOW

        # A later re-score and tier demotion must never rewrite this
        # already-created event's own frozen snapshot (gate 2).
        later = _NOW + timedelta(hours=1)
        async with sessionmaker() as session, session.begin():
            wallet = await session.get(Wallet, wallet_id)
            wallet.current_tier = "QUARANTINE"
            session.add(
                WalletScoreSnapshot(
                    score_id=uuid.uuid4(),
                    wallet_id=wallet_id,
                    as_of=later,
                    score_version="test-v1",
                    descriptive_score=Decimal("10.000"),
                    qualification_score=Decimal("10.000"),
                    component_values={},
                    penalties={},
                    confidence="HIGH",
                    excluded_discovery_token_ids=[],
                    eligible_for_qualification=False,
                    sample_gate_reason="test",
                    build_hash="test-build",
                    config_hash="test-config",
                    master_spec_hash="test-spec",
                    git_commit=_TEST_GIT_COMMIT,
                    created_at=later,
                )
            )

        async with sessionmaker() as session:
            reloaded = (
                await session.execute(
                    select(ProspectiveEvent).where(
                        ProspectiveEvent.prospective_event_id == event.prospective_event_id
                    )
                )
            ).scalar_one()
            assert reloaded.wallet_score_snapshot == Decimal("90.000")
            assert reloaded.wallet_tier_snapshot == "A"

        # Duplicate/late replay of the same scan never creates a second
        # event for the same swap, and never touches the original row
        # (gate 1's "duplicate/late replay ... preserve original
        # first-seen").
        async with sessionmaker() as session, session.begin():
            replay_created = await scan_for_new_prospective_events(
                session, tier_allowed=["A", "S", "QUARANTINE"], now=later
            )
        assert replay_created == []
        async with sessionmaker() as session:
            count = (
                (
                    await session.execute(
                        select(ProspectiveEvent).where(ProspectiveEvent.swap_id == swap_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(count) == 1
            assert count[0].wallet_score_snapshot == Decimal("90.000")
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


async def test_shadow_intent_monitoring_pass_creates_intent_and_probes(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4Mint{uuid.uuid4().hex[:32]}"
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
        assert len(result.prospective_events) == 1
        assert len(result.shadow_intents) == 1
        intent = result.shadow_intents[0]
        assert intent.input_mint == config.get("shadow_copy.notional_input_mint")

        async with sessionmaker() as session:
            probes = (
                (
                    await session.execute(
                        select(ShadowQuoteProbe).where(
                            ShadowQuoteProbe.shadow_intent_id == intent.shadow_intent_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            labels = sorted(p.target_label for p in probes)
            assert labels == sorted(entry_probe_label(s) for s in [1, 5, 15, 30, 60, 300])
            for probe in probes:
                expected_due = _NOW + timedelta(seconds=int(probe.target_label.removesuffix("s")))
                assert probe.target_due_at == expected_due
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


async def test_ineligible_wallet_gets_no_shadow_intent(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4Mint{uuid.uuid4().hex[:32]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            await _seed_tracked_wallet_with_buy_swap(
                session,
                wallet_address=wallet_address,
                tier="B",  # not in wallet_tier_allowed [A, S]
                score=Decimal("90.000"),
                mint=mint,
                at=_NOW,
            )

        result = await run_prospective_monitoring_pass(
            sessionmaker, config=config, now=_NOW, tier_allowed=["A", "B", "S"]
        )
        assert len(result.prospective_events) == 1
        assert result.shadow_intents == ()
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# Gate 3: quote actual latency recorded, never asserted.
# ---------------------------------------------------------------------


async def test_entry_probe_records_actual_latency_not_target_delay(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4Mint{uuid.uuid4().hex[:32]}"
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

        # Target for the "1s" probe is _NOW + 1s. The real request is
        # made 2.7s late; the response arrives 100ms after that -- never
        # reported as a false "+1s" observation.
        target_due_at = _NOW + timedelta(seconds=1)
        actual_requested_at = target_due_at + timedelta(seconds=2.7)
        actual_responded_at = actual_requested_at + timedelta(milliseconds=100)
        actual_terminal_at = actual_responded_at + timedelta(milliseconds=5)
        clock = _ScriptedClock([actual_requested_at, actual_responded_at, actual_terminal_at])

        provider = QueuedExecutionProvider(
            queue=[
                _quote(
                    input_mint=intent.input_mint,
                    output_mint=intent.output_mint,
                    in_amount=intent.notional_input_amount_raw,
                    out_amount=500_000,
                )
            ]
        )
        processed = await run_due_entry_probes(
            sessionmaker,
            provider,
            config=config,
            clock=clock,
            now=actual_requested_at + timedelta(seconds=10),
            limit=1,
        )
        assert len(processed) == 1
        probe = processed[0]
        assert probe.target_label == "1s"
        assert probe.requested_at == actual_requested_at
        assert probe.responded_at == actual_responded_at
        assert probe.scheduling_delay_seconds == Decimal("2.7")
        assert probe.latency_ms == 100
        assert probe.outcome == OUTCOME_SUCCESS
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# Gate 5: unsellable outcomes preserved as real, distinct rows.
# Gate 6: provider-capacity miss is missing data, never fabricated.
# ---------------------------------------------------------------------


async def test_all_entry_probes_fail_with_distinct_unsellable_reasons_intent_becomes_no_fill(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4Mint{uuid.uuid4().hex[:32]}"
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

        # Ordered to match claim order (ascending target_due_at: 1s, 5s,
        # 15s, 30s, 60s, 300s).
        provider = QueuedExecutionProvider(
            queue=[
                NoRouteError("no route"),
                InsufficientLiquidityError("insufficient liquidity"),
                TokenRestrictedError("token restricted"),
                ProviderCapacityMissError("capacity exhausted"),
                RuntimeError("unclassified failure"),  # -> QUOTE_FAILED
                NoRouteError("no route again"),
            ]
        )
        far_future = _NOW + timedelta(seconds=400)
        processed = await run_due_entry_probes(
            sessionmaker, provider, config=config, clock=Clock(), now=far_future, limit=10
        )
        assert len(processed) == 6
        outcomes = {p.target_label: p.outcome for p in processed}
        assert outcomes["1s"] == OUTCOME_NO_ROUTE
        assert outcomes["5s"] == OUTCOME_INSUFFICIENT_LIQUIDITY
        assert outcomes["15s"] == OUTCOME_TOKEN_RESTRICTED
        assert outcomes["30s"] == OUTCOME_PROVIDER_CAPACITY_MISS
        assert outcomes["300s"] == OUTCOME_NO_ROUTE

        capacity_miss_probe = next(p for p in processed if p.target_label == "30s")
        # A provider-capacity miss is a real, honest missing observation
        # -- never a fabricated fill/return (gate 6).
        assert capacity_miss_probe.expected_output_amount_raw is None
        assert capacity_miss_probe.route_present is False

        async with sessionmaker() as session:
            reloaded_intent = await session.get(ShadowIntent, intent.shadow_intent_id)
            assert reloaded_intent.status == STATUS_NO_FILL
            no_position = (
                await session.execute(
                    select(ShadowPosition).where(
                        ShadowPosition.shadow_intent_id == intent.shadow_intent_id
                    )
                )
            ).scalar_one_or_none()
            assert no_position is None
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# Gate 4: executable return distinct from mark return.
# ---------------------------------------------------------------------


async def test_executable_return_distinct_from_mark_return_for_same_position(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4Mint{uuid.uuid4().hex[:32]}"
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

        entry_provider = QueuedExecutionProvider(
            queue=[
                _quote(
                    input_mint=intent.input_mint,
                    output_mint=intent.output_mint,
                    in_amount=intent.notional_input_amount_raw,
                    out_amount=500_000,
                )
            ]
        )
        entry_market = QueuedMarketDataProvider(
            queue=[
                TokenSnapshot(
                    provider="dexscreener-fake",
                    mint=intent.output_mint,
                    price_usd=Decimal("1.00"),
                    pairs_found=1,
                    raw={},
                )
            ]
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
        assert processed[0].outcome == OUTCOME_SUCCESS

        async with sessionmaker() as session:
            position = (
                await session.execute(
                    select(ShadowPosition).where(
                        ShadowPosition.shadow_intent_id == intent.shadow_intent_id
                    )
                )
            ).scalar_one()
            assert position.entry_price_usd == Decimal("1.00")

        # The position's mark price rises 50% -- a strongly positive mark
        # return -- but its reverse-executable quote has NO real route.
        reverse_provider = QueuedExecutionProvider(queue=[NoRouteError("no route out")])
        reverse_due = position.opened_at + timedelta(minutes=5, seconds=1)
        reverse_results = await run_due_reverse_probes(
            sessionmaker, reverse_provider, config=config, clock=Clock(), now=reverse_due, limit=10
        )
        assert len(reverse_results) == 1
        assert reverse_results[0].outcome == OUTCOME_NO_ROUTE
        assert reverse_results[0].expected_output_amount_raw is None

        mark_market = QueuedMarketDataProvider(
            queue=[
                TokenSnapshot(
                    provider="dexscreener-fake",
                    mint=position.output_mint,
                    price_usd=Decimal("1.50"),
                    pairs_found=1,
                    raw={},
                )
            ]
        )
        mark_results = await run_due_mark_outcomes(
            sessionmaker, mark_market, clock=Clock(), now=reverse_due, limit=10
        )
        matured_5m = next(m for m in mark_results if m.horizon_label == "5m")
        assert matured_5m.outcome == OUTCOME_RECORDED
        assert matured_5m.mark_return_pct == Decimal("0.5")

        # Distinct outcomes on the SAME position: a positive mark return
        # never overrides or is overridden by the genuinely unsellable
        # executable outcome (gate 4).
        assert matured_5m.mark_return_pct is not None
        assert reverse_results[0].outcome == OUTCOME_NO_ROUTE
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# Gate 9 (section 84): shadow restart -- no duplicate shadow trade.
# ---------------------------------------------------------------------


async def test_crash_after_quote_before_record_reclaims_probe_no_duplicate_position(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mint = f"P4Mint{uuid.uuid4().hex[:32]}"
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

        crash_provider = QueuedExecutionProvider(
            queue=[
                _quote(
                    input_mint=intent.input_mint,
                    output_mint=intent.output_mint,
                    in_amount=intent.notional_input_amount_raw,
                    out_amount=500_000,
                )
            ]
        )
        first_now = _NOW + timedelta(seconds=1)
        with pytest.raises(SimulatedWorkerCrash):
            await run_due_entry_probes(
                sessionmaker,
                crash_provider,
                config=config,
                clock=Clock(),
                now=first_now,
                limit=1,
                _simulate_crash_after="quote",
            )

        async with sessionmaker() as session:
            probes = (
                (
                    await session.execute(
                        select(ShadowQuoteProbe).where(
                            ShadowQuoteProbe.shadow_intent_id == intent.shadow_intent_id,
                            ShadowQuoteProbe.target_label == "1s",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(probes) == 1
            claimed_probe = probes[0]
            assert claimed_probe.claimed_at is not None
            assert claimed_probe.responded_at is None
            no_position = (
                await session.execute(
                    select(ShadowPosition).where(
                        ShadowPosition.shadow_intent_id == intent.shadow_intent_id
                    )
                )
            ).scalar_one_or_none()
            assert no_position is None

        # Restart: the claim goes stale, a fresh pass reclaims and
        # actually completes the SAME probe -- exactly one position,
        # never two, never a rewritten original observation timestamp
        # request semantics.
        resumed_provider = QueuedExecutionProvider(
            queue=[
                _quote(
                    input_mint=intent.input_mint,
                    output_mint=intent.output_mint,
                    in_amount=intent.notional_input_amount_raw,
                    out_amount=500_000,
                )
            ]
        )
        second_now = first_now + timedelta(seconds=60)
        processed = await run_due_entry_probes(
            sessionmaker,
            resumed_provider,
            config=config,
            clock=Clock(),
            now=second_now,
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


async def test_reprocessing_an_already_responded_probe_is_a_no_op(admin_engine) -> None:
    """A worker that somehow re-executes an already-recorded probe
    (e.g. a duplicate delivery of the same claimed job) never writes a
    second response or creates a second position."""
    wallet_address = _unique_wallet()
    mint = f"P4Mint{uuid.uuid4().hex[:32]}"
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

        provider = QueuedExecutionProvider(
            queue=[
                _quote(
                    input_mint=intent.input_mint,
                    output_mint=intent.output_mint,
                    in_amount=intent.notional_input_amount_raw,
                    out_amount=500_000,
                )
            ]
        )
        far_future = _NOW + timedelta(seconds=400)
        first_pass = await run_due_entry_probes(
            sessionmaker, provider, config=config, clock=Clock(), now=far_future, limit=1
        )
        probe_id = first_pass[0].probe_id

        from argus.shadow.quote_jobs import _execute_and_record_probe

        # P4-R5: a call counter, not just a queued exception, proves the
        # already-terminal probe's re-execution never reaches the
        # provider at all -- catching the "should never be called"
        # RuntimeError alone would mask an actual provider call whose
        # result is merely discarded afterward.
        no_call_provider = QueuedExecutionProvider(queue=[RuntimeError("should never be called")])
        second_result = await _execute_and_record_probe(
            sessionmaker,
            probe_id=probe_id,
            provider=no_call_provider,
            config=config,
            clock=Clock(),
        )
        assert second_result.outcome == OUTCOME_SUCCESS
        assert no_call_provider.calls == []

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

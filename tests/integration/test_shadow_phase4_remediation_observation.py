"""Phase 4 remediation (`argus-phase-4-remediation-001`) observation tests
against real Postgres -- proving P4-R1/P4-R2/P4-R3 actually hold, using
the real production functions (never a duplicated re-implementation of
the query logic).

P4-R1 (``argus.shadow.prospective``): a prospective event's frozen
snapshot reflects ONLY evidence that existed as of ``swap.first_seen_at``
(the immutable knowledge cutoff), never evidence created later even if it
already exists in the DB by scan time.

P4-R2 (``argus.shadow.intents``): entry-delay probe ``target_due_at`` is
anchored to ``event.first_seen_at``, never to wall-clock scan time;
``created_at`` columns still honestly record the real row-creation
instant.

P4-R3 (``argus.shadow.prospective``/``argus.shadow.monitor``): the
candidate-swap scan excludes already-claimed events before any SQL LIMIT
(no starvation across bounded passes); ``revisit_pending_confirmations``
exposes a late confirmation exactly once without touching frozen fields;
two parser artifacts of one transaction produce only one prospective
event.
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
from argus.domain.shadow_intents import ShadowIntent
from argus.domain.shadow_quote_probes import ShadowQuoteProbe
from argus.domain.swaps import Swap
from argus.domain.token_market_snapshots import TokenMarketSnapshot
from argus.domain.tokens import LIFECYCLE_AMM_POOL, Token
from argus.domain.wallet_cluster_links import EVIDENCE_SYNCHRONIZED_ACTIVITY, WalletClusterLink
from argus.domain.wallet_history_quality import WalletHistoryQuality
from argus.domain.wallet_positions import CONFIDENCE_HIGH, STATUS_OPEN, WalletPosition
from argus.domain.wallet_score_snapshots import WalletScoreSnapshot
from argus.domain.wallet_tier_history import TIER_DISCOVERED, WalletTierTransition
from argus.domain.wallets import Wallet
from argus.providers.models import ExecutableQuote
from argus.shadow.intents import entry_probe_label
from argus.shadow.monitor import run_prospective_monitoring_pass
from argus.shadow.prospective import revisit_pending_confirmations, scan_for_new_prospective_events
from argus.shadow.quote_jobs import run_due_entry_probes

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 6, 1, tzinfo=UTC)
_TEST_GIT_COMMIT = "TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFCD"
SOL_MINT = "So11111111111111111111111111111111111111112"


def _unique_wallet() -> str:
    return f"P4RO{uuid.uuid4().hex[:37]}"


def _unique_mint() -> str:
    return f"P4ROMint{uuid.uuid4().hex[:31]}"


def _sessionmaker() -> tuple[Any, Any, Any]:
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
                text("DELETE FROM wallet_positions WHERE wallet_id = :w"), {"w": wid}
            )
            await conn.execute(
                text("DELETE FROM wallet_history_quality WHERE wallet_id = :w"), {"w": wid}
            )
            await conn.execute(
                text("DELETE FROM wallet_cluster_links WHERE wallet_a_id = :w OR wallet_b_id = :w"),
                {"w": wid},
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


async def _cleanup_token(admin_engine: Any, mint: str) -> None:
    async with admin_engine.connect() as conn:
        row = (
            await conn.execute(text("SELECT token_id FROM tokens WHERE mint = :m"), {"m": mint})
        ).fetchone()
        if row is not None:
            tid = row[0]
            await conn.execute(
                text("DELETE FROM token_market_snapshots WHERE token_id = :t"), {"t": tid}
            )
            await conn.execute(text("DELETE FROM tokens WHERE token_id = :t"), {"t": tid})
        await conn.commit()


# ---------------------------------------------------------------------
# Seeding helpers -- real rows via the real ORM models, matching
# test_shadow_phase4.py's own established seeding style.
# ---------------------------------------------------------------------


async def _seed_score_snapshot(
    session: Any, *, wallet_id: uuid.UUID, score: Decimal, at: datetime
) -> uuid.UUID:
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
    await session.flush()
    return score_id


async def _seed_tier_transition(
    session: Any,
    *,
    wallet_id: uuid.UUID,
    to_tier: str,
    at: datetime,
    from_tier: str | None = None,
    source_score_id: uuid.UUID | None = None,
) -> uuid.UUID:
    transition_id = uuid.uuid4()
    session.add(
        WalletTierTransition(
            transition_id=transition_id,
            wallet_id=wallet_id,
            source_score_id=source_score_id,
            from_tier=from_tier,
            to_tier=to_tier,
            reason="test",
            transitioned_at=at,
            created_at=at,
        )
    )
    await session.flush()
    return transition_id


async def _seed_tracked_wallet_with_buy_swap(
    session: Any,
    *,
    wallet_address: str,
    tier: str,
    score: Decimal,
    mint: str,
    at: datetime,
    seed_score_and_tier: bool = True,
    confirmed: bool = True,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Real wallets/chain_events/swaps rows -- a genuine SWAP_SIMPLE buy
    (SOL -> mint) from a tracked wallet. ``seed_score_and_tier=False``
    deliberately leaves the wallet with zero score/tier evidence (P4-R1
    test 2's "no pre-cutoff evidence exists at all" scenario).
    ``confirmed=False`` leaves ``confirmation_time`` genuinely unknown
    (P4-R3's late-confirmation scenario)."""
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
    if seed_score_and_tier:
        score_id = await _seed_score_snapshot(session, wallet_id=wallet_id, score=score, at=at)
        await _seed_tier_transition(
            session, wallet_id=wallet_id, to_tier=tier, at=at, source_score_id=score_id
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
            transaction_signature=f"p4ro-buy-{uuid.uuid4()}",
            event_type="TRANSACTION_OBSERVED",
            wallet_address=wallet_address,
            raw_payload={},
            payload_hash="h",
            parser_version="v1",
            created_at=at,
        )
    )
    await session.flush()
    if confirmed:
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
    return wallet_id, swap_id, event_id


async def _seed_additional_buy_swap(
    session: Any,
    *,
    wallet_address: str,
    mint: str,
    at: datetime,
    event_id: uuid.UUID | None = None,
    parser_version: str = "v1",
) -> tuple[uuid.UUID, uuid.UUID]:
    """One more real chain_events/swaps pair for an ALREADY-tracked
    wallet -- or, when ``event_id`` is given, a second ``swaps`` row (a
    reparse artifact) against that SAME already-existing chain_events
    row, never a new one (P4-R3's two-parser-artifacts scenario)."""
    if event_id is None:
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
                transaction_signature=f"p4ro-buy-{uuid.uuid4()}",
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
            parser_version=parser_version,
            build_hash="test-build",
            created_at=at,
        )
    )
    await session.flush()
    return swap_id, event_id


async def _seed_token(session: Any, *, mint: str, at: datetime) -> uuid.UUID:
    token_id = uuid.uuid4()
    session.add(
        Token(
            token_id=token_id,
            mint=mint,
            chain="solana",
            first_observed_at=at,
            mint_validated=True,
            current_lifecycle_stage=LIFECYCLE_AMM_POOL,
            created_at=at,
        )
    )
    await session.flush()
    return token_id


async def _seed_token_market_snapshot(
    session: Any, *, token_id: uuid.UUID, observed_at: datetime, price_usd: Decimal
) -> uuid.UUID:
    snapshot_id = uuid.uuid4()
    session.add(
        TokenMarketSnapshot(
            snapshot_id=snapshot_id,
            token_id=token_id,
            observed_at=observed_at,
            chain_time=None,
            lifecycle_stage=LIFECYCLE_AMM_POOL,
            venue=None,
            venue_program=None,
            pool_or_curve_address=None,
            price_usd=price_usd,
            supply_raw=None,
            liquidity_usd=Decimal("1000"),
            fdv_usd=None,
            market_cap_usd=None,
            market_state_confidence="HIGH",
            source="test-src",
            evidence_reference=None,
            algorithm_version="test-v1",
            build_hash="test-build",
            created_at=observed_at,
        )
    )
    await session.flush()
    return snapshot_id


async def _seed_history_quality(session: Any, *, wallet_id: uuid.UUID, at: datetime) -> uuid.UUID:
    history_id = uuid.uuid4()
    session.add(
        WalletHistoryQuality(
            history_id=history_id,
            wallet_id=wallet_id,
            history_start=at - timedelta(days=30),
            history_end=at,
            history_provider_set="helius",
            history_completeness="HIGH",
            history_completeness_reason="test",
            acquisition_manifest=None,
            excluded_evidence=[],
            algorithm_version="test-v1",
            created_at=at,
        )
    )
    await session.flush()
    return history_id


async def _seed_open_position(
    session: Any,
    *,
    wallet_id: uuid.UUID,
    token_id: uuid.UUID,
    history_id: uuid.UUID,
    entry_value_quote: Decimal,
    at: datetime,
) -> uuid.UUID:
    position_id = uuid.uuid4()
    session.add(
        WalletPosition(
            position_id=position_id,
            wallet_id=wallet_id,
            token_id=token_id,
            history_id=history_id,
            quote_asset_mint=SOL_MINT,
            round_trip_index=0,
            input_manifest_digest=None,
            first_entry_at=at,
            last_entry_at=at,
            final_exit_at=None,
            entry_quantity=Decimal("1"),
            entry_value_quote=entry_value_quote,
            average_cost_quote=entry_value_quote,
            partial_exit_count=0,
            realized_pnl_quote=None,
            unrealized_pnl_quote=None,
            holding_duration_seconds=None,
            mfe_quote=None,
            mae_quote=None,
            peak_value_quote=None,
            peak_profit_capture=None,
            confidence=CONFIDENCE_HIGH,
            status=STATUS_OPEN,
            algorithm_version="test-v1",
            git_commit=_TEST_GIT_COMMIT,
            created_at=at,
        )
    )
    await session.flush()
    return position_id


async def _seed_cluster_link(
    session: Any,
    *,
    wallet_a_id: uuid.UUID,
    wallet_b_id: uuid.UUID,
    at: datetime,
    probability: Decimal,
) -> uuid.UUID:
    a, b = sorted([wallet_a_id, wallet_b_id], key=str)
    link_id = uuid.uuid4()
    session.add(
        WalletClusterLink(
            link_id=link_id,
            wallet_a_id=a,
            wallet_b_id=b,
            evidence_type=EVIDENCE_SYNCHRONIZED_ACTIVITY,
            evidence_reference="test-evidence",
            probability=probability,
            algorithm_version="test-v1",
            as_of=at,
            created_at=at,
        )
    )
    await session.flush()
    return link_id


# ---------------------------------------------------------------------
# P4-R1: point-in-time snapshot cutoff correctness.
# ---------------------------------------------------------------------


async def test_snapshot_reflects_only_pre_cutoff_evidence_never_later_updates(admin_engine) -> None:
    """The audit's own literal reproduction: a rescore, a tier promotion,
    a new token price snapshot, a new position snapshot, and a
    cluster-link change ALL happen after first_seen_at (T) but before the
    scan runs (T+2h) -- every one of the 5 snapshot fields must reflect
    only the T state."""
    wallet_address = _unique_wallet()
    other_address = _unique_wallet()
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    try:
        T = _NOW
        later = T + timedelta(hours=1)
        scan_time = T + timedelta(hours=2)

        async with sessionmaker() as session, session.begin():
            wallet_id, swap_id, _event_id = await _seed_tracked_wallet_with_buy_swap(
                session,
                wallet_address=wallet_address,
                tier="A",
                score=Decimal("90.000"),
                mint=mint,
                at=T,
            )
            await _seed_token(session, mint=mint, at=T)
            other_wallet_id = uuid.uuid4()
            session.add(
                Wallet(
                    wallet_id=other_wallet_id,
                    wallet_address=other_address,
                    first_discovered_at=T,
                    current_tier="B",
                    created_at=T,
                )
            )

        # All post-cutoff evidence -- created strictly after T, before the
        # scan runs at T+2h.
        async with sessionmaker() as session, session.begin():
            new_score_id = await _seed_score_snapshot(
                session, wallet_id=wallet_id, score=Decimal("99.000"), at=later
            )
            await _seed_tier_transition(
                session, wallet_id=wallet_id, to_tier="S", at=later, source_score_id=new_score_id
            )
            token = (await session.execute(select(Token).where(Token.mint == mint))).scalar_one()
            await _seed_token_market_snapshot(
                session, token_id=token.token_id, observed_at=later, price_usd=Decimal("5.00")
            )
            history_id = await _seed_history_quality(session, wallet_id=wallet_id, at=later)
            await _seed_open_position(
                session,
                wallet_id=wallet_id,
                token_id=token.token_id,
                history_id=history_id,
                entry_value_quote=Decimal("42"),
                at=later,
            )
            await _seed_cluster_link(
                session,
                wallet_a_id=wallet_id,
                wallet_b_id=other_wallet_id,
                at=later,
                probability=Decimal("0.90"),
            )

        async with sessionmaker() as session, session.begin():
            created = await scan_for_new_prospective_events(
                session, tier_allowed=["A", "S"], now=scan_time
            )
        assert len(created) == 1
        event = created[0]
        assert event.swap_id == swap_id
        assert event.first_seen_at == T

        # Score/tier: still the ORIGINAL T values, never the later 99/S.
        assert event.wallet_score_snapshot == Decimal("90.000")
        assert event.wallet_tier_snapshot == "A"

        # Token market state: the token itself is known (seeded at T), but
        # no market snapshot existed by T -- the T+1h price must never
        # leak in.
        assert event.token_state_snapshot["available"] is True
        assert event.token_state_snapshot["market_snapshot_available"] is False

        # Position context: no wallet_history_quality row existed by T.
        assert event.position_size_context["available"] is False
        assert event.position_size_context["open_position_count"] == 0

        # Cluster state: no link existed by T.
        assert event.cluster_state_snapshot["link_count"] == 0
        assert event.cluster_state_snapshot["cluster_risk"] is None
    finally:
        await _cleanup_wallet(admin_engine, other_address)
        await _cleanup_wallet(admin_engine, wallet_address)
        await _cleanup_token(admin_engine, mint)
        await engine.dispose()


async def test_snapshot_with_no_pre_cutoff_score_or_tier_falls_back_honestly(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = _unique_mint()
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
                seed_score_and_tier=False,
            )

        async with sessionmaker() as session, session.begin():
            created = await scan_for_new_prospective_events(
                session, tier_allowed=["A", "S"], now=_NOW
            )
        assert len(created) == 1
        event = created[0]
        assert event.wallet_score_snapshot is None
        assert event.wallet_tier_snapshot == TIER_DISCOVERED
        assert event.score_snapshot_id is None
        assert event.tier_transition_id is None

        assert event.position_size_context["available"] is False
        assert isinstance(event.position_size_context["reason"], str)
        assert event.position_size_context["reason"] != ""

        # No tokens row for this mint either -- honest "unavailable", not
        # a crash or an invented market state.
        assert event.token_state_snapshot["available"] is False
        assert isinstance(event.token_state_snapshot["reason"], str)
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


async def test_evidence_dated_exactly_at_cutoff_is_included(admin_engine) -> None:
    """``<=``, not ``<``: a row whose own timestamp equals
    ``swap.first_seen_at`` exactly is real, already-known evidence."""
    wallet_address = _unique_wallet()
    other_address = _unique_wallet()
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    try:
        T = _NOW
        async with sessionmaker() as session, session.begin():
            wallet_id, _swap_id, _event_id = await _seed_tracked_wallet_with_buy_swap(
                session,
                wallet_address=wallet_address,
                tier="A",
                score=Decimal("90.000"),
                mint=mint,
                at=T,
            )
            token_id = await _seed_token(session, mint=mint, at=T)
            await _seed_token_market_snapshot(
                session, token_id=token_id, observed_at=T, price_usd=Decimal("2.50")
            )
            history_id = await _seed_history_quality(session, wallet_id=wallet_id, at=T)
            await _seed_open_position(
                session,
                wallet_id=wallet_id,
                token_id=token_id,
                history_id=history_id,
                entry_value_quote=Decimal("10"),
                at=T,
            )
            other_wallet_id = uuid.uuid4()
            session.add(
                Wallet(
                    wallet_id=other_wallet_id,
                    wallet_address=other_address,
                    first_discovered_at=T,
                    current_tier="B",
                    created_at=T,
                )
            )
            await session.flush()
            await _seed_cluster_link(
                session,
                wallet_a_id=wallet_id,
                wallet_b_id=other_wallet_id,
                at=T,
                probability=Decimal("0.20"),
            )

        async with sessionmaker() as session, session.begin():
            created = await scan_for_new_prospective_events(session, tier_allowed=["A", "S"], now=T)
        assert len(created) == 1
        event = created[0]
        # The wallet's own score/tier rows (seeded by the helper at T
        # itself) are the score/tier equality-at-cutoff case.
        assert event.wallet_score_snapshot == Decimal("90.000")
        assert event.wallet_tier_snapshot == "A"

        assert event.token_state_snapshot["available"] is True
        assert event.token_state_snapshot["market_snapshot_available"] is True
        assert Decimal(event.token_state_snapshot["price_usd"]) == Decimal("2.50")

        assert event.position_size_context["available"] is True
        assert event.position_size_context["open_position_count"] == 1
        assert Decimal(event.position_size_context["aggregate_entry_value_quote"]) == Decimal("10")

        assert event.cluster_state_snapshot["link_count"] == 1
    finally:
        await _cleanup_wallet(admin_engine, other_address)
        await _cleanup_wallet(admin_engine, wallet_address)
        await _cleanup_token(admin_engine, mint)
        await engine.dispose()


async def test_future_rows_already_in_db_before_scan_are_ignored(admin_engine) -> None:
    """Future-dated evidence already sitting in the DB by scan time must
    never be picked up -- the cutoff is ``swap.first_seen_at``, never
    "whatever exists in the DB right now"."""
    wallet_address = _unique_wallet()
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    try:
        T = _NOW
        future = T + timedelta(minutes=30)
        async with sessionmaker() as session, session.begin():
            wallet_id, swap_id, _event_id = await _seed_tracked_wallet_with_buy_swap(
                session,
                wallet_address=wallet_address,
                tier="A",
                score=Decimal("90.000"),
                mint=mint,
                at=T,
            )
            token_id = await _seed_token(session, mint=mint, at=T)
            # Future-dated rows, already persisted BEFORE the scan runs.
            future_score_id = await _seed_score_snapshot(
                session, wallet_id=wallet_id, score=Decimal("11.000"), at=future
            )
            await _seed_tier_transition(
                session,
                wallet_id=wallet_id,
                to_tier="QUARANTINE",
                at=future,
                source_score_id=future_score_id,
            )
            await _seed_token_market_snapshot(
                session, token_id=token_id, observed_at=future, price_usd=Decimal("999.00")
            )

        async with sessionmaker() as session, session.begin():
            created = await scan_for_new_prospective_events(
                session, tier_allowed=["A", "S", "QUARANTINE"], now=T + timedelta(minutes=5)
            )
        assert len(created) == 1
        event = created[0]
        assert event.swap_id == swap_id
        assert event.wallet_score_snapshot == Decimal("90.000")
        assert event.wallet_tier_snapshot == "A"
        assert event.token_state_snapshot["market_snapshot_available"] is False
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await _cleanup_token(admin_engine, mint)
        await engine.dispose()


async def test_position_context_uses_only_single_most_recent_history_id(admin_engine) -> None:
    """Two separate wallet_history_quality reconstruction runs, each with
    its own OPEN positions for the same two tokens -- summing must use
    ONLY the most-recent-as-of-cutoff run, never both."""
    wallet_address = _unique_wallet()
    mint_a = _unique_mint()
    mint_b = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    try:
        T = _NOW
        older_run = T - timedelta(hours=2)
        newer_run = T - timedelta(hours=1)
        async with sessionmaker() as session, session.begin():
            wallet_id, _swap_id, _event_id = await _seed_tracked_wallet_with_buy_swap(
                session,
                wallet_address=wallet_address,
                tier="A",
                score=Decimal("90.000"),
                mint=mint_a,
                at=T,
            )
            token_a = await _seed_token(session, mint=mint_a, at=T)
            token_b = await _seed_token(session, mint=mint_b, at=T)

            older_history_id = await _seed_history_quality(
                session, wallet_id=wallet_id, at=older_run
            )
            await _seed_open_position(
                session,
                wallet_id=wallet_id,
                token_id=token_a,
                history_id=older_history_id,
                entry_value_quote=Decimal("3"),
                at=older_run,
            )
            await _seed_open_position(
                session,
                wallet_id=wallet_id,
                token_id=token_b,
                history_id=older_history_id,
                entry_value_quote=Decimal("4"),
                at=older_run,
            )

            newer_history_id = await _seed_history_quality(
                session, wallet_id=wallet_id, at=newer_run
            )
            await _seed_open_position(
                session,
                wallet_id=wallet_id,
                token_id=token_a,
                history_id=newer_history_id,
                entry_value_quote=Decimal("10"),
                at=newer_run,
            )
            await _seed_open_position(
                session,
                wallet_id=wallet_id,
                token_id=token_b,
                history_id=newer_history_id,
                entry_value_quote=Decimal("20"),
                at=newer_run,
            )

        async with sessionmaker() as session, session.begin():
            created = await scan_for_new_prospective_events(session, tier_allowed=["A", "S"], now=T)
        assert len(created) == 1
        ctx = created[0].position_size_context
        assert ctx["available"] is True
        assert ctx["source_history_id"] == str(newer_history_id)
        assert ctx["open_position_count"] == 2
        assert ctx["distinct_open_token_count"] == 2
        # 10 + 20 from the newer run only -- never 3 + 4 + 10 + 20 = 37.
        assert Decimal(ctx["aggregate_entry_value_quote"]) == Decimal("30")
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await _cleanup_token(admin_engine, mint_a)
        await _cleanup_token(admin_engine, mint_b)
        await engine.dispose()


async def test_exact_replay_after_later_updates_snapshot_byte_for_byte_unchanged(
    admin_engine,
) -> None:
    """Closes the gap the pre-P4-R1 immutability test left open: this
    replay seeds real pre-cutoff token-market/position/cluster evidence
    (not just score/tier), then applies later updates to ALL FIVE
    dimensions before replaying the scan, and checks every field is
    exactly unchanged."""
    wallet_address = _unique_wallet()
    other_address = _unique_wallet()
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    try:
        T = _NOW
        later = T + timedelta(hours=1)
        async with sessionmaker() as session, session.begin():
            wallet_id, swap_id, _event_id = await _seed_tracked_wallet_with_buy_swap(
                session,
                wallet_address=wallet_address,
                tier="A",
                score=Decimal("90.000"),
                mint=mint,
                at=T,
            )
            token_id = await _seed_token(session, mint=mint, at=T)
            await _seed_token_market_snapshot(
                session, token_id=token_id, observed_at=T, price_usd=Decimal("1.00")
            )
            history_id = await _seed_history_quality(session, wallet_id=wallet_id, at=T)
            await _seed_open_position(
                session,
                wallet_id=wallet_id,
                token_id=token_id,
                history_id=history_id,
                entry_value_quote=Decimal("5"),
                at=T,
            )
            other_wallet_id = uuid.uuid4()
            session.add(
                Wallet(
                    wallet_id=other_wallet_id,
                    wallet_address=other_address,
                    first_discovered_at=T,
                    current_tier="B",
                    created_at=T,
                )
            )
            await session.flush()
            await _seed_cluster_link(
                session,
                wallet_a_id=wallet_id,
                wallet_b_id=other_wallet_id,
                at=T,
                probability=Decimal("0.30"),
            )

        async with sessionmaker() as session, session.begin():
            first_created = await scan_for_new_prospective_events(
                session, tier_allowed=["A", "S"], now=T
            )
        assert len(first_created) == 1
        original_event_id = first_created[0].prospective_event_id
        snapshot1 = {
            "wallet_score_snapshot": first_created[0].wallet_score_snapshot,
            "wallet_tier_snapshot": first_created[0].wallet_tier_snapshot,
            "token_state_snapshot": first_created[0].token_state_snapshot,
            "position_size_context": first_created[0].position_size_context,
            "cluster_state_snapshot": first_created[0].cluster_state_snapshot,
        }

        # Later updates across every dimension.
        async with sessionmaker() as session, session.begin():
            new_score_id = await _seed_score_snapshot(
                session, wallet_id=wallet_id, score=Decimal("50.000"), at=later
            )
            await _seed_tier_transition(
                session, wallet_id=wallet_id, to_tier="S", at=later, source_score_id=new_score_id
            )
            await _seed_token_market_snapshot(
                session, token_id=token_id, observed_at=later, price_usd=Decimal("77.00")
            )
            later_history_id = await _seed_history_quality(session, wallet_id=wallet_id, at=later)
            await _seed_open_position(
                session,
                wallet_id=wallet_id,
                token_id=token_id,
                history_id=later_history_id,
                entry_value_quote=Decimal("999"),
                at=later,
            )
            await _seed_cluster_link(
                session,
                wallet_a_id=wallet_id,
                wallet_b_id=other_wallet_id,
                at=later,
                probability=Decimal("0.95"),
            )

        async with sessionmaker() as session, session.begin():
            replay_created = await scan_for_new_prospective_events(
                session, tier_allowed=["A", "S"], now=later + timedelta(hours=1)
            )
        assert replay_created == []

        async with sessionmaker() as session:
            reloaded = (
                await session.execute(
                    select(ProspectiveEvent).where(
                        ProspectiveEvent.prospective_event_id == original_event_id
                    )
                )
            ).scalar_one()
            assert reloaded.wallet_score_snapshot == snapshot1["wallet_score_snapshot"]
            assert reloaded.wallet_tier_snapshot == snapshot1["wallet_tier_snapshot"]
            assert reloaded.token_state_snapshot == snapshot1["token_state_snapshot"]
            assert reloaded.position_size_context == snapshot1["position_size_context"]
            assert reloaded.cluster_state_snapshot == snapshot1["cluster_state_snapshot"]

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
    finally:
        await _cleanup_wallet(admin_engine, other_address)
        await _cleanup_wallet(admin_engine, wallet_address)
        await _cleanup_token(admin_engine, mint)
        await engine.dispose()


class _ScriptedClock(Clock):
    def __init__(self, times: list[datetime]) -> None:
        super().__init__()
        self._times = iter(times)

    def utc_now(self) -> datetime:
        return next(self._times)


@dataclasses.dataclass
class _QueuedExecutionProvider:
    queue: list[ExecutableQuote]

    async def get_quote(
        self, *, input_mint: str, output_mint: str, amount_raw: int, slippage_bps: int = 50
    ) -> ExecutableQuote:
        return self.queue.pop(0)

    async def build_unsigned_order(self, *, quote: Any, wallet_address: str) -> Any:
        raise NotImplementedError


def _quote(
    *, input_mint: str, output_mint: str, in_amount: int, out_amount: int
) -> ExecutableQuote:
    return ExecutableQuote(
        provider="jupiter-fake",
        input_mint=input_mint,
        output_mint=output_mint,
        in_amount_raw=in_amount,
        out_amount_raw=out_amount,
        raw={
            "priceImpactPct": "0.01",
            "inAmount": str(in_amount),
            "outAmount": str(out_amount),
            "routePlan": [{"swapInfo": {"label": "fake-amm"}, "percent": 100}],
        },
    )


# ---------------------------------------------------------------------
# P4-R2: entry-delay probe due-time anchoring.
# ---------------------------------------------------------------------


async def test_probe_due_at_anchored_to_first_seen_at_matches_worked_example(admin_engine) -> None:
    """first_seen T, consumer reaches this event at T+60s, nominal "1s"
    due time is T+1s (never T+61s); a request at T+62.7s records a
    61.7s scheduling delay -- the instruction's own worked example."""
    wallet_address = _unique_wallet()
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    try:
        T = _NOW
        consumer_arrival = T + timedelta(seconds=60)
        async with sessionmaker() as session, session.begin():
            await _seed_tracked_wallet_with_buy_swap(
                session,
                wallet_address=wallet_address,
                tier="A",
                score=Decimal("90.000"),
                mint=mint,
                at=T,
            )

        result = await run_prospective_monitoring_pass(
            sessionmaker, config=config, now=consumer_arrival
        )
        assert len(result.prospective_events) == 1
        assert result.prospective_events[0].first_seen_at == T
        assert len(result.shadow_intents) == 1
        intent = result.shadow_intents[0]
        # created_at honestly records the real (late) creation instant.
        assert intent.created_at == consumer_arrival

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
            by_label = {p.target_label: p for p in probes}
        one_s_probe = by_label[entry_probe_label(1)]
        assert one_s_probe.target_due_at == T + timedelta(seconds=1)
        assert one_s_probe.target_due_at != T + timedelta(seconds=61)
        # Probe row creation instant is also honestly T+60s, not backdated.
        assert one_s_probe.created_at == consumer_arrival

        actual_requested_at = T + timedelta(seconds=62.7)
        actual_responded_at = actual_requested_at + timedelta(milliseconds=100)
        clock = _ScriptedClock([actual_requested_at, actual_responded_at])

        provider = _QueuedExecutionProvider(
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
        executed = processed[0]
        assert executed.target_label == "1s"
        assert executed.requested_at == actual_requested_at
        # target_due_at (T+1s) to requested_at (T+62.7s) = 61.7s late.
        assert executed.scheduling_delay_seconds == Decimal("61.7")
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


async def test_late_confirmation_does_not_affect_probe_due_time_anchoring(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    try:
        T = _NOW
        async with sessionmaker() as session, session.begin():
            _wallet_id, _swap_id, event_id = await _seed_tracked_wallet_with_buy_swap(
                session,
                wallet_address=wallet_address,
                tier="A",
                score=Decimal("90.000"),
                mint=mint,
                at=T,
                confirmed=False,
            )

        result = await run_prospective_monitoring_pass(sessionmaker, config=config, now=T)
        assert len(result.prospective_events) == 1
        event = result.prospective_events[0]
        assert event.confirmation_time is None
        intent = result.shadow_intents[0]

        async with sessionmaker() as session:
            probes_before = (
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
            due_before = {p.target_label: p.target_due_at for p in probes_before}

        late_confirmed_at = T + timedelta(minutes=5)
        async with sessionmaker() as session, session.begin():
            session.add(
                CommitmentObservation(
                    observation_id=uuid.uuid4(),
                    event_id=event_id,
                    commitment_level=COMMITMENT_CONFIRMED,
                    transaction_succeeded=True,
                    observed_at=late_confirmed_at,
                    provider="helius",
                    provider_received_at=late_confirmed_at,
                    created_at=late_confirmed_at,
                )
            )

        async with sessionmaker() as session, session.begin():
            updated = await revisit_pending_confirmations(session)
        assert event.prospective_event_id in updated

        async with sessionmaker() as session:
            reloaded_event = await session.get(ProspectiveEvent, event.prospective_event_id)
            assert reloaded_event.confirmation_time == late_confirmed_at
            assert reloaded_event.first_seen_at == T

            probes_after = (
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
            due_after = {p.target_label: p.target_due_at for p in probes_after}
        assert due_after == due_before
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


async def test_monitoring_pass_replay_no_second_intent_no_rescheduled_probes(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    try:
        T = _NOW
        async with sessionmaker() as session, session.begin():
            await _seed_tracked_wallet_with_buy_swap(
                session,
                wallet_address=wallet_address,
                tier="A",
                score=Decimal("90.000"),
                mint=mint,
                at=T,
            )

        first = await run_prospective_monitoring_pass(sessionmaker, config=config, now=T)
        assert len(first.shadow_intents) == 1
        intent_id = first.shadow_intents[0].shadow_intent_id

        async with sessionmaker() as session:
            probes_first = (
                (
                    await session.execute(
                        select(ShadowQuoteProbe).where(
                            ShadowQuoteProbe.shadow_intent_id == intent_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            first_state = {(p.target_label, p.target_due_at, p.created_at) for p in probes_first}

        second = await run_prospective_monitoring_pass(
            sessionmaker, config=config, now=T + timedelta(minutes=30)
        )
        assert second.prospective_events == ()
        assert second.shadow_intents == ()

        async with sessionmaker() as session:
            intents = (
                (
                    await session.execute(
                        select(ShadowIntent).where(
                            ShadowIntent.wallet_id == first.prospective_events[0].wallet_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(intents) == 1

            probes_second = (
                (
                    await session.execute(
                        select(ShadowQuoteProbe).where(
                            ShadowQuoteProbe.shadow_intent_id == intent_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            second_state = {(p.target_label, p.target_due_at, p.created_at) for p in probes_second}
        assert second_state == first_state
        assert len(probes_second) == 6
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# P4-R3: bounded-scan starvation, confirmation exposure, dedup.
# ---------------------------------------------------------------------


async def test_scan_drains_all_eligible_swaps_without_starvation(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    try:
        T = _NOW
        async with sessionmaker() as session, session.begin():
            _wallet_id, first_swap_id, _event_id = await _seed_tracked_wallet_with_buy_swap(
                session,
                wallet_address=wallet_address,
                tier="A",
                score=Decimal("90.000"),
                mint=mint,
                at=T,
            )
            all_swap_ids = {first_swap_id}
            for i in range(1, 7):
                swap_id, _eid = await _seed_additional_buy_swap(
                    session, wallet_address=wallet_address, mint=mint, at=T + timedelta(seconds=i)
                )
                all_swap_ids.add(swap_id)
        assert len(all_swap_ids) == 7

        limit = 3
        collected: list[uuid.UUID] = []
        for _ in range(10):
            async with sessionmaker() as session, session.begin():
                batch = await scan_for_new_prospective_events(
                    session, tier_allowed=["A", "S"], now=T + timedelta(hours=1), limit=limit
                )
            if not batch:
                break
            collected.extend(e.swap_id for e in batch)
        else:
            pytest.fail("scan did not drain within 10 bounded passes -- possible starvation")

        assert len(collected) == len(all_swap_ids)
        assert set(collected) == all_swap_ids

        # New work arriving after full drain is never blocked either.
        async with sessionmaker() as session, session.begin():
            new_swap_id_1, _ = await _seed_additional_buy_swap(
                session, wallet_address=wallet_address, mint=mint, at=T + timedelta(hours=2)
            )
            new_swap_id_2, _ = await _seed_additional_buy_swap(
                session,
                wallet_address=wallet_address,
                mint=mint,
                at=T + timedelta(hours=2, seconds=1),
            )

        async with sessionmaker() as session, session.begin():
            post_drain_batch = await scan_for_new_prospective_events(
                session, tier_allowed=["A", "S"], now=T + timedelta(hours=3), limit=limit
            )
        assert {e.swap_id for e in post_drain_batch} == {new_swap_id_1, new_swap_id_2}
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


async def test_revisit_pending_confirmations_idempotent_and_frozen_fields_untouched(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    try:
        T = _NOW
        async with sessionmaker() as session, session.begin():
            wallet_id, _swap_id, event_id = await _seed_tracked_wallet_with_buy_swap(
                session,
                wallet_address=wallet_address,
                tier="A",
                score=Decimal("90.000"),
                mint=mint,
                at=T,
                confirmed=False,
            )
            token_id = await _seed_token(session, mint=mint, at=T)
            await _seed_token_market_snapshot(
                session, token_id=token_id, observed_at=T, price_usd=Decimal("3.00")
            )
            history_id = await _seed_history_quality(session, wallet_id=wallet_id, at=T)
            await _seed_open_position(
                session,
                wallet_id=wallet_id,
                token_id=token_id,
                history_id=history_id,
                entry_value_quote=Decimal("6"),
                at=T,
            )

        async with sessionmaker() as session, session.begin():
            created = await scan_for_new_prospective_events(session, tier_allowed=["A", "S"], now=T)
        assert len(created) == 1
        event = created[0]
        assert event.confirmation_time is None
        before = {
            "first_seen_at": event.first_seen_at,
            "wallet_score_snapshot": event.wallet_score_snapshot,
            "wallet_tier_snapshot": event.wallet_tier_snapshot,
            "token_state_snapshot": event.token_state_snapshot,
            "position_size_context": event.position_size_context,
            "cluster_state_snapshot": event.cluster_state_snapshot,
            "score_snapshot_id": event.score_snapshot_id,
            "tier_transition_id": event.tier_transition_id,
        }

        confirmed_at = T + timedelta(minutes=2)
        async with sessionmaker() as session, session.begin():
            session.add(
                CommitmentObservation(
                    observation_id=uuid.uuid4(),
                    event_id=event_id,
                    commitment_level=COMMITMENT_CONFIRMED,
                    transaction_succeeded=True,
                    observed_at=confirmed_at,
                    provider="helius",
                    provider_received_at=confirmed_at,
                    created_at=confirmed_at,
                )
            )

        async with sessionmaker() as session, session.begin():
            first_updated = await revisit_pending_confirmations(session)
        assert event.prospective_event_id in first_updated

        async with sessionmaker() as session:
            reloaded = await session.get(ProspectiveEvent, event.prospective_event_id)
            assert reloaded.confirmation_time == confirmed_at
            assert reloaded.first_seen_at == before["first_seen_at"]
            assert reloaded.wallet_score_snapshot == before["wallet_score_snapshot"]
            assert reloaded.wallet_tier_snapshot == before["wallet_tier_snapshot"]
            assert reloaded.token_state_snapshot == before["token_state_snapshot"]
            assert reloaded.position_size_context == before["position_size_context"]
            assert reloaded.cluster_state_snapshot == before["cluster_state_snapshot"]
            assert reloaded.score_snapshot_id == before["score_snapshot_id"]
            assert reloaded.tier_transition_id == before["tier_transition_id"]

        async with sessionmaker() as session, session.begin():
            second_updated = await revisit_pending_confirmations(session)
        assert event.prospective_event_id not in second_updated
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await _cleanup_token(admin_engine, mint)
        await engine.dispose()


async def test_two_parser_artifacts_same_event_id_produce_only_one_prospective_event(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    try:
        T = _NOW
        async with sessionmaker() as session, session.begin():
            _wallet_id, _first_swap_id, event_id = await _seed_tracked_wallet_with_buy_swap(
                session,
                wallet_address=wallet_address,
                tier="A",
                score=Decimal("90.000"),
                mint=mint,
                at=T,
            )
            # A second, independent Swap row for the exact same event_id
            # -- as if a reparse produced a second parser artifact of the
            # very same raw transaction.
            second_swap_id, _same_event_id = await _seed_additional_buy_swap(
                session,
                wallet_address=wallet_address,
                mint=mint,
                at=T,
                event_id=event_id,
                parser_version="v2",
            )
        assert second_swap_id != _first_swap_id

        async with sessionmaker() as session, session.begin():
            created = await scan_for_new_prospective_events(session, tier_allowed=["A", "S"], now=T)
        assert len(created) == 1

        async with sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(ProspectiveEvent).where(ProspectiveEvent.event_id == event_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await _cleanup_token(admin_engine, mint)
        await engine.dispose()

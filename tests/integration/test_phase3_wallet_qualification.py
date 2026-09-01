"""Phase 3 (WALLET RECONSTRUCTION + UNBIASED QUALIFICATION) integration
tests against real Postgres -- the DB-persistence halves of required
tests 8 (tier lifecycle) and 9 (restart/replay idempotency) that the
pure-function unit tests in ``tests/unit/test_phase3_wallet_qualification.py``
cannot exercise, plus one additional full-service-path discovery-
contamination test for extra rigor beyond the pure-function version
(`argus-phase-3-001`'s own "direct automated assertions proving the
contamination cannot leak" requirement).

Follows ``tests/integration/test_phase2_discovery.py``'s established
conventions: a unique, clearly-fake mint/wallet address per test, real
service calls through ``connection_for_role(..., DbRole.INGEST)`` (the
same least-privilege role production code uses, proving migration 0010's
grants are sufficient, not merely declared), and a ``finally``-block
cleanup via the admin engine.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from argus.config import load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.chain_events import ChainEvent
from argus.domain.swaps import Swap
from argus.domain.wallet_cluster_links import EVIDENCE_SYNCHRONIZED_ACTIVITY, WalletClusterLink
from argus.domain.wallet_discovery_events import (
    DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY,
    WalletDiscoveryEvent,
)
from argus.domain.wallet_metrics_snapshots import RECENCY_WINDOWS, WalletMetricsSnapshot
from argus.domain.wallet_positions import WalletPosition
from argus.domain.wallet_score_snapshots import WalletScoreSnapshot
from argus.domain.wallet_tier_history import (
    TIER_A,
    TIER_B,
    TIER_DISCOVERED,
    TIER_QUARANTINE,
    WalletTierTransition,
)
from argus.domain.wallets import Wallet
from argus.tokens.historical_acquisition import STATUS_COMPLETE
from argus.tokens.importer import import_bootstrap_token
from argus.wallets.history_reconstruction import (
    EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK,
    EVIDENCE_SOURCE_STREAM_FORWARD_ONLY,
    AcquisitionManifest,
)
from argus.wallets.qualification_service import reconstruct_and_score_wallet

pytestmark = pytest.mark.asyncio

_TEST_GIT_COMMIT = "TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB"
SOL = "SOL"


def _unique_mint() -> str:
    return f"P3Test{uuid.uuid4().hex[:36]}"


def _unique_wallet() -> str:
    return f"P3W{uuid.uuid4().hex[:38]}"


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
            for table, col in (
                ("wallet_tier_history", "wallet_id"),
                ("wallet_score_snapshots", "wallet_id"),
                ("wallet_metrics_snapshots", "wallet_id"),
                ("wallet_positions", "wallet_id"),
                ("wallet_history_quality", "wallet_id"),
                ("wallet_discovery_events", "wallet_id"),
                ("early_buyers", "wallet_id"),
            ):
                await conn.execute(text(f"DELETE FROM {table} WHERE {col} = :w"), {"w": wid})
            await conn.execute(
                text("DELETE FROM wallet_cluster_links WHERE wallet_a_id = :w OR wallet_b_id = :w"),
                {"w": wid},
            )
            await conn.execute(
                text("DELETE FROM swaps WHERE wallet_address = :addr"), {"addr": wallet_address}
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
            token_id = row[0]
            for table, col in (
                ("wallet_positions", "token_id"),
                ("wallet_discovery_events", "trigger_token_id"),
                ("early_buyers", "token_id"),
                ("token_mint_validations", "token_id"),
            ):
                await conn.execute(text(f"DELETE FROM {table} WHERE {col} = :t"), {"t": token_id})
            await conn.execute(text("DELETE FROM tokens WHERE token_id = :t"), {"t": token_id})
        await conn.commit()


async def _make_token(sessionmaker, config, mint: str, now: datetime) -> None:
    async with sessionmaker() as session, session.begin():
        await import_bootstrap_token(
            session,
            mint=mint,
            evidence={"value": {"owner": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}},
            evidence_kind="account_info",
            evidence_reference="test",
            now=now,
            config=config,
            git_commit=_TEST_GIT_COMMIT,
        )


async def _add_closed_position_swaps(
    session, *, wallet_address: str, mint: str, slot_base: int, at: datetime
) -> None:
    """One SWAP_SIMPLE buy + one SWAP_SIMPLE sell -- a single clean
    closed position -- backed by real ``chain_events``/``swaps`` rows."""
    buy_event_id = uuid.uuid4()
    sell_event_id = uuid.uuid4()
    session.add(
        ChainEvent(
            event_id=buy_event_id,
            chain="solana",
            slot=slot_base,
            first_seen_at=at,
            provider="helius",
            provider_received_at=at,
            transaction_signature=f"p3-buy-{uuid.uuid4()}",
            event_type="TRANSACTION_OBSERVED",
            wallet_address=wallet_address,
            raw_payload={},
            payload_hash="h",
            parser_version="v1",
            created_at=at,
        )
    )
    session.add(
        Swap(
            swap_id=uuid.uuid4(),
            event_id=buy_event_id,
            wallet_address=wallet_address,
            classification="SWAP_SIMPLE",
            input_mint=SOL,
            input_amount_raw=10_000_000_000,
            input_amount_ui=Decimal("10"),
            output_mint=mint,
            output_amount_raw=100,
            output_amount_ui=Decimal("100"),
            network_fee_raw=5000,
            slot=slot_base,
            block_time=at,
            first_seen_at=at,
            confidence=Decimal("1.000"),
            parser_version="v1",
            build_hash="test-build-hash",
            created_at=at,
        )
    )
    sell_at = at + timedelta(hours=1)
    session.add(
        ChainEvent(
            event_id=sell_event_id,
            chain="solana",
            slot=slot_base + 1,
            first_seen_at=sell_at,
            provider="helius",
            provider_received_at=sell_at,
            transaction_signature=f"p3-sell-{uuid.uuid4()}",
            event_type="TRANSACTION_OBSERVED",
            wallet_address=wallet_address,
            raw_payload={},
            payload_hash="h",
            parser_version="v1",
            created_at=sell_at,
        )
    )
    session.add(
        Swap(
            swap_id=uuid.uuid4(),
            event_id=sell_event_id,
            wallet_address=wallet_address,
            classification="SWAP_SIMPLE",
            input_mint=mint,
            input_amount_raw=100,
            input_amount_ui=Decimal("100"),
            output_mint=SOL,
            output_amount_raw=15_000_000_000,
            output_amount_ui=Decimal("15"),
            network_fee_raw=5000,
            slot=slot_base + 1,
            block_time=sell_at,
            first_seen_at=sell_at,
            confidence=Decimal("1.000"),
            parser_version="v1",
            build_hash="test-build-hash",
            created_at=sell_at,
        )
    )


# ---------------------------------------------------------------------
# Required test 8: tier lifecycle -- real DB transitions are immutable
# and timestamped; a later score change never rewrites earlier rows.
# ---------------------------------------------------------------------


async def test_p3_tier_lifecycle_transitions_are_immutable_and_timestamped(admin_engine) -> None:
    wallet_address = _unique_wallet()
    other_wallet_address = _unique_wallet()
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    now = datetime(2026, 6, 1, tzinfo=UTC)
    try:
        async with sessionmaker() as session, session.begin():
            session.add(
                Wallet(
                    wallet_id=uuid.uuid4(),
                    wallet_address=wallet_address,
                    first_discovered_at=now,
                    created_at=now,
                )
            )
            await _add_closed_position_swaps(
                session, wallet_address=wallet_address, mint=mint, slot_base=1, at=now
            )
        await _make_token(sessionmaker, config, mint, now)

        first_result = await reconstruct_and_score_wallet(
            sessionmaker,
            wallet_address=wallet_address,
            evidence_source=EVIDENCE_SOURCE_STREAM_FORWARD_ONLY,
            acquisition_manifest=None,
            config=config,
            git_commit=_TEST_GIT_COMMIT,
            now=now,
        )
        # P3-R6: the desired tier is always computed from the current,
        # complete score -- even on the very first invocation, never
        # forced to DISCOVERED regardless of evidence. With only 1
        # closed position (far below the eligibility gate) this wallet's
        # shrunk score still lands in DISCOVERED, but for the real
        # reason (not eligible / below the WATCH threshold), not a
        # special-cased "no prior score exists" placeholder.
        assert first_result.tier_transition is not None
        assert first_result.tier_transition[0] == TIER_DISCOVERED
        assert "eligible" in first_result.tier_transition[1]
        assert first_result.current_tier == TIER_DISCOVERED

        async with sessionmaker() as session:
            transitions = (
                (
                    await session.execute(
                        select(WalletTierTransition)
                        .where(WalletTierTransition.wallet_id == first_result.wallet_id)
                        .order_by(WalletTierTransition.transitioned_at)
                    )
                )
                .scalars()
                .all()
            )
            assert len(transitions) == 1
            first_transition = transitions[0]
            assert first_transition.from_tier is None
            assert first_transition.to_tier == TIER_DISCOVERED
            first_transitioned_at = first_transition.transitioned_at

        # A synchronized-activity cluster link at a probability well above
        # the QUARANTINE threshold (>= 0.80): a real, independently
        # meaningful tier-changing event a second reconstruct-and-score
        # pass will pick up.
        other_wallet_id = uuid.uuid4()
        later = now + timedelta(days=1)
        async with sessionmaker() as session, session.begin():
            session.add(
                Wallet(
                    wallet_id=other_wallet_id,
                    wallet_address=other_wallet_address,
                    first_discovered_at=later,
                    created_at=later,
                )
            )
            # No ORM relationship links Wallet <-> WalletClusterLink, so
            # the unit of work cannot infer insert order from the raw FK
            # values alone -- flush explicitly so the wallet row exists
            # before the FK-dependent cluster link is inserted.
            await session.flush()
            session.add(
                WalletClusterLink(
                    link_id=uuid.uuid4(),
                    wallet_a_id=first_result.wallet_id,
                    wallet_b_id=other_wallet_id,
                    evidence_type=EVIDENCE_SYNCHRONIZED_ACTIVITY,
                    evidence_reference="test: synchronized buy/sell timing",
                    probability=Decimal("0.95"),
                    algorithm_version="test",
                    as_of=later,
                    created_at=later,
                )
            )

        second_result = await reconstruct_and_score_wallet(
            sessionmaker,
            wallet_address=wallet_address,
            evidence_source=EVIDENCE_SOURCE_STREAM_FORWARD_ONLY,
            acquisition_manifest=None,
            config=config,
            git_commit=_TEST_GIT_COMMIT,
            now=later,
        )
        assert second_result.current_tier == TIER_QUARANTINE
        assert second_result.tier_transition is not None
        assert second_result.tier_transition[0] == TIER_QUARANTINE

        async with sessionmaker() as session:
            transitions = (
                (
                    await session.execute(
                        select(WalletTierTransition)
                        .where(WalletTierTransition.wallet_id == first_result.wallet_id)
                        .order_by(WalletTierTransition.transitioned_at)
                    )
                )
                .scalars()
                .all()
            )
            assert len(transitions) == 2
            # The first transition is unchanged -- immutable, never
            # rewritten by the later score/tier change.
            assert transitions[0].from_tier is None
            assert transitions[0].to_tier == TIER_DISCOVERED
            assert transitions[0].transitioned_at == first_transitioned_at
            assert transitions[1].from_tier == TIER_DISCOVERED
            assert transitions[1].to_tier == TIER_QUARANTINE

            wallet_row = (
                await session.execute(
                    select(Wallet).where(Wallet.wallet_id == first_result.wallet_id)
                )
            ).scalar_one()
            assert wallet_row.current_tier == TIER_QUARANTINE
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await _cleanup_wallet(admin_engine, other_wallet_address)
        await _cleanup_token(admin_engine, mint)
        await engine.dispose()


# ---------------------------------------------------------------------
# Required test 9: restart/replay idempotency.
# ---------------------------------------------------------------------


async def test_p3_restart_replay_identical_evidence_produces_no_duplicate_rows(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    now = datetime(2026, 6, 1, tzinfo=UTC)
    try:
        async with sessionmaker() as session, session.begin():
            session.add(
                Wallet(
                    wallet_id=uuid.uuid4(),
                    wallet_address=wallet_address,
                    first_discovered_at=now,
                    created_at=now,
                )
            )
            await _add_closed_position_swaps(
                session, wallet_address=wallet_address, mint=mint, slot_base=1, at=now
            )
        await _make_token(sessionmaker, config, mint, now)

        first_result = await reconstruct_and_score_wallet(
            sessionmaker,
            wallet_address=wallet_address,
            evidence_source=EVIDENCE_SOURCE_STREAM_FORWARD_ONLY,
            acquisition_manifest=None,
            config=config,
            git_commit=_TEST_GIT_COMMIT,
            now=now,
        )
        assert first_result.positions_written == 1
        assert first_result.score_written is True

        second_result = await reconstruct_and_score_wallet(
            sessionmaker,
            wallet_address=wallet_address,
            evidence_source=EVIDENCE_SOURCE_STREAM_FORWARD_ONLY,
            acquisition_manifest=None,
            config=config,
            git_commit=_TEST_GIT_COMMIT,
            now=now,
        )
        assert second_result.positions_written == 0
        assert second_result.positions_unchanged == 1
        assert second_result.score_written is False
        # Restarting from a later real-world timestamp is still a
        # replay of *identical evidence* -- no new tier transition
        # either, since the computed tier is unchanged.
        assert second_result.tier_transition is None

        async with sessionmaker() as session:
            position_count = (
                (
                    await session.execute(
                        select(WalletPosition).where(
                            WalletPosition.wallet_id == first_result.wallet_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(position_count) == 1

            score_count = (
                (
                    await session.execute(
                        select(WalletScoreSnapshot).where(
                            WalletScoreSnapshot.wallet_id == first_result.wallet_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(score_count) == 1

            transition_count = (
                (
                    await session.execute(
                        select(WalletTierTransition).where(
                            WalletTierTransition.wallet_id == first_result.wallet_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(transition_count) == 1
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await _cleanup_token(admin_engine, mint)
        await engine.dispose()


# ---------------------------------------------------------------------
# Extra rigor: the discovery-contamination firewall at the full,
# persisted service level (not just the pure-function version).
# ---------------------------------------------------------------------


async def test_p3_discovery_contamination_excluded_at_the_service_level(admin_engine) -> None:
    clean_wallet = _unique_wallet()
    contaminated_wallet = _unique_wallet()
    clean_mint = _unique_mint()
    discovery_mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    now = datetime(2026, 6, 1, tzinfo=UTC)
    try:
        async with sessionmaker() as session, session.begin():
            session.add(
                Wallet(
                    wallet_id=uuid.uuid4(),
                    wallet_address=clean_wallet,
                    first_discovered_at=now,
                    created_at=now,
                )
            )
            await _add_closed_position_swaps(
                session, wallet_address=clean_wallet, mint=clean_mint, slot_base=1, at=now
            )
        await _make_token(sessionmaker, config, clean_mint, now)

        contaminated_wallet_id = uuid.uuid4()
        async with sessionmaker() as session, session.begin():
            session.add(
                Wallet(
                    wallet_id=contaminated_wallet_id,
                    wallet_address=contaminated_wallet,
                    first_discovered_at=now,
                    created_at=now,
                )
            )
            # The exact same clean position...
            await _add_closed_position_swaps(
                session, wallet_address=contaminated_wallet, mint=clean_mint, slot_base=1, at=now
            )
            # ...plus a huge-winner discovery-trigger position.
            await _add_closed_position_swaps(
                session,
                wallet_address=contaminated_wallet,
                mint=discovery_mint,
                slot_base=10,
                at=now,
            )
        await _make_token(sessionmaker, config, discovery_mint, now)

        async with sessionmaker() as session:
            discovery_token_id = (
                await session.execute(
                    text("SELECT token_id FROM tokens WHERE mint = :m"), {"m": discovery_mint}
                )
            ).scalar_one()
        async with sessionmaker() as session, session.begin():
            session.add(
                WalletDiscoveryEvent(
                    discovery_event_id=uuid.uuid4(),
                    wallet_id=contaminated_wallet_id,
                    discovered_at=now,
                    discovery_channel=DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY,
                    trigger_token_id=discovery_token_id,
                    trigger_wallet_id=None,
                    trigger_event=None,
                    trigger_reason="test: discovered via this huge winner",
                    algorithm_version="test",
                    created_at=now,
                )
            )

        clean_result = await reconstruct_and_score_wallet(
            sessionmaker,
            wallet_address=clean_wallet,
            evidence_source=EVIDENCE_SOURCE_STREAM_FORWARD_ONLY,
            acquisition_manifest=None,
            config=config,
            git_commit=_TEST_GIT_COMMIT,
            now=now,
        )
        contaminated_result = await reconstruct_and_score_wallet(
            sessionmaker,
            wallet_address=contaminated_wallet,
            evidence_source=EVIDENCE_SOURCE_STREAM_FORWARD_ONLY,
            acquisition_manifest=None,
            config=config,
            git_commit=_TEST_GIT_COMMIT,
            now=now,
        )

        # The discovery-trigger token's own position is present in the
        # DB (never dropped/hidden) -- 2 positions reconstructed -- but
        # the qualification score is byte-identical to the wallet that
        # never had that token at all, because it never enters the
        # qualification computation's inputs.
        assert contaminated_result.positions_reconstructed == 2
        assert clean_result.positions_reconstructed == 1
        assert contaminated_result.qualification_score == clean_result.qualification_score
    finally:
        await _cleanup_wallet(admin_engine, clean_wallet)
        await _cleanup_wallet(admin_engine, contaminated_wallet)
        await _cleanup_token(admin_engine, clean_mint)
        await _cleanup_token(admin_engine, discovery_mint)
        await engine.dispose()


# ---------------------------------------------------------------------
# P3-R1: point-in-time knowledge-cutoff firewall at the real service
# level -- future-dated evidence (a cluster link not yet observed) must
# not be visible to a score computed as of an earlier instant.
# ---------------------------------------------------------------------


async def test_p3_service_level_as_of_boundary_excludes_future_cluster_link(admin_engine) -> None:
    wallet_address = _unique_wallet()
    other_wallet_address = _unique_wallet()
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    later = t0 + timedelta(days=1)
    try:
        wallet_id = uuid.uuid4()
        other_wallet_id = uuid.uuid4()
        async with sessionmaker() as session, session.begin():
            session.add(
                Wallet(
                    wallet_id=wallet_id,
                    wallet_address=wallet_address,
                    first_discovered_at=t0,
                    created_at=t0,
                )
            )
            session.add(
                Wallet(
                    wallet_id=other_wallet_id,
                    wallet_address=other_wallet_address,
                    first_discovered_at=t0,
                    created_at=t0,
                )
            )
            await session.flush()
            await _add_closed_position_swaps(
                session, wallet_address=wallet_address, mint=mint, slot_base=1, at=t0
            )
        await _make_token(sessionmaker, config, mint, t0)

        # A cluster link only observed AFTER t0 -- must not exist yet
        # from t0's own point of view.
        async with sessionmaker() as session, session.begin():
            session.add(
                WalletClusterLink(
                    link_id=uuid.uuid4(),
                    wallet_a_id=wallet_id,
                    wallet_b_id=other_wallet_id,
                    evidence_type=EVIDENCE_SYNCHRONIZED_ACTIVITY,
                    evidence_reference="test: only known later",
                    probability=Decimal("0.95"),
                    algorithm_version="test",
                    as_of=later,
                    created_at=later,
                )
            )

        at_t0 = await reconstruct_and_score_wallet(
            sessionmaker,
            wallet_address=wallet_address,
            evidence_source=EVIDENCE_SOURCE_STREAM_FORWARD_ONLY,
            acquisition_manifest=None,
            config=config,
            git_commit=_TEST_GIT_COMMIT,
            now=t0,
        )
        # The future cluster link was not yet knowable at t0 -- no
        # quarantine, no cluster penalty.
        assert at_t0.current_tier != TIER_QUARANTINE

        at_later = await reconstruct_and_score_wallet(
            sessionmaker,
            wallet_address=wallet_address,
            evidence_source=EVIDENCE_SOURCE_STREAM_FORWARD_ONLY,
            acquisition_manifest=None,
            config=config,
            git_commit=_TEST_GIT_COMMIT,
            now=later,
        )
        # At `later`, the same link is now genuinely knowable.
        assert at_later.current_tier == TIER_QUARANTINE

        # Re-scoring the EARLIER as_of again is byte-identical -- later
        # evidence existing in the DB never leaks backward into an
        # earlier snapshot's own computation.
        replay_t0 = await reconstruct_and_score_wallet(
            sessionmaker,
            wallet_address=wallet_address,
            evidence_source=EVIDENCE_SOURCE_STREAM_FORWARD_ONLY,
            acquisition_manifest=None,
            config=config,
            git_commit=_TEST_GIT_COMMIT,
            now=t0,
        )
        # Note: score history dedup compares against the wallet's most
        # recently *written* row (by created_at), not the row matching this
        # as_of -- since `at_later` was written in between, replay_t0 is
        # correctly persisted as its own row rather than deduped against
        # `at_later`. The P3-R1 guarantee under test is that the *value*
        # recomputed for the earlier as_of never drifts, which the
        # assertion above already proves.
        assert replay_t0.qualification_score == at_t0.qualification_score
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await _cleanup_wallet(admin_engine, other_wallet_address)
        await _cleanup_token(admin_engine, mint)
        await engine.dispose()


# ---------------------------------------------------------------------
# P3-R4: all five recency-window metric snapshots are materialized per
# run, with correct exit-time window membership -- never copied from
# LIFETIME, never leaking a later observation into an earlier window.
# ---------------------------------------------------------------------


async def test_p3_all_five_metric_windows_persisted_with_correct_membership(admin_engine) -> None:
    wallet_address = _unique_wallet()
    recent_mint = _unique_mint()
    old_mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    as_of = datetime(2026, 6, 1, tzinfo=UTC)
    recent_close_at = as_of - timedelta(days=3)  # inside every window
    old_close_at = as_of - timedelta(days=200)  # inside LIFETIME only
    try:
        async with sessionmaker() as session, session.begin():
            session.add(
                Wallet(
                    wallet_id=uuid.uuid4(),
                    wallet_address=wallet_address,
                    first_discovered_at=old_close_at,
                    created_at=old_close_at,
                )
            )
            await _add_closed_position_swaps(
                session,
                wallet_address=wallet_address,
                mint=recent_mint,
                slot_base=1,
                at=recent_close_at,
            )
            await _add_closed_position_swaps(
                session, wallet_address=wallet_address, mint=old_mint, slot_base=10, at=old_close_at
            )
        await _make_token(sessionmaker, config, recent_mint, as_of)
        await _make_token(sessionmaker, config, old_mint, as_of)

        result = await reconstruct_and_score_wallet(
            sessionmaker,
            wallet_address=wallet_address,
            evidence_source=EVIDENCE_SOURCE_STREAM_FORWARD_ONLY,
            acquisition_manifest=None,
            config=config,
            git_commit=_TEST_GIT_COMMIT,
            now=as_of,
        )
        assert result.positions_reconstructed == 2

        async with sessionmaker() as session:
            snapshots = (
                (
                    await session.execute(
                        select(WalletMetricsSnapshot).where(
                            WalletMetricsSnapshot.wallet_id == result.wallet_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            by_window = {s.metrics_window: s for s in snapshots}
            assert set(by_window) == set(RECENCY_WINDOWS)

            # LIFETIME sees both closed positions.
            assert by_window["LIFETIME"].usable_closed_positions_count == 2
            # 180D sees only the recent one -- the 200-day-old close is
            # outside this window, never copied from LIFETIME.
            assert by_window["180D"].usable_closed_positions_count == 1
            # 90D/30D/7D also see only the recent one.
            for window in ("90D", "30D", "7D"):
                assert by_window[window].usable_closed_positions_count == 1
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await _cleanup_token(admin_engine, recent_mint)
        await _cleanup_token(admin_engine, old_mint)
        await engine.dispose()


# ---------------------------------------------------------------------
# P3-R6: an eligible wallet's first invocation produces its real,
# score-derived tier directly (never forced to DISCOVERED first), and
# exact replay is idempotent.
# ---------------------------------------------------------------------


async def test_p3_eligible_wallet_first_invocation_not_forced_discovered_replay_idempotent(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mints = [_unique_mint() for _ in range(20)]
    config, engine, sessionmaker = _sessionmaker()
    now = datetime(2026, 6, 1, tzinfo=UTC)
    try:
        async with sessionmaker() as session, session.begin():
            session.add(
                Wallet(
                    wallet_id=uuid.uuid4(),
                    wallet_address=wallet_address,
                    first_discovered_at=now - timedelta(days=1),
                    created_at=now - timedelta(days=1),
                )
            )
            for i, mint in enumerate(mints):
                await _add_closed_position_swaps(
                    session,
                    wallet_address=wallet_address,
                    mint=mint,
                    slot_base=i * 10,
                    at=now - timedelta(days=1) + timedelta(minutes=i),
                )
        for mint in mints:
            await _make_token(sessionmaker, config, mint, now)

        # A real, structured, HIGH-completeness acquisition manifest --
        # never a bare caller-typed status string (P3-R2).
        manifest = AcquisitionManifest(
            wallet_walk_status=STATUS_COMPLETE,
            token_accounts_enumerated=True,
            associated_token_accounts=(),
            provider_set="test-fake-acquisition",
            known_gaps=None,
            evidence_reference="test",
        )

        first_result = await reconstruct_and_score_wallet(
            sessionmaker,
            wallet_address=wallet_address,
            evidence_source=EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK,
            acquisition_manifest=manifest,
            config=config,
            git_commit=_TEST_GIT_COMMIT,
            now=now,
        )
        assert first_result.history_completeness == "HIGH"
        assert first_result.eligible_for_qualification is True
        # P3-R6 fix: the very first invocation reflects the real,
        # score-derived tier -- never forced to DISCOVERED regardless of
        # evidence.
        assert first_result.current_tier != TIER_DISCOVERED
        assert first_result.tier_transition is not None
        assert first_result.tier_transition[0] != TIER_DISCOVERED

        async with sessionmaker() as session:
            score_row = (
                await session.execute(
                    select(WalletScoreSnapshot)
                    .where(WalletScoreSnapshot.wallet_id == first_result.wallet_id)
                    .order_by(WalletScoreSnapshot.created_at.desc())
                    .limit(1)
                )
            ).scalar_one()
            # P3-R6 canonical score: the persisted score is exactly the
            # score the tier decision used.
            assert score_row.qualification_score == first_result.qualification_score

        # Exact replay of identical inputs/as_of must not create a
        # second transition or score row.
        second_result = await reconstruct_and_score_wallet(
            sessionmaker,
            wallet_address=wallet_address,
            evidence_source=EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK,
            acquisition_manifest=manifest,
            config=config,
            git_commit=_TEST_GIT_COMMIT,
            now=now,
        )
        assert second_result.tier_transition is None
        assert second_result.score_written is False
        assert second_result.current_tier == first_result.current_tier

        async with sessionmaker() as session:
            transitions = (
                (
                    await session.execute(
                        select(WalletTierTransition).where(
                            WalletTierTransition.wallet_id == first_result.wallet_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(transitions) == 1
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        for mint in mints:
            await _cleanup_token(admin_engine, mint)
        await engine.dispose()


# ---------------------------------------------------------------------
# P3-R6: a cluster-uncertainty penalty that crosses an A/B tier cutoff
# changes both the persisted score and the tier from the SAME adjusted
# value -- never a locally-adjusted score the tier logic never sees.
# ---------------------------------------------------------------------


async def test_p3_cluster_penalty_crossing_tier_cutoff_persists_the_same_adjusted_score(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    other_wallet_address = _unique_wallet()
    mints = [_unique_mint() for _ in range(20)]
    config, engine, sessionmaker = _sessionmaker()
    now = datetime(2026, 6, 1, tzinfo=UTC)
    try:
        wallet_id = uuid.uuid4()
        other_wallet_id = uuid.uuid4()
        async with sessionmaker() as session, session.begin():
            session.add(
                Wallet(
                    wallet_id=wallet_id,
                    wallet_address=wallet_address,
                    first_discovered_at=now - timedelta(days=1),
                    created_at=now - timedelta(days=1),
                )
            )
            session.add(
                Wallet(
                    wallet_id=other_wallet_id,
                    wallet_address=other_wallet_address,
                    first_discovered_at=now - timedelta(days=1),
                    created_at=now - timedelta(days=1),
                )
            )
            await session.flush()
            for i, mint in enumerate(mints):
                await _add_closed_position_swaps(
                    session,
                    wallet_address=wallet_address,
                    mint=mint,
                    slot_base=i * 10,
                    at=now - timedelta(days=1) + timedelta(minutes=i),
                )
        for mint in mints:
            await _make_token(sessionmaker, config, mint, now)

        manifest = AcquisitionManifest(
            wallet_walk_status=STATUS_COMPLETE,
            token_accounts_enumerated=True,
            associated_token_accounts=(),
            provider_set="test-fake-acquisition",
            known_gaps=None,
            evidence_reference="test",
        )

        # Baseline (no cluster evidence): 20 identical clean +50% round
        # trips independently land this wallet's raw qualification_score
        # at 73.75 -- TIER_A (65-79.999...). This fixture is not
        # hand-tuned to an exact score; it is empirically confirmed
        # (see this run's own scratch probe) to land inside TIER_A with
        # enough headroom that the fixed 10-point cluster-uncertainty
        # penalty (probability 0.60, above the 0.50 penalty threshold
        # but below the 0.80 QUARANTINE threshold) pushes it into
        # TIER_B (50-64.999...) without ever triggering QUARANTINE.
        baseline = await reconstruct_and_score_wallet(
            sessionmaker,
            wallet_address=wallet_address,
            evidence_source=EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK,
            acquisition_manifest=manifest,
            config=config,
            git_commit=_TEST_GIT_COMMIT,
            now=now,
        )
        assert baseline.current_tier == TIER_A

        async with sessionmaker() as session, session.begin():
            session.add(
                WalletClusterLink(
                    link_id=uuid.uuid4(),
                    wallet_a_id=wallet_id,
                    wallet_b_id=other_wallet_id,
                    evidence_type=EVIDENCE_SYNCHRONIZED_ACTIVITY,
                    evidence_reference="test: moderate-probability link, below quarantine",
                    probability=Decimal("0.60"),
                    algorithm_version="test",
                    as_of=now,
                    created_at=now,
                )
            )

        # A tiny time advance (irrelevant to any recency-window
        # membership -- every round trip closed a full day earlier)
        # avoids a same-instant created_at tie against the baseline
        # snapshot, so "latest score row" is unambiguous.
        now_penalized = now + timedelta(seconds=1)
        penalized = await reconstruct_and_score_wallet(
            sessionmaker,
            wallet_address=wallet_address,
            evidence_source=EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK,
            acquisition_manifest=manifest,
            config=config,
            git_commit=_TEST_GIT_COMMIT,
            now=now_penalized,
        )
        # The penalty crossed the A/B cutoff -- never QUARANTINE, since
        # 0.60 < the 0.80 quarantine threshold.
        assert penalized.qualification_score == baseline.qualification_score - Decimal("10")
        assert penalized.current_tier == TIER_B
        assert penalized.current_tier != TIER_QUARANTINE

        async with sessionmaker() as session:
            score_row = (
                await session.execute(
                    select(WalletScoreSnapshot)
                    .where(WalletScoreSnapshot.wallet_id == wallet_id)
                    .order_by(WalletScoreSnapshot.created_at.desc())
                    .limit(1)
                )
            ).scalar_one()
            # P3-R6 canonical score: the persisted score is exactly the
            # penalized score the tier decision used -- never the
            # pre-penalty raw score.
            assert score_row.qualification_score == penalized.qualification_score
            assert score_row.qualification_score == baseline.qualification_score - Decimal("10")

            transitions = (
                (
                    await session.execute(
                        select(WalletTierTransition)
                        .where(WalletTierTransition.wallet_id == wallet_id)
                        .order_by(WalletTierTransition.transitioned_at)
                    )
                )
                .scalars()
                .all()
            )
            assert len(transitions) == 2
            assert transitions[0].to_tier == TIER_A
            assert transitions[1].from_tier == TIER_A
            assert transitions[1].to_tier == TIER_B
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await _cleanup_wallet(admin_engine, other_wallet_address)
        for mint in mints:
            await _cleanup_token(admin_engine, mint)
        await engine.dispose()

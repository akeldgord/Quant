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
from argus.domain.wallet_positions import WalletPosition
from argus.domain.wallet_score_snapshots import WalletScoreSnapshot
from argus.domain.wallet_tier_history import TIER_DISCOVERED, TIER_QUARANTINE, WalletTierTransition
from argus.domain.wallets import Wallet
from argus.tokens.importer import import_bootstrap_token
from argus.wallets.history_reconstruction import EVIDENCE_SOURCE_STREAM_FORWARD_ONLY
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
            acquisition_status=None,
            acquisition_known_gaps=None,
            config=config,
            git_commit=_TEST_GIT_COMMIT,
            now=now,
        )
        assert first_result.tier_transition == (
            TIER_DISCOVERED,
            "first tier assignment: no prior score exists",
        )
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
            acquisition_status=None,
            acquisition_known_gaps=None,
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
            acquisition_status=None,
            acquisition_known_gaps=None,
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
            acquisition_status=None,
            acquisition_known_gaps=None,
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
            acquisition_status=None,
            acquisition_known_gaps=None,
            config=config,
            git_commit=_TEST_GIT_COMMIT,
            now=now,
        )
        contaminated_result = await reconstruct_and_score_wallet(
            sessionmaker,
            wallet_address=contaminated_wallet,
            evidence_source=EVIDENCE_SOURCE_STREAM_FORWARD_ONLY,
            acquisition_status=None,
            acquisition_known_gaps=None,
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

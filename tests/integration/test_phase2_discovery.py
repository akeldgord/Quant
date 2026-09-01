"""Phase 2 (TOKEN + WALLET DISCOVERY) integration tests against real
Postgres -- the DB-persistence halves of P2-T1 through P2-T10 (the pure-
function halves live in ``tests/unit/test_phase2_discovery.py``).

Every test uses a unique, clearly-fake mint/wallet address per test (never
colliding with real committed evidence or another test) and cleans up its
own rows via the ``admin_engine`` fixture in a ``finally`` block, matching
``tests/integration/test_reconciliation_sql.py``'s established pattern.
The actual service calls under test go through ``connection_for_role(...,
DbRole.INGEST)`` -- the real least-privilege role production code uses --
not the admin engine, so these tests also prove the Phase 2 role grants
(migration 0008) are sufficient for real application code, not merely
declared.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from argus.config import load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.archaeology_runs import (
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_PARTIAL,
)
from argus.domain.archaeology_triggers import (
    TRIGGER_TYPE_HISTORICAL_WINNER,
    TRIGGER_TYPE_PROSPECTIVE_WINNER,
)
from argus.domain.early_buyers import EarlyBuyer
from argus.domain.tokens import Token
from argus.domain.wallet_discovery_events import (
    DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY,
    EXCLUSION_REASON_DISCOVERY_CONTAMINATION,
    WalletDiscoveryEvent,
)
from argus.domain.wallets import Wallet
from argus.tokens.importer import import_bootstrap_token
from argus.tokens.market_snapshots import MarketSnapshotDraft, record_snapshot
from argus.tokens.negative_controls import NegativeControlDraft, record_negative_control
from argus.wallets.archaeology import (
    get_or_create_historical_trigger,
    run_archaeology,
)
from argus.wallets.early_buyer_extraction import RawTransactionEvidence
from argus.wallets.watcher_service import evaluate_token

REPO_ROOT = Path(__file__).resolve().parents[2]
PUMPFUN_MINT = "5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump"
PUMPFUN_CREATOR = "6xo262KbDXepWbF3vPTrFXysr5vJwk3mozBXmXk3hmMx"
PUMPFUN_EVIDENCE_PATH = "orchestration/phase_1_5/evidence/raw/token_00_pumpfun_create.json"


def _unique_mint() -> str:
    return f"P2Test{uuid.uuid4().hex[:36]}"


def _unique_wallet() -> str:
    return f"P2W{uuid.uuid4().hex[:38]}"


async def _cleanup_token(admin_engine: Any, mint: str) -> None:
    async with admin_engine.connect() as conn:
        row = (
            await conn.execute(text("SELECT token_id FROM tokens WHERE mint = :m"), {"m": mint})
        ).fetchone()
        if row is not None:
            token_id = row[0]
            for table, col in (
                ("early_buyers", "token_id"),
                ("wallet_discovery_events", "trigger_token_id"),
                ("archaeology_runs", "token_id"),
                ("archaeology_triggers", "token_id"),
                ("token_winner_milestones", "token_id"),
                ("token_market_snapshots", "token_id"),
                ("token_mint_validations", "token_id"),
                ("token_negative_controls", "winner_token_id"),
                ("token_negative_controls", "control_token_id"),
            ):
                await conn.execute(text(f"DELETE FROM {table} WHERE {col} = :t"), {"t": token_id})
            await conn.execute(text("DELETE FROM tokens WHERE token_id = :t"), {"t": token_id})
        await conn.commit()


async def _cleanup_wallets(admin_engine: Any, wallet_addresses: list[str]) -> None:
    async with admin_engine.connect() as conn:
        for addr in wallet_addresses:
            row = (
                await conn.execute(
                    text("SELECT wallet_id FROM wallets WHERE wallet_address = :w"), {"w": addr}
                )
            ).fetchone()
            if row is not None:
                wid = row[0]
                await conn.execute(
                    text("DELETE FROM early_buyers WHERE wallet_id = :w"), {"w": wid}
                )
                await conn.execute(
                    text(
                        "DELETE FROM wallet_discovery_events WHERE wallet_id = :w OR "
                        "trigger_wallet_id = :w"
                    ),
                    {"w": wid},
                )
                await conn.execute(text("DELETE FROM wallets WHERE wallet_id = :w"), {"w": wid})
        await conn.commit()


def _sessionmaker():
    config = load_config()
    info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(info.as_asyncpg_url())
    return config, engine, async_sessionmaker(engine, expire_on_commit=False)


def _pumpfun_transaction_evidence() -> RawTransactionEvidence:
    raw = json.loads((REPO_ROOT / PUMPFUN_EVIDENCE_PATH).read_text())
    if isinstance(raw, list):
        raw = raw[0]
    sig = raw["transaction"]["signatures"][0]
    return RawTransactionEvidence(
        raw=raw,
        signature=sig,
        slot=raw["slot"],
        block_time=None,
        evidence_reference=PUMPFUN_EVIDENCE_PATH,
    )


# ---------------------------------------------------------------------
# P2-T1 (DB half) -- only VALID evidence ever sets mint_validated=True
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p2t1_db_only_valid_evidence_persists_mint_validated(admin_engine) -> None:
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    now = datetime.now(UTC)
    try:
        async with sessionmaker() as session, session.begin():
            unavailable_result = await import_bootstrap_token(
                session,
                mint=mint,
                evidence=None,
                evidence_kind="account_info",
                evidence_reference="test",
                now=now,
                config=config,
                git_commit="TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB",
            )
        assert unavailable_result.mint_validated is False

        async with sessionmaker() as session, session.begin():
            invalid_result = await import_bootstrap_token(
                session,
                mint=mint,
                evidence={"value": None},
                evidence_kind="account_info",
                evidence_reference="test",
                now=now,
                config=config,
                git_commit="TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB",
            )
        assert invalid_result.mint_validated is False

        # Both attempts are preserved, never overwritten (append-only).
        async with sessionmaker() as session:
            token = (await session.execute(select(Token).where(Token.mint == mint))).scalar_one()
            from argus.domain.token_mint_validations import TokenMintValidation

            attempts = (
                (
                    await session.execute(
                        select(TokenMintValidation).where(
                            TokenMintValidation.token_id == token.token_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(attempts) == 2
            assert token.mint_validated is False
    finally:
        await _cleanup_token(admin_engine, mint)
        await engine.dispose()


# ---------------------------------------------------------------------
# P2-T2 -- lifecycle/market snapshots preserve point-in-time truth
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p2t2_multiple_snapshots_preserve_point_in_time_truth(admin_engine) -> None:
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    now = datetime.now(UTC)
    try:
        async with sessionmaker() as session, session.begin():
            token = Token(
                token_id=uuid.uuid4(),
                mint=mint,
                chain="solana",
                first_observed_at=now,
                mint_validated=False,
                current_lifecycle_stage=None,
                created_at=now,
            )
            session.add(token)
            await session.flush()
            token_id = token.token_id

            draft1 = MarketSnapshotDraft(
                token_id=token_id,
                observed_at=datetime(2026, 1, 1, tzinfo=UTC),
                lifecycle_stage="BONDING_CURVE",
                source="test_source",
                chain_time=datetime(2026, 1, 1, 0, 0, 5, tzinfo=UTC),
                price_usd=Decimal("0.001"),
                liquidity_usd=None,  # honestly unrecoverable -- must stay NULL
                market_state_confidence="LOW",
                evidence_reference="ev1",
            )
            id1 = await record_snapshot(session, draft1, now=now)

            draft2 = MarketSnapshotDraft(
                token_id=token_id,
                observed_at=datetime(2026, 1, 2, tzinfo=UTC),
                lifecycle_stage="AMM_POOL",
                source="test_source",
                price_usd=Decimal("0.05"),
                liquidity_usd=Decimal("10000"),
                market_state_confidence="HIGH",
                evidence_reference="ev2",
            )
            id2 = await record_snapshot(session, draft2, now=now)

        async with sessionmaker() as session:
            from argus.domain.token_market_snapshots import TokenMarketSnapshot

            row1 = (
                await session.execute(
                    select(TokenMarketSnapshot).where(TokenMarketSnapshot.snapshot_id == id1)
                )
            ).scalar_one()
            row2 = (
                await session.execute(
                    select(TokenMarketSnapshot).where(TokenMarketSnapshot.snapshot_id == id2)
                )
            ).scalar_one()

            # Older row unchanged after the second was recorded.
            assert row1.lifecycle_stage == "BONDING_CURVE"
            assert row1.price_usd == Decimal("0.001000000000000000")
            assert row1.liquidity_usd is None  # NULL preserved, not backfilled
            assert row1.observed_at != row1.chain_time  # distinct point-in-time fields
            assert row1.market_state_confidence == "LOW"
            assert row1.evidence_reference == "ev1"

            assert row2.lifecycle_stage == "AMM_POOL"
            assert row2.liquidity_usd == Decimal("10000.000000000000000000")
            assert row2.market_state_confidence == "HIGH"
    finally:
        await _cleanup_token(admin_engine, mint)
        await engine.dispose()


@pytest.mark.asyncio
async def test_p2t2_replaying_the_same_observation_is_idempotent(admin_engine) -> None:
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    now = datetime.now(UTC)
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        async with sessionmaker() as session, session.begin():
            token = Token(
                token_id=uuid.uuid4(),
                mint=mint,
                chain="solana",
                first_observed_at=now,
                mint_validated=False,
                current_lifecycle_stage=None,
                created_at=now,
            )
            session.add(token)
            await session.flush()
            token_id = token.token_id
            draft = MarketSnapshotDraft(
                token_id=token_id,
                observed_at=observed_at,
                lifecycle_stage="BONDING_CURVE",
                source="src",
                price_usd=Decimal("1"),
                liquidity_usd=Decimal("1"),
            )
            first_id = await record_snapshot(session, draft, now=now)

        async with sessionmaker() as session, session.begin():
            draft2 = MarketSnapshotDraft(
                token_id=token_id,
                observed_at=observed_at,
                lifecycle_stage="BONDING_CURVE",
                source="src",
                price_usd=Decimal("999"),
                liquidity_usd=Decimal("999"),
            )
            second_id = await record_snapshot(session, draft2, now=now)

        assert first_id == second_id
        async with sessionmaker() as session:
            from argus.domain.token_market_snapshots import TokenMarketSnapshot

            rows = (
                (
                    await session.execute(
                        select(TokenMarketSnapshot).where(TokenMarketSnapshot.token_id == token_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].price_usd == Decimal("1.000000000000000000")  # first value wins
    finally:
        await _cleanup_token(admin_engine, mint)
        await engine.dispose()


# ---------------------------------------------------------------------
# P2-T3 -- winner baseline is tradable and versioned (DB persistence)
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p2t3_zero_liquidity_baseline_excluded_and_milestone_versioned(admin_engine) -> None:
    mint = _unique_mint()
    _config, engine, sessionmaker = _sessionmaker()
    now = datetime.now(UTC)
    try:
        async with sessionmaker() as session, session.begin():
            token = Token(
                token_id=uuid.uuid4(),
                mint=mint,
                chain="solana",
                first_observed_at=now,
                mint_validated=False,
                current_lifecycle_stage=None,
                created_at=now,
            )
            session.add(token)
            await session.flush()
            token_id = token.token_id

            for draft in (
                MarketSnapshotDraft(
                    token_id=token_id,
                    observed_at=datetime(2026, 1, 1, tzinfo=UTC),
                    lifecycle_stage="BONDING_CURVE",
                    source="src",
                    price_usd=Decimal("0.00000001"),
                    liquidity_usd=Decimal("0"),
                ),
                MarketSnapshotDraft(
                    token_id=token_id,
                    observed_at=datetime(2026, 1, 2, tzinfo=UTC),
                    lifecycle_stage="BONDING_CURVE",
                    source="src",
                    price_usd=Decimal("1"),
                    liquidity_usd=Decimal("5000"),
                ),
                MarketSnapshotDraft(
                    token_id=token_id,
                    observed_at=datetime(2026, 1, 3, tzinfo=UTC),
                    lifecycle_stage="AMM_POOL",
                    source="src",
                    price_usd=Decimal("15"),
                    liquidity_usd=Decimal("50000"),
                ),
            ):
                await record_snapshot(session, draft, now=now)

            evaluations = await evaluate_token(session, token_id=token_id, now=now)

        assert len(evaluations) == 1
        crossing = evaluations[0].crossing
        assert crossing.category == "MAJOR_WINNER"
        assert crossing.baseline_price == Decimal("1.000000000000000000")  # NOT 0.00000001
        assert crossing.baseline_liquidity == Decimal("5000.000000000000000000")
        assert crossing.peak_price == Decimal("15.000000000000000000")
        assert crossing.multiple_x == Decimal("15.000000")
        assert crossing.winner_definition_version
        assert crossing.reason_codes == "ZERO_LIQUIDITY_SNAPSHOTS_EXCLUDED_FROM_BASELINE"

        async with sessionmaker() as session:
            from argus.domain.token_winner_milestones import TokenWinnerMilestone

            row = (
                await session.execute(
                    select(TokenWinnerMilestone).where(TokenWinnerMilestone.token_id == token_id)
                )
            ).scalar_one()
            assert row.winner_definition_version == crossing.winner_definition_version
            assert row.baseline_timestamp == datetime(2026, 1, 2, tzinfo=UTC)
            assert row.peak_timestamp == datetime(2026, 1, 3, tzinfo=UTC)
    finally:
        await _cleanup_token(admin_engine, mint)
        await engine.dispose()


# ---------------------------------------------------------------------
# P2-T4 -- historical archaeology works on real committed evidence
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p2t4_historical_archaeology_on_real_evidence(admin_engine) -> None:
    """Uses the actual verified real pump.fun token from Phase 1.5 -- the
    exact production CLI/service path (``run_archaeology``), not a mock."""
    config, engine, sessionmaker = _sessionmaker()
    now = datetime.now(UTC)
    mint = PUMPFUN_MINT
    try:
        await _cleanup_token(admin_engine, mint)  # in case a prior run left residue
        tx = _pumpfun_transaction_evidence()

        async with sessionmaker() as session, session.begin():
            import_result = await import_bootstrap_token(
                session,
                mint=mint,
                evidence=tx.raw,
                evidence_kind="token_balance",
                evidence_reference=PUMPFUN_EVIDENCE_PATH,
                now=now,
                config=config,
                git_commit="TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB",
            )
        assert import_result.mint_validated is True
        token_id = import_result.token_id

        async with sessionmaker() as session, session.begin():
            result = await run_archaeology(
                session,
                token_id=token_id,
                mint=mint,
                run_type=TRIGGER_TYPE_HISTORICAL_WINNER,
                transactions=[tx],
                discovery_channel=DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY,
                source_provider_set="0xjeffro/tx-parser@475b1ebff79a2f41ec966919fdefa01f11f6c5d7",
                input_evidence_reference=PUMPFUN_EVIDENCE_PATH,
                time_range_start=None,
                time_range_end=None,
                known_gaps="only the creation transaction is available in this sandbox",
                completeness_statement="1 of an unknown total transaction count for this mint",
                config=config,
                git_commit="TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB",
                now=now,
                deployer_wallet=PUMPFUN_CREATOR,
            )

        assert result.status == RUN_STATUS_COMPLETED
        assert result.early_buyers_recovered == 2
        assert result.wallets_discovered == 2

        async with sessionmaker() as session:
            from argus.domain.archaeology_runs import ArchaeologyRun

            run_row = (
                await session.execute(
                    select(ArchaeologyRun).where(ArchaeologyRun.run_id == result.run_id)
                )
            ).scalar_one()
            assert run_row.source_provider_set.startswith("0xjeffro/tx-parser@")
            assert run_row.time_range_start is None
            assert "sandbox" in (run_row.known_gaps or "")
            assert run_row.completeness_statement
            assert run_row.input_evidence_reference == PUMPFUN_EVIDENCE_PATH
            assert run_row.status == RUN_STATUS_COMPLETED
            assert run_row.build_hash and run_row.config_hash and run_row.master_spec_hash
            assert run_row.git_commit

            buyers = (
                (await session.execute(select(EarlyBuyer).where(EarlyBuyer.token_id == token_id)))
                .scalars()
                .all()
            )
            assert len(buyers) == 2
            deployer_row = next(b for b in buyers if b.possible_deployer)
            assert deployer_row.amount_raw > 0

            discovery_events = (
                (
                    await session.execute(
                        select(WalletDiscoveryEvent).where(
                            WalletDiscoveryEvent.trigger_token_id == token_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(discovery_events) == 2
    finally:
        wallets_to_clean = [PUMPFUN_CREATOR, "CQrqvWERJtEjw2rCCQV6EqfM6V6jzTuKjhJjKNFmGB7r"]
        await _cleanup_token(admin_engine, mint)
        await _cleanup_wallets(admin_engine, wallets_to_clean)
        await engine.dispose()


@pytest.mark.asyncio
async def test_p2t4_retry_does_not_erase_or_duplicate_prior_run(admin_engine) -> None:
    config, engine, sessionmaker = _sessionmaker()
    now = datetime.now(UTC)
    mint = _unique_mint()
    try:
        async with sessionmaker() as session, session.begin():
            token = Token(
                token_id=uuid.uuid4(),
                mint=mint,
                chain="solana",
                first_observed_at=now,
                mint_validated=True,
                current_lifecycle_stage=None,
                created_at=now,
            )
            session.add(token)
            await session.flush()
            token_id = token.token_id

        buyer = _unique_wallet()
        raw = {
            "meta": {
                "err": None,
                "preTokenBalances": [],
                "postTokenBalances": [
                    {
                        "accountIndex": 0,
                        "mint": mint,
                        "owner": buyer,
                        "uiTokenAmount": {"amount": "1000", "decimals": 6},
                    }
                ],
            }
        }
        tx = RawTransactionEvidence(
            raw=raw, signature="sig1", slot=1, block_time=None, evidence_reference="x"
        )

        async with sessionmaker() as session, session.begin():
            first = await run_archaeology(
                session,
                token_id=token_id,
                mint=mint,
                run_type=TRIGGER_TYPE_HISTORICAL_WINNER,
                transactions=[tx],
                discovery_channel=DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY,
                source_provider_set="test",
                input_evidence_reference="x",
                time_range_start=None,
                time_range_end=None,
                known_gaps=None,
                completeness_statement="complete",
                config=config,
                git_commit="TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB",
                now=now,
            )
        assert first.early_buyers_recovered == 1

        async with sessionmaker() as session, session.begin():
            retry = await run_archaeology(
                session,
                token_id=token_id,
                mint=mint,
                run_type=TRIGGER_TYPE_HISTORICAL_WINNER,
                transactions=[tx],
                discovery_channel=DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY,
                source_provider_set="test",
                input_evidence_reference="x",
                time_range_start=None,
                time_range_end=None,
                known_gaps=None,
                completeness_statement="complete",
                config=config,
                git_commit="TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB",
                now=now,
            )
        assert retry.run_id != first.run_id  # a genuine new run row, not erased
        assert retry.early_buyers_recovered == 0  # but no duplicate output row

        async with sessionmaker() as session:
            from argus.domain.archaeology_runs import ArchaeologyRun

            runs = (
                (
                    await session.execute(
                        select(ArchaeologyRun).where(ArchaeologyRun.token_id == token_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(runs) == 2  # both runs preserved
            buyers = (
                (await session.execute(select(EarlyBuyer).where(EarlyBuyer.token_id == token_id)))
                .scalars()
                .all()
            )
            assert len(buyers) == 1  # exactly one canonical output row
    finally:
        await _cleanup_token(admin_engine, mint)
        await _cleanup_wallets(admin_engine, [buyer])
        await engine.dispose()


# ---------------------------------------------------------------------
# P2-T6 -- discovery contamination remains identifiable
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p2t6_discovery_provenance_is_complete_and_marked_contaminated(admin_engine) -> None:
    config, engine, sessionmaker = _sessionmaker()
    now = datetime.now(UTC)
    mint = _unique_mint()
    buyer = _unique_wallet()
    try:
        async with sessionmaker() as session, session.begin():
            token = Token(
                token_id=uuid.uuid4(),
                mint=mint,
                chain="solana",
                first_observed_at=now,
                mint_validated=True,
                current_lifecycle_stage=None,
                created_at=now,
            )
            session.add(token)
            await session.flush()
            token_id = token.token_id

        raw = {
            "meta": {
                "err": None,
                "postTokenBalances": [
                    {
                        "accountIndex": 0,
                        "mint": mint,
                        "owner": buyer,
                        "uiTokenAmount": {"amount": "1000", "decimals": 6},
                    }
                ],
            }
        }
        tx = RawTransactionEvidence(
            raw=raw, signature="sig-t6", slot=1, block_time=None, evidence_reference="x"
        )

        async with sessionmaker() as session, session.begin():
            result = await run_archaeology(
                session,
                token_id=token_id,
                mint=mint,
                run_type=TRIGGER_TYPE_HISTORICAL_WINNER,
                transactions=[tx],
                discovery_channel=DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY,
                source_provider_set="test",
                input_evidence_reference="x",
                time_range_start=None,
                time_range_end=None,
                known_gaps=None,
                completeness_statement="complete",
                config=config,
                git_commit="TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB",
                now=now,
            )

        async with sessionmaker() as session:
            wallet_row = (
                await session.execute(select(Wallet).where(Wallet.wallet_address == buyer))
            ).scalar_one()
            event = (
                await session.execute(
                    select(WalletDiscoveryEvent).where(
                        WalletDiscoveryEvent.wallet_id == wallet_row.wallet_id
                    )
                )
            ).scalar_one()
            assert event.discovery_channel == DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY
            assert event.trigger_token_id == token_id
            assert str(result.run_id) == event.trigger_event
            assert event.trigger_reason
            assert event.algorithm_version
            # Permanently marked for later QUALIFICATION SCORE exclusion,
            # never deleted (section 30).
            assert event.exclusion_reason == EXCLUSION_REASON_DISCOVERY_CONTAMINATION
    finally:
        await _cleanup_token(admin_engine, mint)
        await _cleanup_wallets(admin_engine, [buyer])
        await engine.dispose()


# ---------------------------------------------------------------------
# P2-T7 (DB half) -- prospective milestone trigger idempotency end-to-end
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p2t7_replayed_evaluation_never_creates_duplicate_milestone_or_trigger(
    admin_engine,
) -> None:
    _config, engine, sessionmaker = _sessionmaker()
    now = datetime.now(UTC)
    mint = _unique_mint()
    try:
        async with sessionmaker() as session, session.begin():
            token = Token(
                token_id=uuid.uuid4(),
                mint=mint,
                chain="solana",
                first_observed_at=now,
                mint_validated=True,
                current_lifecycle_stage=None,
                created_at=now,
            )
            session.add(token)
            await session.flush()
            token_id = token.token_id
            for draft in (
                MarketSnapshotDraft(
                    token_id=token_id,
                    observed_at=datetime(2026, 1, 1, tzinfo=UTC),
                    lifecycle_stage="BONDING_CURVE",
                    source="src",
                    price_usd=Decimal("1"),
                    liquidity_usd=Decimal("1000"),
                ),
                MarketSnapshotDraft(
                    token_id=token_id,
                    observed_at=datetime(2026, 1, 2, tzinfo=UTC),
                    lifecycle_stage="AMM_POOL",
                    source="src",
                    price_usd=Decimal("11"),
                    liquidity_usd=Decimal("5000"),
                ),
            ):
                await record_snapshot(session, draft, now=now)
            first_pass = await evaluate_token(session, token_id=token_id, now=now)

        assert len(first_pass) == 1
        assert first_pass[0].milestone_newly_recorded is True
        assert first_pass[0].trigger_newly_recorded is True

        # Duplicate delivery / restarted-worker replay: re-evaluate the
        # identical snapshot history from scratch.
        async with sessionmaker() as session, session.begin():
            second_pass = await evaluate_token(session, token_id=token_id, now=now)
        assert second_pass == []

        async with sessionmaker() as session:
            from argus.domain.token_winner_milestones import TokenWinnerMilestone

            milestones = (
                (
                    await session.execute(
                        select(TokenWinnerMilestone).where(
                            TokenWinnerMilestone.token_id == token_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(milestones) == 1
            from argus.domain.archaeology_triggers import ArchaeologyTrigger

            triggers = (
                (
                    await session.execute(
                        select(ArchaeologyTrigger).where(ArchaeologyTrigger.token_id == token_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(triggers) == 1
            assert triggers[0].trigger_type == TRIGGER_TYPE_PROSPECTIVE_WINNER
    finally:
        await _cleanup_token(admin_engine, mint)
        await engine.dispose()


@pytest.mark.asyncio
async def test_p2t7_at_most_one_historical_trigger_per_token(admin_engine) -> None:
    _config, engine, sessionmaker = _sessionmaker()
    now = datetime.now(UTC)
    mint = _unique_mint()
    try:
        async with sessionmaker() as session, session.begin():
            token = Token(
                token_id=uuid.uuid4(),
                mint=mint,
                chain="solana",
                first_observed_at=now,
                mint_validated=True,
                current_lifecycle_stage=None,
                created_at=now,
            )
            session.add(token)
            await session.flush()
            token_id = token.token_id
            first = await get_or_create_historical_trigger(
                session, token_id=token_id, trigger_reason="human request", now=now
            )
            second = await get_or_create_historical_trigger(
                session, token_id=token_id, trigger_reason="duplicate human request", now=now
            )
        assert first == second

        async with sessionmaker() as session:
            from argus.domain.archaeology_triggers import ArchaeologyTrigger

            triggers = (
                (
                    await session.execute(
                        select(ArchaeologyTrigger).where(
                            ArchaeologyTrigger.token_id == token_id,
                            ArchaeologyTrigger.trigger_type == TRIGGER_TYPE_HISTORICAL_WINNER,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(triggers) == 1
    finally:
        await _cleanup_token(admin_engine, mint)
        await engine.dispose()


# ---------------------------------------------------------------------
# P2-T8 -- historical evidence failure matrix
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p2t8_empty_evidence_set_completes_honestly_with_zero_candidates(
    admin_engine,
) -> None:
    config, engine, sessionmaker = _sessionmaker()
    now = datetime.now(UTC)
    mint = _unique_mint()
    try:
        async with sessionmaker() as session, session.begin():
            token = Token(
                token_id=uuid.uuid4(),
                mint=mint,
                chain="solana",
                first_observed_at=now,
                mint_validated=False,
                current_lifecycle_stage=None,
                created_at=now,
            )
            session.add(token)
            await session.flush()
            token_id = token.token_id

        async with sessionmaker() as session, session.begin():
            result = await run_archaeology(
                session,
                token_id=token_id,
                mint=mint,
                run_type=TRIGGER_TYPE_HISTORICAL_WINNER,
                transactions=[],
                discovery_channel=DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY,
                source_provider_set="test",
                input_evidence_reference="none",
                time_range_start=None,
                time_range_end=None,
                known_gaps="no evidence located",
                completeness_statement="zero transactions found for this mint",
                config=config,
                git_commit="TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB",
                now=now,
            )
        assert result.status == RUN_STATUS_COMPLETED  # honest zero-result completion
        assert result.early_buyers_recovered == 0
    finally:
        await _cleanup_token(admin_engine, mint)
        await engine.dispose()


@pytest.mark.asyncio
async def test_p2t8_caller_asserted_partial_evidence_is_marked_partial(admin_engine) -> None:
    config, engine, sessionmaker = _sessionmaker()
    now = datetime.now(UTC)
    mint = _unique_mint()
    try:
        async with sessionmaker() as session, session.begin():
            token = Token(
                token_id=uuid.uuid4(),
                mint=mint,
                chain="solana",
                first_observed_at=now,
                mint_validated=False,
                current_lifecycle_stage=None,
                created_at=now,
            )
            session.add(token)
            await session.flush()
            token_id = token.token_id

        async with sessionmaker() as session, session.begin():
            result = await run_archaeology(
                session,
                token_id=token_id,
                mint=mint,
                run_type=TRIGGER_TYPE_HISTORICAL_WINNER,
                transactions=[],
                discovery_channel=DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY,
                source_provider_set="test",
                input_evidence_reference="partial-page-1-of-3",
                time_range_start=None,
                time_range_end=None,
                known_gaps="provider pagination truncated after page 1 of an unknown total",
                completeness_statement="only page 1 was recoverable before a rate limit",
                config=config,
                git_commit="TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB",
                now=now,
                is_partial=True,
            )
        assert result.status == RUN_STATUS_PARTIAL  # never silently reported COMPLETED
    finally:
        await _cleanup_token(admin_engine, mint)
        await engine.dispose()


@pytest.mark.asyncio
async def test_p2t8_malformed_evidence_fails_the_run_closed_not_silently(admin_engine) -> None:
    """A malformed raw amount (non-numeric string) makes extraction raise
    -- the run must land FAILED with a real error_reason, never COMPLETED
    with a wrong/partial result silently passed off as success."""
    config, engine, sessionmaker = _sessionmaker()
    now = datetime.now(UTC)
    mint = _unique_mint()
    try:
        async with sessionmaker() as session, session.begin():
            token = Token(
                token_id=uuid.uuid4(),
                mint=mint,
                chain="solana",
                first_observed_at=now,
                mint_validated=False,
                current_lifecycle_stage=None,
                created_at=now,
            )
            session.add(token)
            await session.flush()
            token_id = token.token_id

        raw = {
            "meta": {
                "err": None,
                "postTokenBalances": [
                    {
                        "accountIndex": 0,
                        "mint": mint,
                        "owner": _unique_wallet(),
                        "uiTokenAmount": {"amount": "not-a-number", "decimals": 6},
                    }
                ],
            }
        }
        tx = RawTransactionEvidence(
            raw=raw, signature="malformed-sig", slot=1, block_time=None, evidence_reference="x"
        )

        async with sessionmaker() as session, session.begin():
            result = await run_archaeology(
                session,
                token_id=token_id,
                mint=mint,
                run_type=TRIGGER_TYPE_HISTORICAL_WINNER,
                transactions=[tx],
                discovery_channel=DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY,
                source_provider_set="test",
                input_evidence_reference="x",
                time_range_start=None,
                time_range_end=None,
                known_gaps=None,
                completeness_statement="complete",
                config=config,
                git_commit="TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB",
                now=now,
            )
        assert result.status == RUN_STATUS_FAILED

        async with sessionmaker() as session:
            from argus.domain.archaeology_runs import ArchaeologyRun

            run_row = (
                await session.execute(
                    select(ArchaeologyRun).where(ArchaeologyRun.run_id == result.run_id)
                )
            ).scalar_one()
            assert run_row.status == RUN_STATUS_FAILED
            assert run_row.error_reason
            assert run_row.completed_at is not None  # never left RUNNING
    finally:
        await _cleanup_token(admin_engine, mint)
        await engine.dispose()


# ---------------------------------------------------------------------
# P2-T9 -- negative-control schema round trip
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p2t9_negative_control_round_trip_never_mislabels(admin_engine) -> None:
    _config, engine, sessionmaker = _sessionmaker()
    now = datetime.now(UTC)
    winner_mint = _unique_mint()
    control_mint = _unique_mint()
    try:
        async with sessionmaker() as session, session.begin():
            winner = Token(
                token_id=uuid.uuid4(),
                mint=winner_mint,
                chain="solana",
                first_observed_at=now,
                mint_validated=True,
                current_lifecycle_stage=None,
                created_at=now,
            )
            control = Token(
                token_id=uuid.uuid4(),
                mint=control_mint,
                chain="solana",
                first_observed_at=now,
                mint_validated=True,
                current_lifecycle_stage=None,
                created_at=now,
            )
            session.add_all([winner, control])
            await session.flush()

            draft = NegativeControlDraft(
                winner_token_id=winner.token_id,
                control_token_id=control.token_id,
                method_version="negative_control_v1",
                launch_period_match=True,
                venue_match=True,
                early_liquidity_delta_pct=Decimal("5.2"),
                early_market_cap_delta_pct=Decimal("-3.1"),
                early_tx_activity_delta_pct=Decimal("12.0"),
                evidence_reference="manual-match-test",
            )
            control_id = await record_negative_control(session, draft, now=now)

            # Idempotent replay.
            control_id_2 = await record_negative_control(session, draft, now=now)
        assert control_id == control_id_2

        async with sessionmaker() as session:
            from argus.domain.token_negative_controls import TokenNegativeControl

            row = (
                await session.execute(
                    select(TokenNegativeControl).where(
                        TokenNegativeControl.control_id == control_id
                    )
                )
            ).scalar_one()
            assert row.winner_token_id == winner.token_id
            assert row.control_token_id == control.token_id
            assert row.method_version == "negative_control_v1"
            # The control token's own `tokens` row carries no winner label
            # anywhere -- nothing in this schema marks it a winner.
            control_token_row = (
                await session.execute(select(Token).where(Token.token_id == control.token_id))
            ).scalar_one()
            assert not hasattr(control_token_row, "winner_category")

            rows = (
                (
                    await session.execute(
                        select(TokenNegativeControl).where(
                            TokenNegativeControl.winner_token_id == winner.token_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1  # no duplicate from the idempotent replay
    finally:
        await _cleanup_token(admin_engine, winner_mint)
        await _cleanup_token(admin_engine, control_mint)
        await engine.dispose()


# ---------------------------------------------------------------------
# P2-T10 -- migration/restart/concurrency safety
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p2t10_duplicate_trigger_delivery_cannot_create_two_runs(admin_engine) -> None:
    """Simulates two "concurrent" workers both trying to consume the same
    archaeology_triggers row into a run: the second must fail closed
    (the partial unique index on archaeology_runs.trigger_id), and its
    failed attempt's transaction must roll back completely -- no partial
    early_buyers/wallet_discovery_events row leaked from the loser."""
    config, engine, sessionmaker = _sessionmaker()
    now = datetime.now(UTC)
    mint = _unique_mint()
    buyer = _unique_wallet()
    try:
        async with sessionmaker() as session, session.begin():
            token = Token(
                token_id=uuid.uuid4(),
                mint=mint,
                chain="solana",
                first_observed_at=now,
                mint_validated=True,
                current_lifecycle_stage=None,
                created_at=now,
            )
            session.add(token)
            await session.flush()
            token_id = token.token_id
            trigger_id = await get_or_create_historical_trigger(
                session, token_id=token_id, trigger_reason="test", now=now
            )

        raw = {
            "meta": {
                "err": None,
                "postTokenBalances": [
                    {
                        "accountIndex": 0,
                        "mint": mint,
                        "owner": buyer,
                        "uiTokenAmount": {"amount": "500", "decimals": 6},
                    }
                ],
            }
        }
        tx = RawTransactionEvidence(
            raw=raw, signature="sig-concurrent", slot=1, block_time=None, evidence_reference="x"
        )

        async with sessionmaker() as session, session.begin():
            winner_result = await run_archaeology(
                session,
                token_id=token_id,
                mint=mint,
                run_type=TRIGGER_TYPE_HISTORICAL_WINNER,
                transactions=[tx],
                discovery_channel=DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY,
                source_provider_set="test",
                input_evidence_reference="x",
                time_range_start=None,
                time_range_end=None,
                known_gaps=None,
                completeness_statement="complete",
                config=config,
                git_commit="TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB",
                now=now,
                trigger_id=trigger_id,
            )
        assert winner_result.early_buyers_recovered == 1

        # The "loser" concurrent worker attempts the same trigger_id.
        with pytest.raises(Exception, match="(?i)unique|duplicate"):
            async with sessionmaker() as session, session.begin():
                await run_archaeology(
                    session,
                    token_id=token_id,
                    mint=mint,
                    run_type=TRIGGER_TYPE_HISTORICAL_WINNER,
                    transactions=[tx],
                    discovery_channel=DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY,
                    source_provider_set="test",
                    input_evidence_reference="x",
                    time_range_start=None,
                    time_range_end=None,
                    known_gaps=None,
                    completeness_statement="complete",
                    config=config,
                    git_commit="TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB",
                    now=now,
                    trigger_id=trigger_id,
                )

        async with sessionmaker() as session:
            from argus.domain.archaeology_runs import ArchaeologyRun

            runs = (
                (
                    await session.execute(
                        select(ArchaeologyRun).where(ArchaeologyRun.trigger_id == trigger_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(runs) == 1  # the loser's transaction rolled back entirely
            buyers = (
                (await session.execute(select(EarlyBuyer).where(EarlyBuyer.token_id == token_id)))
                .scalars()
                .all()
            )
            assert len(buyers) == 1  # no partial/duplicate output from the loser
    finally:
        await _cleanup_token(admin_engine, mint)
        await _cleanup_wallets(admin_engine, [buyer])
        await engine.dispose()


@pytest.mark.asyncio
async def test_p2t10_phase2_tables_have_role_grants_matching_immutability_convention(
    admin_engine,
) -> None:
    """Direct proof (not just code review) that argus_ingest can insert
    into every Phase 2 append-only table but cannot delete from it, and
    argus_research can read but not write -- the same DB-enforced
    immutability convention as parse_attempts/commitment_observations."""
    append_only_tables = [
        "token_mint_validations",
        "reference_asset_prices",
        "token_market_snapshots",
        "token_winner_milestones",
        "wallets",
        "wallet_discovery_events",
        "early_buyers",
        "token_negative_controls",
    ]
    async with admin_engine.connect() as conn:
        for table in append_only_tables:
            rows = (
                await conn.execute(
                    text(
                        "SELECT privilege_type FROM information_schema.role_table_grants "
                        "WHERE table_name = :t AND grantee = 'argus_ingest'"
                    ),
                    {"t": table},
                )
            ).fetchall()
            privileges = {r[0] for r in rows}
            assert privileges == {"SELECT", "INSERT"}, f"{table}: {privileges}"

            research_rows = (
                await conn.execute(
                    text(
                        "SELECT privilege_type FROM information_schema.role_table_grants "
                        "WHERE table_name = :t AND grantee = 'argus_research'"
                    ),
                    {"t": table},
                )
            ).fetchall()
            assert {r[0] for r in research_rows} == {"SELECT"}, f"{table}: research grants"

"""``argus report daily`` (MASTER_SPEC.md section 93) against real Postgres.

Seeds one real tracked wallet with a genuine SWAP_SIMPLE buy, runs the real
Phase 4 prospective-monitoring pass over it (producing a real
``prospective_events``/``shadow_intents`` row pair), then asserts the report
built by the real production ``build_daily_report`` function reflects those
real counts -- never a duplicated test-only reimplementation of the report's
own queries.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from argus.config import load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.chain_events import ChainEvent
from argus.domain.commitment import COMMITMENT_CONFIRMED, CommitmentObservation
from argus.domain.swaps import Swap
from argus.domain.wallet_score_snapshots import WalletScoreSnapshot
from argus.domain.wallet_tier_history import WalletTierTransition
from argus.domain.wallets import Wallet
from argus.reports.daily import build_daily_report
from argus.shadow.monitor import run_prospective_monitoring_pass

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("isolated_database")]

_NOW = datetime(2026, 6, 1, tzinfo=UTC)
_TEST_GIT_COMMIT = "TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB"
SOL_MINT = "So11111111111111111111111111111111111111112"


def _unique_wallet() -> str:
    return f"RPTW{uuid.uuid4().hex[:37]}"


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
    session, *, wallet_address: str, mint: str, at: datetime
) -> uuid.UUID:
    wallet_id = uuid.uuid4()
    session.add(
        Wallet(
            wallet_id=wallet_id,
            wallet_address=wallet_address,
            first_discovered_at=at,
            current_tier="A",
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
            descriptive_score=Decimal("90.000"),
            qualification_score=Decimal("90.000"),
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
            to_tier="A",
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
            transaction_signature=f"rpt-buy-{uuid.uuid4()}",
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
    return wallet_id


async def test_daily_report_reflects_real_seeded_signal_and_tracking_counts(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mint = f"RPTMint{uuid.uuid4().hex[:32]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            await _seed_tracked_wallet_with_buy_swap(
                session, wallet_address=wallet_address, mint=mint, at=_NOW
            )

        pass_result = await run_prospective_monitoring_pass(sessionmaker, config=config, now=_NOW)
        assert len(pass_result.prospective_events) == 1
        assert len(pass_result.shadow_intents) == 1

        report_now = _NOW + timedelta(minutes=1)
        report = await build_daily_report(
            sessionmaker,
            now=report_now,
            tier_allowed=config.get("thresholds.wallet_tier_allowed"),
        )

        assert report.window_end == report_now
        assert report.system["uptime"] == "UNAVAILABLE_OFFLINE_REPORT"
        assert report.tracking["tracked_wallets"] >= 1
        assert report.tracking["wallet_trades"] >= 1
        assert report.signals["signals"] >= 1
        assert report.signals["convergence_events"] == "NOT_IMPLEMENTED"
        # The shadow intent was just created -- not yet filled, so no
        # shadow trade has opened in this window.
        assert report.shadow["shadow_trades_opened_in_window"] == 0
        assert report.live == {
            "ready_state": False,
            "canary_state": False,
            "armed_state": False,
            "orders": "NOT_IMPLEMENTED",
            "fills": "NOT_IMPLEMENTED",
            "pnl": "NOT_IMPLEMENTED",
            "risk_events": "NOT_IMPLEMENTED",
            "rejections": "NOT_IMPLEMENTED",
        }
        assert report.research["hypothesis_changes"] == "NOT_IMPLEMENTED"
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


async def test_daily_report_window_excludes_activity_outside_the_reporting_window(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mint = f"RPTMint{uuid.uuid4().hex[:32]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            await _seed_tracked_wallet_with_buy_swap(
                session, wallet_address=wallet_address, mint=mint, at=_NOW
            )
        await run_prospective_monitoring_pass(sessionmaker, config=config, now=_NOW)

        # A report generated for a window that ends well before the
        # seeded activity must not count it.
        report = await build_daily_report(
            sessionmaker,
            now=datetime(2020, 1, 1, tzinfo=UTC),
            tier_allowed=config.get("thresholds.wallet_tier_allowed"),
        )

        assert report.discovery["new_wallets"] == 0
        assert report.signals["signals"] == 0
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()

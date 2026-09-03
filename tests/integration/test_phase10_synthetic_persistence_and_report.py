"""Phase 10 (SYNTHETIC SUPER-WALLET) DB-backed integration coverage:

- Real ``prospective_events``/``swaps``/``token_market_snapshots``
  evidence -> ``argus.synthetic.service.compute_and_persist_phase10`` ->
  idempotent persistence of ``synthetic_strategy_trades``/
  ``synthetic_strategy_summaries`` for all five strategies (A-E), even
  when a given strategy has zero qualifying triggers in this minimal
  fixture (an honest zero-trade summary, not a missing row).
- Strategy A (source entry -> source exit) resolves to a real priced
  trade with the expected realistic-cost-adjusted return.
- The real ``argus synthetic report`` CLI command, run through the same
  Typer app a human operator uses -- confirms the report is explicitly
  labeled shadow-only.

Follows the exact ``admin_engine``-gated skip pattern every other Phase
1-9 DB-backed integration test in this repo uses -- these tests SKIP
(never fail) when Postgres is unreachable in this sandbox.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from typer.testing import CliRunner

from argus.cli import app
from argus.config import ArgusConfig, load_config
from argus.convergence.service import ConvergenceRunConfig as Phase8RunConfig
from argus.counterfactual.service import Phase9RunConfig
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.chain_events import ChainEvent
from argus.domain.prospective_events import ProspectiveEvent
from argus.domain.swaps import Swap
from argus.domain.synthetic_strategy_summaries import SyntheticStrategySummary
from argus.domain.synthetic_strategy_trades import SyntheticStrategyTrade
from argus.domain.token_market_snapshots import TokenMarketSnapshot
from argus.domain.tokens import Token
from argus.domain.wallets import Wallet
from argus.graph.service import GraphRunConfig
from argus.synthetic.service import STRATEGY_CODES, Phase10RunConfig, compute_and_persist_phase10

SOL_MINT = "So11111111111111111111111111111111111111112"
_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

runner = CliRunner()


def _sessionmaker() -> tuple[ArgusConfig, Any, async_sessionmaker[Any]]:
    config = load_config()
    info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(info.as_asyncpg_url())
    return config, engine, async_sessionmaker(engine, expire_on_commit=False)


def _unique_wallet() -> str:
    return f"P10TEST{uuid.uuid4().hex[:37]}"


def _unique_mint() -> str:
    return f"P10TOK{uuid.uuid4().hex[:38]}"


async def _seed_wallet(session, *, address: str, at: datetime) -> uuid.UUID:
    wallet_id = uuid.uuid4()
    session.add(
        Wallet(
            wallet_id=wallet_id,
            wallet_address=address,
            first_discovered_at=at,
            current_tier="A",
            created_at=at,
        )
    )
    await session.flush()
    return wallet_id


async def _seed_token(session, *, mint: str, at: datetime) -> uuid.UUID:
    token_id = uuid.uuid4()
    session.add(Token(token_id=token_id, mint=mint, first_observed_at=at, created_at=at))
    await session.flush()
    return token_id


async def _seed_snapshot(session, *, token_id: uuid.UUID, at: datetime, price_usd: Decimal) -> None:
    session.add(
        TokenMarketSnapshot(
            snapshot_id=uuid.uuid4(),
            token_id=token_id,
            observed_at=at,
            lifecycle_stage="AMM_POOL",
            venue="pump.fun",
            price_usd=price_usd,
            liquidity_usd=Decimal(5_000),
            market_cap_usd=Decimal(10_000),
            source="p10-test",
            algorithm_version="p10-test",
            build_hash="p10-test-build",
            created_at=at,
        )
    )
    await session.flush()


async def _seed_buy(
    session,
    *,
    wallet_address: str,
    wallet_id: uuid.UUID,
    token_id: uuid.UUID,
    mint: str,
    at: datetime,
) -> None:
    event_id = uuid.uuid4()
    session.add(
        ChainEvent(
            event_id=event_id,
            chain="solana",
            slot=1,
            block_time=at,
            first_seen_at=at,
            provider="p10-test",
            provider_received_at=at,
            transaction_signature=f"p10-buy-{uuid.uuid4()}",
            event_type="TRANSACTION_OBSERVED",
            wallet_address=wallet_address,
            raw_payload={},
            payload_hash="h",
            parser_version="v1",
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
            output_amount_raw=200_000_000,
            output_amount_ui=Decimal(200),
            network_fee_raw=5000,
            slot=1,
            block_time=at,
            first_seen_at=at,
            confidence=Decimal("1.000"),
            parser_version="v1",
            build_hash="p10-test-build",
            created_at=at,
        )
    )
    await session.flush()
    session.add(
        ProspectiveEvent(
            prospective_event_id=uuid.uuid4(),
            wallet_id=wallet_id,
            swap_id=swap_id,
            event_id=event_id,
            token_id=token_id,
            leader_transaction_time=at,
            first_seen_at=at,
            wallet_tier_snapshot="A",
            token_state_snapshot={},
            position_size_context={},
            cluster_state_snapshot={},
            graph_state_snapshot={"available": False, "reason": "phase10-test"},
            algorithm_version="p10-test",
            created_at=at,
        )
    )
    await session.flush()


async def _seed_sell(session, *, wallet_address: str, mint: str, at: datetime) -> None:
    event_id = uuid.uuid4()
    session.add(
        ChainEvent(
            event_id=event_id,
            chain="solana",
            slot=2,
            block_time=at,
            first_seen_at=at,
            provider="p10-test",
            provider_received_at=at,
            transaction_signature=f"p10-sell-{uuid.uuid4()}",
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
            event_id=event_id,
            wallet_address=wallet_address,
            classification="SWAP_SIMPLE",
            input_mint=mint,
            input_amount_raw=200_000_000,
            input_amount_ui=Decimal(200),
            output_mint=SOL_MINT,
            output_amount_raw=120_000_000,
            output_amount_ui=Decimal("0.12"),
            network_fee_raw=5000,
            slot=2,
            block_time=at,
            first_seen_at=at,
            confidence=Decimal("1.000"),
            parser_version="v1",
            build_hash="p10-test-build",
            created_at=at,
        )
    )
    await session.flush()


_GRAPH_CONFIG = GraphRunConfig(
    max_lag=timedelta(minutes=30), min_observations=1, q_value_threshold=Decimal("0.99")
)
_PHASE8_CONFIG = Phase8RunConfig(
    window=timedelta(minutes=30),
    unknown_independence_weight=Decimal("0.75"),
    q_value_threshold=Decimal("0.99"),
    min_observations=1,
    strong_surprisal_threshold=Decimal("3.0"),
)
_PHASE9_CONFIG = Phase9RunConfig(
    horizons=(timedelta(minutes=5),),
    max_price_staleness=timedelta(minutes=30),
    max_control_tokens=10,
    entry_specialist_horizon=timedelta(minutes=5),
    discovery_min_observations=1,
    discovery_q_value_threshold=Decimal("0.99"),
    follower_influx_window=timedelta(minutes=30),
    exit_after_influx_window=timedelta(minutes=30),
    predation_influx_normalization_cap=Decimal(10),
    exit_convergence_window=timedelta(minutes=30),
    exit_convergence_unknown_independence_weight=Decimal("0.75"),
    min_exit_specialist_score=Decimal(70),
)
_CONFIG = Phase10RunConfig(
    entry_exit_price_max_staleness=timedelta(minutes=30),
    cost_bps=Decimal(100),
    max_concurrent_positions=10,
    high_convergence_surprisal_threshold=Decimal("3.0"),
    min_exit_specialist_score=Decimal(70),
    max_hold_duration=timedelta(hours=6),
)


async def test_strategy_a_resolves_with_realistic_cost(admin_engine) -> None:
    config, engine, sessionmaker = _sessionmaker()
    try:
        wallet_address = _unique_wallet()
        async with sessionmaker() as session, session.begin():
            wallet_id = await _seed_wallet(session, address=wallet_address, at=_NOW)
            mint = _unique_mint()
            token_id = await _seed_token(session, mint=mint, at=_NOW)
            await _seed_snapshot(session, token_id=token_id, at=_NOW, price_usd=Decimal(100))
            exit_at = _NOW + timedelta(hours=1)
            await _seed_snapshot(session, token_id=token_id, at=exit_at, price_usd=Decimal(110))
            await _seed_buy(
                session,
                wallet_address=wallet_address,
                wallet_id=wallet_id,
                token_id=token_id,
                mint=mint,
                at=_NOW,
            )
            await _seed_sell(session, wallet_address=wallet_address, mint=mint, at=exit_at)

        cutoff = _NOW + timedelta(hours=2)
        async with sessionmaker() as session, session.begin():
            result = await compute_and_persist_phase10(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                phase8_config=_PHASE8_CONFIG,
                phase9_config=_PHASE9_CONFIG,
                config=_CONFIG,
                computed_at=_NOW,
            )
        assert set(result.summaries.keys()) == set(STRATEGY_CODES)
        assert result.summaries["A"].trade_count >= 1

        async with sessionmaker() as session:
            trades = (
                (
                    await session.execute(
                        select(SyntheticStrategyTrade).where(
                            SyntheticStrategyTrade.strategy_code == "A",
                            SyntheticStrategyTrade.token_id == token_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(trades) == 1
            trade = trades[0]
            assert trade.outcome == "RESOLVED"
            assert trade.entry_price_usd == Decimal(100)
            assert trade.exit_price_usd == Decimal(110)
            assert trade.gross_return == Decimal("0.1")
            assert trade.net_return < trade.gross_return

            summaries = (
                (
                    await session.execute(
                        select(SyntheticStrategySummary).where(
                            SyntheticStrategySummary.as_of == cutoff
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert {s.strategy_code for s in summaries} == set(STRATEGY_CODES)
    finally:
        await engine.dispose()


async def test_rerun_over_identical_evidence_is_idempotent(admin_engine) -> None:
    config, engine, sessionmaker = _sessionmaker()
    try:
        wallet_address = _unique_wallet()
        async with sessionmaker() as session, session.begin():
            wallet_id = await _seed_wallet(session, address=wallet_address, at=_NOW)
            mint = _unique_mint()
            token_id = await _seed_token(session, mint=mint, at=_NOW)
            await _seed_snapshot(session, token_id=token_id, at=_NOW, price_usd=Decimal(100))
            await _seed_buy(
                session,
                wallet_address=wallet_address,
                wallet_id=wallet_id,
                token_id=token_id,
                mint=mint,
                at=_NOW,
            )

        cutoff = _NOW + timedelta(hours=2)
        async with sessionmaker() as session, session.begin():
            await compute_and_persist_phase10(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                phase8_config=_PHASE8_CONFIG,
                phase9_config=_PHASE9_CONFIG,
                config=_CONFIG,
                computed_at=_NOW,
            )
        async with sessionmaker() as session, session.begin():
            await compute_and_persist_phase10(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                phase8_config=_PHASE8_CONFIG,
                phase9_config=_PHASE9_CONFIG,
                config=_CONFIG,
                computed_at=_NOW + timedelta(seconds=1),
            )

        async with sessionmaker() as session:
            summaries = (
                (
                    await session.execute(
                        select(SyntheticStrategySummary).where(
                            SyntheticStrategySummary.strategy_code == "A",
                            SyntheticStrategySummary.as_of == cutoff,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(summaries) == 1
    finally:
        await engine.dispose()


def test_cli_synthetic_report_runs_and_is_labeled_shadow_only(admin_engine) -> None:
    result = runner.invoke(app, ["synthetic", "report", "--as-of", _NOW.isoformat()])
    assert result.exit_code == 0, result.output
    assert "strategies" in result.output
    assert '"shadow_only": true' in result.output
    assert "SHADOW ONLY" in result.output

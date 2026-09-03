"""Phase 9 (COUNTERFACTUAL ALPHA + SPECIALISTS) DB-backed integration
coverage:

- Real ``prospective_events``/``token_market_snapshots``/``swaps``
  evidence -> ``argus.counterfactual.service.compute_and_persist_phase9``
  -> idempotent persistence of ``counterfactual_alpha_estimates``/
  ``wallet_specialist_scores``/``wallet_predation_scores``/
  ``exit_convergence_events``.
- The real ``argus counterfactual report`` CLI command, run through the
  same Typer app a human operator uses.

Follows the exact ``admin_engine``-gated skip pattern every other Phase
1-8 DB-backed integration test in this repo uses -- these tests SKIP
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
from argus.counterfactual.service import Phase9RunConfig, compute_and_persist_phase9
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.chain_events import ChainEvent
from argus.domain.counterfactual_alpha_estimates import CounterfactualAlphaEstimate
from argus.domain.prospective_events import ProspectiveEvent
from argus.domain.swaps import Swap
from argus.domain.token_market_snapshots import TokenMarketSnapshot
from argus.domain.tokens import Token
from argus.domain.wallet_specialist_scores import WalletSpecialistScore
from argus.domain.wallets import Wallet
from argus.graph.service import GraphRunConfig

SOL_MINT = "So11111111111111111111111111111111111111112"
_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

runner = CliRunner()


def _sessionmaker() -> tuple[ArgusConfig, Any, async_sessionmaker[Any]]:
    config = load_config()
    info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(info.as_asyncpg_url())
    return config, engine, async_sessionmaker(engine, expire_on_commit=False)


def _unique_wallet() -> str:
    return f"P9TEST{uuid.uuid4().hex[:38]}"


def _unique_mint() -> str:
    return f"P9TOK{uuid.uuid4().hex[:39]}"


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
            source="p9-test",
            algorithm_version="p9-test",
            build_hash="p9-test-build",
            created_at=at,
        )
    )
    await session.flush()


async def _seed_prospective_event(
    session, *, wallet_id: uuid.UUID, token_id: uuid.UUID, output_mint: str, entered_at: datetime
) -> uuid.UUID:
    event_id = uuid.uuid4()
    session.add(
        ChainEvent(
            event_id=event_id,
            chain="solana",
            slot=1,
            block_time=entered_at,
            first_seen_at=entered_at,
            provider="p9-test",
            provider_received_at=entered_at,
            transaction_signature=f"p9-test-{uuid.uuid4()}",
            event_type="TRANSACTION_OBSERVED",
            wallet_address="leader-not-under-test",
            raw_payload={},
            payload_hash="h",
            parser_version="v1",
            created_at=entered_at,
        )
    )
    swap_id = uuid.uuid4()
    session.add(
        Swap(
            swap_id=swap_id,
            event_id=event_id,
            wallet_address="leader-not-under-test",
            classification="SWAP_SIMPLE",
            input_mint=SOL_MINT,
            input_amount_raw=100_000_000,
            input_amount_ui=Decimal("0.1"),
            output_mint=output_mint,
            output_amount_raw=200_000_000,
            output_amount_ui=Decimal(200),
            network_fee_raw=5000,
            slot=1,
            block_time=entered_at,
            first_seen_at=entered_at,
            confidence=Decimal("1.000"),
            parser_version="v1",
            build_hash="p9-test-build",
            created_at=entered_at,
        )
    )
    await session.flush()
    prospective_event_id = uuid.uuid4()
    session.add(
        ProspectiveEvent(
            prospective_event_id=prospective_event_id,
            wallet_id=wallet_id,
            swap_id=swap_id,
            event_id=event_id,
            token_id=token_id,
            leader_transaction_time=entered_at,
            first_seen_at=entered_at,
            wallet_tier_snapshot="A",
            token_state_snapshot={},
            position_size_context={},
            cluster_state_snapshot={},
            graph_state_snapshot={"available": False, "reason": "phase9-test"},
            algorithm_version="p9-test",
            created_at=entered_at,
        )
    )
    await session.flush()
    return prospective_event_id


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
_CONFIG = Phase9RunConfig(
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


async def test_counterfactual_alpha_computed_with_matched_control(admin_engine) -> None:
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            wallet_a = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)
            wallet_b = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)

            mint_wallet_token = _unique_mint()
            wallet_token_id = await _seed_token(session, mint=mint_wallet_token, at=_NOW)
            mint_control = _unique_mint()
            control_token_id = await _seed_token(session, mint=mint_control, at=_NOW)

            for token_id in (wallet_token_id, control_token_id):
                await _seed_snapshot(session, token_id=token_id, at=_NOW, price_usd=Decimal(100))
                await _seed_snapshot(
                    session,
                    token_id=token_id,
                    at=_NOW + timedelta(minutes=5),
                    price_usd=Decimal(110),
                )

            await _seed_prospective_event(
                session,
                wallet_id=wallet_a,
                token_id=wallet_token_id,
                output_mint=mint_wallet_token,
                entered_at=_NOW,
            )
            await _seed_prospective_event(
                session,
                wallet_id=wallet_b,
                token_id=wallet_token_id,
                output_mint=mint_wallet_token,
                entered_at=_NOW + timedelta(seconds=30),
            )

        cutoff = _NOW + timedelta(hours=1)
        async with sessionmaker() as session, session.begin():
            result = await compute_and_persist_phase9(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                phase8_config=_PHASE8_CONFIG,
                config=_CONFIG,
                computed_at=_NOW,
            )
        assert result.alpha_estimate_count >= 1
        assert result.specialist_score_count >= 1

        async with sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(CounterfactualAlphaEstimate).where(
                            CounterfactualAlphaEstimate.token_id == wallet_token_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) >= 1
            # Both tokens moved 100 -> 110 identically, so the residual
            # selection alpha should be exactly zero (no outperformance).
            for row in rows:
                if row.residual_selection_alpha is not None:
                    assert row.residual_selection_alpha == Decimal(0)
    finally:
        await engine.dispose()


async def test_rerun_over_identical_evidence_is_idempotent(admin_engine) -> None:
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            wallet_a = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)
            mint_wallet_token = _unique_mint()
            wallet_token_id = await _seed_token(session, mint=mint_wallet_token, at=_NOW)
            await _seed_snapshot(session, token_id=wallet_token_id, at=_NOW, price_usd=Decimal(100))
            await _seed_prospective_event(
                session,
                wallet_id=wallet_a,
                token_id=wallet_token_id,
                output_mint=mint_wallet_token,
                entered_at=_NOW,
            )

        cutoff = _NOW + timedelta(hours=1)
        async with sessionmaker() as session, session.begin():
            await compute_and_persist_phase9(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                phase8_config=_PHASE8_CONFIG,
                config=_CONFIG,
                computed_at=_NOW,
            )
        async with sessionmaker() as session, session.begin():
            await compute_and_persist_phase9(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                phase8_config=_PHASE8_CONFIG,
                config=_CONFIG,
                computed_at=_NOW + timedelta(seconds=1),
            )

        async with sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(WalletSpecialistScore).where(
                            WalletSpecialistScore.wallet_id == wallet_a,
                            WalletSpecialistScore.as_of == cutoff,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
    finally:
        await engine.dispose()


def test_cli_counterfactual_report_runs_and_prints_required_fields(admin_engine) -> None:
    result = runner.invoke(app, ["counterfactual", "report", "--as-of", _NOW.isoformat()])
    assert result.exit_code == 0, result.output
    assert "top_residual_selection_alpha" in result.output
    assert "specialists" in result.output
    assert "predation_scores" in result.output
    assert "purely observational" in result.output

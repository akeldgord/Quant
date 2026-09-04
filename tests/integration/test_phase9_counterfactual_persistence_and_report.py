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

import pytest
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
from argus.domain.lead_follow_observations import LeadFollowObservation
from argus.domain.prospective_events import ProspectiveEvent
from argus.domain.shadow_intents import STATUS_FILLED, ShadowIntent
from argus.domain.shadow_positions import ShadowPosition
from argus.domain.shadow_quote_probes import (
    OUTCOME_SUCCESS,
    PROBE_KIND_REVERSE_EXECUTABLE,
    ShadowQuoteProbe,
)
from argus.domain.swaps import Swap
from argus.domain.token_market_snapshots import TokenMarketSnapshot
from argus.domain.tokens import Token
from argus.domain.wallet_predation_scores import WalletPredationScore
from argus.domain.wallet_specialist_scores import WalletSpecialistScore
from argus.domain.wallets import Wallet
from argus.graph.service import ALGORITHM_VERSION as GRAPH_ALGORITHM_VERSION
from argus.graph.service import GraphRunConfig

SOL_MINT = "So11111111111111111111111111111111111111112"
pytestmark = pytest.mark.usefixtures("isolated_database")
# R2-04 (``argus-final-spec-recovery-002``): see
# ``tests/integration/conftest.py``'s ``isolated_database`` fixture --
# this module's own production queries scan ALL matching rows, so each
# TEST FUNCTION here gets its own real, independent database.

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


async def _seed_prospective_event_with_shadow_fill(
    session,
    *,
    wallet_id: uuid.UUID,
    token_id: uuid.UUID,
    output_mint: str,
    entered_at: datetime,
    entry_price_impact_pct: Decimal,
) -> uuid.UUID:
    """FSR-07: same as :func:`_seed_prospective_event`, but also seeds a
    FILLED :class:`ShadowIntent`/:class:`ShadowPosition` (carrying a
    known ``entry_price_impact_pct``) and a SUCCESS 5m
    :class:`ShadowQuoteProbe` -- the real Phase 5 evidence predation's
    price-impact input reuses."""
    prospective_event_id = await _seed_prospective_event(
        session,
        wallet_id=wallet_id,
        token_id=token_id,
        output_mint=output_mint,
        entered_at=entered_at,
    )
    intent_id = uuid.uuid4()
    session.add(
        ShadowIntent(
            shadow_intent_id=intent_id,
            prospective_event_id=prospective_event_id,
            wallet_id=wallet_id,
            token_id=token_id,
            input_mint=SOL_MINT,
            output_mint=output_mint,
            notional_input_amount_raw=100_000_000,
            config_hash="p9-fsr07-test-config",
            status=STATUS_FILLED,
            algorithm_version="p9-fsr07-test",
            created_at=entered_at,
        )
    )
    await session.flush()

    position_id = uuid.uuid4()
    session.add(
        ShadowPosition(
            shadow_position_id=position_id,
            shadow_intent_id=intent_id,
            wallet_id=wallet_id,
            token_id=token_id,
            input_mint=SOL_MINT,
            output_mint=output_mint,
            entry_input_amount_raw=100_000_000,
            entry_output_amount_raw=200_000_000,
            entry_price_impact_pct=entry_price_impact_pct,
            entry_route_present=True,
            entry_probe_target_label="0s",
            entry_requested_at=entered_at,
            entry_responded_at=entered_at,
            opened_at=entered_at,
            algorithm_version="p9-fsr07-test",
            created_at=entered_at,
        )
    )
    await session.flush()

    session.add(
        ShadowQuoteProbe(
            probe_id=uuid.uuid4(),
            probe_kind=PROBE_KIND_REVERSE_EXECUTABLE,
            target_label="5m",
            shadow_position_id=position_id,
            input_mint=output_mint,
            output_mint=SOL_MINT,
            notional_input_amount_raw=200_000_000,
            target_due_at=entered_at + timedelta(minutes=5),
            requested_at=entered_at + timedelta(minutes=5),
            responded_at=entered_at + timedelta(minutes=5, milliseconds=100),
            terminal_at=entered_at + timedelta(minutes=5, milliseconds=100),
            expected_output_amount_raw=210_000_000,
            route_present=True,
            outcome=OUTCOME_SUCCESS,
            algorithm_version="p9-fsr07-test",
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


async def test_fsr07_predation_incorporates_real_follower_price_impact(admin_engine) -> None:
    """FSR-07: when the follower's own Phase 5 executable-entry evidence
    is available, ``price_impact_mean`` is the real measured value (never
    NULL-by-default) and ``price_impact_incorporated`` is honestly True."""
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            leader = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)
            follower = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)
            mint = _unique_mint()
            token_id = await _seed_token(session, mint=mint, at=_NOW)
            await _seed_prospective_event(
                session, wallet_id=leader, token_id=token_id, output_mint=mint, entered_at=_NOW
            )
            await _seed_prospective_event_with_shadow_fill(
                session,
                wallet_id=follower,
                token_id=token_id,
                output_mint=mint,
                entered_at=_NOW + timedelta(seconds=30),
                entry_price_impact_pct=Decimal("5.5"),
            )
            # A leader exit shortly after the follower's influx.
            exit_event_id = uuid.uuid4()
            exit_at = _NOW + timedelta(minutes=10)
            session.add(
                ChainEvent(
                    event_id=exit_event_id,
                    chain="solana",
                    slot=2,
                    block_time=exit_at,
                    first_seen_at=exit_at,
                    provider="p9-fsr07-test",
                    provider_received_at=exit_at,
                    transaction_signature=f"p9-fsr07-exit-{uuid.uuid4()}",
                    event_type="TRANSACTION_OBSERVED",
                    wallet_address="leader-exit-address",
                    raw_payload={},
                    payload_hash="h",
                    parser_version="v1",
                    created_at=exit_at,
                )
            )
            leader_row = await session.get(Wallet, leader)
            session.add(
                Swap(
                    swap_id=uuid.uuid4(),
                    event_id=exit_event_id,
                    wallet_address=leader_row.wallet_address,
                    classification="SWAP_SIMPLE",
                    input_mint=mint,
                    input_amount_raw=200_000_000,
                    input_amount_ui=Decimal(200),
                    output_mint=SOL_MINT,
                    output_amount_raw=105_000_000,
                    output_amount_ui=Decimal("0.105"),
                    network_fee_raw=5000,
                    slot=2,
                    block_time=exit_at,
                    first_seen_at=exit_at,
                    confidence=Decimal("1.000"),
                    parser_version="v1",
                    build_hash="p9-fsr07-test-build",
                    created_at=exit_at,
                )
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

        async with sessionmaker() as session:
            row = (
                await session.execute(
                    select(WalletPredationScore).where(
                        WalletPredationScore.wallet_id == leader,
                        WalletPredationScore.as_of == cutoff,
                    )
                )
            ).scalar_one()
            assert row.entries_with_influx_count == 1
            assert row.exit_after_influx_count == 1
            assert row.price_impact_mean == Decimal("5.5")
            assert row.price_impact_incorporated is True
            assert row.predation_score is not None
    finally:
        await engine.dispose()


async def test_fsr07_predation_missing_price_impact_is_explicit_never_silent(admin_engine) -> None:
    """FSR-07: with follower influx but no shadow-fill evidence for the
    follower, ``price_impact_mean`` stays NULL and
    ``price_impact_incorporated`` is honestly False -- the core score
    (from influx/exit-timing/repetition alone) is still computed, never
    silently treated as complete."""
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            leader = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)
            follower = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)
            mint = _unique_mint()
            token_id = await _seed_token(session, mint=mint, at=_NOW)
            await _seed_prospective_event(
                session, wallet_id=leader, token_id=token_id, output_mint=mint, entered_at=_NOW
            )
            await _seed_prospective_event(
                session,
                wallet_id=follower,
                token_id=token_id,
                output_mint=mint,
                entered_at=_NOW + timedelta(seconds=30),
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

        async with sessionmaker() as session:
            row = (
                await session.execute(
                    select(WalletPredationScore).where(
                        WalletPredationScore.wallet_id == leader,
                        WalletPredationScore.as_of == cutoff,
                    )
                )
            ).scalar_one()
            assert row.entries_with_influx_count == 1
            assert row.price_impact_mean is None
            assert row.price_impact_incorporated is False
    finally:
        await engine.dispose()


async def test_fsr07_future_lead_follow_observation_beyond_cutoff_excluded_from_influx(
    admin_engine,
) -> None:
    """FSR-07/FSR-04 required test: a Phase 7 lead/follow observation not
    yet known by this run's own cutoff must not count toward follower
    influx, even when it describes entries that themselves precede the
    cutoff."""
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            leader = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)
            follower = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)
            mint = _unique_mint()
            token_id = await _seed_token(session, mint=mint, at=_NOW)
            leader_prospective_event_id = await _seed_prospective_event(
                session, wallet_id=leader, token_id=token_id, output_mint=mint, entered_at=_NOW
            )
            follower_entered_at = _NOW + timedelta(seconds=30)
            follower_prospective_event_id = await _seed_prospective_event(
                session,
                wallet_id=follower,
                token_id=token_id,
                output_mint=mint,
                entered_at=follower_entered_at,
            )
            # Directly seed the Phase 7 observation Phase 9 would
            # otherwise compute fresh, but with created_at set FAR beyond
            # this run's own cutoff -- idempotent Phase 7 persistence
            # reuses this exact row (same identity) rather than
            # overwriting it, so the future created_at survives into
            # what predation's own follower-influx query sees.
            session.add(
                LeadFollowObservation(
                    observation_id=uuid.uuid4(),
                    token_id=token_id,
                    leader_wallet_id=leader,
                    follower_wallet_id=follower,
                    leader_prospective_event_id=leader_prospective_event_id,
                    follower_prospective_event_id=follower_prospective_event_id,
                    leader_entered_at=_NOW,
                    follower_entered_at=follower_entered_at,
                    lag_seconds=Decimal("30"),
                    algorithm_version=GRAPH_ALGORITHM_VERSION,
                    created_at=_NOW + timedelta(days=2),
                )
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

        async with sessionmaker() as session:
            row = (
                await session.execute(
                    select(WalletPredationScore).where(
                        WalletPredationScore.wallet_id == leader,
                        WalletPredationScore.as_of == cutoff,
                    )
                )
            ).scalar_one()
            # The future-dated observation must not count as influx.
            assert row.entries_with_influx_count == 0
            assert row.follower_influx_mean == Decimal(0)
    finally:
        await engine.dispose()

"""Phase 11 (PREDICT INFORMED ORDER FLOW) DB-backed integration coverage:

- Real ``prospective_events``/``wallet_tier_history`` evidence ->
  ``argus.prediction.service.compute_and_persist_phase11`` -> idempotent
  persistence of ``order_flow_prediction_runs`` for every (horizon, model
  family) combination -- including an honest ``INSUFFICIENT_SAMPLE`` row
  (never a fabricated one) for the model families whose named feature
  subset has no supporting evidence in this minimal fixture.
- The ``BASELINE_RANDOM`` family (no feature dependency) reaches
  ``EVALUATED`` on a small, deliberately class-balanced fixture, proving
  the strict temporal split and sample gate both work end to end.
- The real ``argus predict report`` CLI command, run through the same
  Typer app a human operator uses.

Follows the exact ``admin_engine``-gated skip pattern every other Phase
1-10 DB-backed integration test in this repo uses -- these tests SKIP
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
from argus.domain.order_flow_prediction_runs import (
    MODEL_BASELINE_RANDOM,
    MODEL_FAMILIES,
    STATUS_EVALUATED,
    STATUS_INSUFFICIENT_SAMPLE,
    OrderFlowPredictionRun,
)
from argus.domain.prospective_events import ProspectiveEvent
from argus.domain.swaps import Swap
from argus.domain.token_market_snapshots import TokenMarketSnapshot
from argus.domain.tokens import Token
from argus.domain.wallet_specialist_scores import WalletSpecialistScore
from argus.domain.wallet_tier_history import WalletTierTransition
from argus.domain.wallets import Wallet
from argus.graph.service import GraphRunConfig
from argus.prediction.loaders import compute_raw_features, load_discovery_effect_size_by_wallet
from argus.prediction.service import (
    ALGORITHM_VERSION,
    Phase11RunConfig,
    compute_and_persist_phase11,
)

SOL_MINT = "So11111111111111111111111111111111111111112"
_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

runner = CliRunner()


def _sessionmaker() -> tuple[ArgusConfig, Any, async_sessionmaker[Any]]:
    config = load_config()
    info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(info.as_asyncpg_url())
    return config, engine, async_sessionmaker(engine, expire_on_commit=False)


def _unique_wallet() -> str:
    return f"P11TEST{uuid.uuid4().hex[:37]}"


def _unique_mint() -> str:
    return f"P11TOK{uuid.uuid4().hex[:38]}"


async def _seed_wallet(session, *, address: str, at: datetime) -> uuid.UUID:
    wallet_id = uuid.uuid4()
    session.add(
        Wallet(wallet_id=wallet_id, wallet_address=address, first_discovered_at=at, created_at=at)
    )
    await session.flush()
    return wallet_id


async def _seed_elite_transition(session, *, wallet_id: uuid.UUID, at: datetime) -> None:
    session.add(
        WalletTierTransition(
            transition_id=uuid.uuid4(),
            wallet_id=wallet_id,
            source_score_id=None,
            from_tier=None,
            to_tier="A",
            reason="p11-test",
            transitioned_at=at,
            created_at=at,
        )
    )
    await session.flush()


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
            source="p11-test",
            algorithm_version="p11-test",
            build_hash="p11-test-build",
            created_at=at,
        )
    )
    await session.flush()


async def _seed_entry(
    session,
    *,
    wallet_address: str,
    wallet_id: uuid.UUID,
    token_id: uuid.UUID,
    mint: str,
    at: datetime,
    tier_snapshot: str = "DISCOVERED",
) -> None:
    event_id = uuid.uuid4()
    session.add(
        ChainEvent(
            event_id=event_id,
            chain="solana",
            slot=1,
            block_time=at,
            first_seen_at=at,
            provider="p11-test",
            provider_received_at=at,
            transaction_signature=f"p11-buy-{uuid.uuid4()}",
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
            build_hash="p11-test-build",
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
            wallet_tier_snapshot=tier_snapshot,
            token_state_snapshot={},
            position_size_context={},
            cluster_state_snapshot={},
            graph_state_snapshot={"available": False, "reason": "phase11-test"},
            algorithm_version="p11-test",
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
_CONFIG = Phase11RunConfig(
    horizons=(timedelta(minutes=5),),
    train_fraction=Decimal("0.5"),
    min_class_count=1,
    max_price_staleness=timedelta(minutes=30),
    token_momentum_window=timedelta(hours=1),
    classification_threshold=Decimal("0.5"),
)


async def _seed_class_balanced_fixture(session) -> None:
    """6 non-elite tracked-wallet entries into 6 distinct tokens, strictly
    increasing in time (10-minute spacing, well beyond the 5-minute
    horizon so no unintended window crosses another entry), alternating
    followed/not-followed by a real elite wallet within the 5-minute
    horizon -- True, False, True, False, True, False in chronological
    order. Under FSR-11's purged+embargoed 0.5 split this yields train =
    [True, False, True] (index 3, "False", sits exactly at the split
    boundary and is purged) and test = [True, False] -- BOTH classes in
    BOTH splits, satisfying the ``min_class_count=1`` gate this fixture is
    built to exercise."""
    follower_address = _unique_wallet()
    follower_id = await _seed_wallet(session, address=follower_address, at=_NOW)

    elite_address = _unique_wallet()
    elite_id = await _seed_wallet(session, address=elite_address, at=_NOW - timedelta(hours=1))
    await _seed_elite_transition(session, wallet_id=elite_id, at=_NOW - timedelta(minutes=30))

    followed = [True, False, True, False, True, False]
    for i, is_followed in enumerate(followed):
        entry_at = _NOW + timedelta(minutes=i * 10)
        mint = _unique_mint()
        token_id = await _seed_token(session, mint=mint, at=entry_at)
        await _seed_entry(
            session,
            wallet_address=follower_address,
            wallet_id=follower_id,
            token_id=token_id,
            mint=mint,
            at=entry_at,
        )
        if is_followed:
            await _seed_entry(
                session,
                wallet_address=elite_address,
                wallet_id=elite_id,
                token_id=token_id,
                mint=mint,
                at=entry_at + timedelta(minutes=2),
                tier_snapshot="A",
            )


async def test_baseline_random_reaches_evaluated_on_class_balanced_fixture(admin_engine) -> None:
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            await _seed_class_balanced_fixture(session)

        cutoff = _NOW + timedelta(hours=1)
        async with sessionmaker() as session, session.begin():
            result = await compute_and_persist_phase11(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                phase8_config=_PHASE8_CONFIG,
                phase9_config=_PHASE9_CONFIG,
                config=_CONFIG,
                computed_at=_NOW,
            )
        assert result.run_count == len(MODEL_FAMILIES)

        async with sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(OrderFlowPredictionRun).where(
                            OrderFlowPredictionRun.as_of == cutoff,
                            OrderFlowPredictionRun.algorithm_version == ALGORITHM_VERSION,
                            OrderFlowPredictionRun.config_hash == _CONFIG.config_hash(),
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert {r.model_family for r in rows} == set(MODEL_FAMILIES)

            random_row = next(r for r in rows if r.model_family == MODEL_BASELINE_RANDOM)
            assert random_row.status == STATUS_EVALUATED
            assert random_row.train_sample_size == 3
            assert random_row.test_sample_size == 2
            assert random_row.feature_set == []
            assert random_row.auc_roc is not None
            # FSR-11: the purged+embargoed split's own required metadata is
            # persisted -- the boundary-straddling 4th entry was purged.
            assert random_row.split_boundary is not None
            assert random_row.embargo_seconds == 300
            assert random_row.purged_count == 1
            assert random_row.train_range_start is not None
            assert random_row.test_range_start is not None
            assert random_row.test_range_start >= random_row.split_boundary + timedelta(
                seconds=random_row.embargo_seconds
            )

            # These families need token/wallet-history/graph evidence this
            # minimal fixture never seeds -- every row is dropped by
            # select_features, so the honest outcome is INSUFFICIENT_SAMPLE,
            # never a fabricated fit on zero real feature rows.
            for row in rows:
                if row.model_family != MODEL_BASELINE_RANDOM:
                    assert row.status == STATUS_INSUFFICIENT_SAMPLE
                    assert row.auc_roc is None
                    assert row.log_loss is None
                    assert row.brier_score is None
                    assert row.accuracy_at_threshold is None
    finally:
        await engine.dispose()


async def test_rerun_over_identical_evidence_is_idempotent(admin_engine) -> None:
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            await _seed_class_balanced_fixture(session)

        cutoff = _NOW + timedelta(hours=1)
        async with sessionmaker() as session, session.begin():
            await compute_and_persist_phase11(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                phase8_config=_PHASE8_CONFIG,
                phase9_config=_PHASE9_CONFIG,
                config=_CONFIG,
                computed_at=_NOW,
            )
        async with sessionmaker() as session, session.begin():
            await compute_and_persist_phase11(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                phase8_config=_PHASE8_CONFIG,
                phase9_config=_PHASE9_CONFIG,
                config=_CONFIG,
                computed_at=_NOW + timedelta(seconds=1),
            )

        async with sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(OrderFlowPredictionRun).where(
                            OrderFlowPredictionRun.as_of == cutoff,
                            OrderFlowPredictionRun.algorithm_version == ALGORITHM_VERSION,
                            OrderFlowPredictionRun.config_hash == _CONFIG.config_hash(),
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == len(MODEL_FAMILIES)
    finally:
        await engine.dispose()


async def test_elite_wallets_own_entry_is_never_an_observation(admin_engine) -> None:
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            elite_address = _unique_wallet()
            elite_id = await _seed_wallet(
                session, address=elite_address, at=_NOW - timedelta(hours=1)
            )
            await _seed_elite_transition(
                session, wallet_id=elite_id, at=_NOW - timedelta(minutes=30)
            )
            mint = _unique_mint()
            token_id = await _seed_token(session, mint=mint, at=_NOW)
            await _seed_entry(
                session,
                wallet_address=elite_address,
                wallet_id=elite_id,
                token_id=token_id,
                mint=mint,
                at=_NOW,
                tier_snapshot="A",
            )

        cutoff = _NOW + timedelta(hours=1)
        async with sessionmaker() as session, session.begin():
            result = await compute_and_persist_phase11(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                phase8_config=_PHASE8_CONFIG,
                phase9_config=_PHASE9_CONFIG,
                config=_CONFIG,
                computed_at=_NOW,
            )
        # No non-elite observation exists at all -- every model family
        # must report INSUFFICIENT_SAMPLE, never a fit on an empty (or
        # entirely elite-excluded) population.
        assert result.evaluated_count == 0
        assert result.insufficient_sample_count == len(MODEL_FAMILIES)
    finally:
        await engine.dispose()


async def test_momentum_ignores_a_closer_future_snapshot(admin_engine) -> None:
    """FSR-09: entry/prior momentum prices must be the latest snapshot AT
    OR BEFORE their own target time -- never the "nearest" snapshot, which
    could be strictly AFTER ``entered_at`` and closer in wall-clock time
    than the real pre-observation snapshot. A poison snapshot placed 1
    second after ``entered_at`` (far closer than the genuine pre-
    observation one) must be ignored entirely."""
    config, engine, sessionmaker = _sessionmaker()
    try:
        entered_at = _NOW
        mint = _unique_mint()
        async with sessionmaker() as session, session.begin():
            token_id = await _seed_token(session, mint=mint, at=entered_at - timedelta(hours=2))
            # Real pre-observation prices (at-or-before their own targets).
            await _seed_snapshot(
                session,
                token_id=token_id,
                at=entered_at - timedelta(hours=1, minutes=5),
                price_usd=Decimal(100),
            )
            await _seed_snapshot(
                session,
                token_id=token_id,
                at=entered_at - timedelta(minutes=5),
                price_usd=Decimal(110),
            )
            # Poison: strictly AFTER entered_at, and far closer to it than
            # the real pre-observation snapshot above -- must never be used.
            await _seed_snapshot(
                session,
                token_id=token_id,
                at=entered_at + timedelta(seconds=1),
                price_usd=Decimal(99999),
            )
            token = await session.get(Token, token_id)

        async with sessionmaker() as session:
            raw = await compute_raw_features(
                session,
                wallet_id=uuid.uuid4(),
                token_id=token_id,
                entered_at=entered_at,
                token_by_id={token_id: token},
                fingerprints_by_wallet={},
                discovery_effect_size_by_wallet={},
                max_staleness_seconds=timedelta(hours=2).total_seconds(),
                momentum_window=timedelta(hours=1),
            )
        # (110 / 100) - 1 -- the real pre-observation prices, never the
        # poison future snapshot (which would have produced a huge value).
        assert raw.token_momentum_pct == Decimal("0.1")
    finally:
        await engine.dispose()


async def test_momentum_missing_when_no_eligible_pre_observation_snapshot(admin_engine) -> None:
    """FSR-09: with no snapshot at or before ``entered_at`` (only a future
    one exists), the momentum feature is honestly missing (``None``) --
    never future-filled from the only snapshot that happens to exist."""
    config, engine, sessionmaker = _sessionmaker()
    try:
        entered_at = _NOW
        mint = _unique_mint()
        async with sessionmaker() as session, session.begin():
            token_id = await _seed_token(session, mint=mint, at=entered_at - timedelta(hours=2))
            await _seed_snapshot(
                session,
                token_id=token_id,
                at=entered_at + timedelta(seconds=1),
                price_usd=Decimal(999),
            )
            token = await session.get(Token, token_id)

        async with sessionmaker() as session:
            raw = await compute_raw_features(
                session,
                wallet_id=uuid.uuid4(),
                token_id=token_id,
                entered_at=entered_at,
                token_by_id={token_id: token},
                fingerprints_by_wallet={},
                discovery_effect_size_by_wallet={},
                max_staleness_seconds=timedelta(hours=2).total_seconds(),
                momentum_window=timedelta(hours=1),
            )
        assert raw.token_momentum_pct is None
    finally:
        await engine.dispose()


async def test_discovery_effect_size_is_scoped_to_its_own_as_of_cutoff(admin_engine) -> None:
    """FSR-09: ``load_discovery_effect_size_by_wallet`` (the primitive
    ``argus.prediction.service`` now invokes once per DISTINCT observation
    decision time) must return a wallet's score exactly AS OF the cutoff
    it is queried with -- a LATER score for the same wallet must never
    bleed into an EARLIER decision time's result (mutation invariance)."""
    config, engine, sessionmaker = _sessionmaker()
    try:
        wallet_address = _unique_wallet()
        early = _NOW
        late = _NOW + timedelta(hours=1)
        async with sessionmaker() as session, session.begin():
            wallet_id = await _seed_wallet(session, address=wallet_address, at=_NOW)
            session.add(
                WalletSpecialistScore(
                    score_id=uuid.uuid4(),
                    wallet_id=wallet_id,
                    as_of=early,
                    entry_specialist_score=None,
                    entry_specialist_sample_size=0,
                    discovery_specialist_score=Decimal("1.0"),
                    discovery_specialist_sample_size=1,
                    validation_specialist_score=None,
                    validation_specialist_sample_size=0,
                    exit_specialist_score=None,
                    entry_percentile=None,
                    discovery_percentile=None,
                    validation_percentile=None,
                    exit_percentile=None,
                    dominant_specialty=None,
                    algorithm_version="p11-fsr09-test",
                    config_hash="p11-fsr09-test-config",
                    created_at=_NOW,
                )
            )
            session.add(
                WalletSpecialistScore(
                    score_id=uuid.uuid4(),
                    wallet_id=wallet_id,
                    as_of=late,
                    entry_specialist_score=None,
                    entry_specialist_sample_size=0,
                    discovery_specialist_score=Decimal("9.0"),
                    discovery_specialist_sample_size=1,
                    validation_specialist_score=None,
                    validation_specialist_sample_size=0,
                    exit_specialist_score=None,
                    entry_percentile=None,
                    discovery_percentile=None,
                    validation_percentile=None,
                    exit_percentile=None,
                    dominant_specialty=None,
                    algorithm_version="p11-fsr09-test",
                    config_hash="p11-fsr09-test-config",
                    created_at=_NOW,
                )
            )

        async with sessionmaker() as session:
            early_map = await load_discovery_effect_size_by_wallet(
                session,
                cutoff=early,
                algorithm_version="p11-fsr09-test",
                config_hash="p11-fsr09-test-config",
            )
            late_map = await load_discovery_effect_size_by_wallet(
                session,
                cutoff=late,
                algorithm_version="p11-fsr09-test",
                config_hash="p11-fsr09-test-config",
            )
        assert early_map[wallet_id] == Decimal("1.0")
        assert late_map[wallet_id] == Decimal("9.0")
    finally:
        await engine.dispose()


def test_cli_predict_report_runs(admin_engine) -> None:
    result = runner.invoke(
        app, ["predict", "report", "--as-of", (_NOW + timedelta(days=1)).isoformat()]
    )
    assert result.exit_code == 0, result.output
    assert "horizons" in result.output
    assert '"algorithm_version": "order_flow_prediction_v1"' in result.output

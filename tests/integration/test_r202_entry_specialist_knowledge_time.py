"""Clarification-002 section 3 (``argus-final-spec-recovery-002-
clarification-002``): the ENTRY-SPECIALIST market-evidence path's own
knowledge-time provenance. The prior mutation test
(``tests/integration/test_r202_specialist_knowledge_time.py::
test_full_mutation_end_to_end_knowledge_time_provenance``) only ever
exercised the EXIT dimension (``wallet_score_snapshots`` ->
``load_latest_exit_skill``) -- it never proved anything about
``TokenMarketSnapshot``-sourced entry-specialist evidence, which is a
structurally different path (``_compute_and_persist_counterfactual_alpha``
-> ``_forward_return_for_token``/``_token_features_at`` ->
``load_nearest_token_market_snapshot``/``load_token_market_snapshot_at_or_
before``). This file closes that one hole, without touching the existing
exit-dimension test.

Before this round's fix, ``_compute_and_persist_counterfactual_alpha``
forwarded ``CounterfactualAlphaEstimate.created_at`` (a DERIVED row's own
physical write time) into ``WalletSpecialistScore.source_knowledge_max_at``
for the entry contribution, and ``load_nearest_token_market_snapshot``
enforced no ``created_at``/``observed_at`` upper bound at all on its
``after`` branch's -- and only an implicit one on its ``before`` branch's
``ORDER BY observed_at DESC LIMIT 1`` -- selection. A later-backfilled
``TokenMarketSnapshot`` with an economically early ``observed_at`` but a
knowledge time (``created_at``) strictly after the run's own cutoff could
therefore win the "nearest" selection and silently change a historical
entry-specialist reconstruction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from argus.config import load_config
from argus.convergence.service import ConvergenceRunConfig as Phase8RunConfig
from argus.counterfactual.service import (
    ALGORITHM_VERSION,
    Phase9RunConfig,
    _forward_return_for_token,
    compute_and_persist_phase9,
)
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.token_market_snapshots import TokenMarketSnapshot
from argus.graph.service import GraphRunConfig
from argus.prediction.loaders import load_discovery_effect_size_by_wallet
from argus.synthetic.loaders import load_specialist_scores_as_of
from tests.integration.test_phase9_counterfactual_persistence_and_report import (
    _seed_prospective_event,
    _seed_token,
    _seed_wallet,
)

pytestmark = pytest.mark.usefixtures("isolated_database")

_T0 = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_ENTERED_AT = _T0 + timedelta(hours=1)  # gives both tokens a positive, matching age at entry
_HORIZON = timedelta(minutes=5)
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
    horizons=(_HORIZON,),
    max_price_staleness=timedelta(minutes=30),
    max_control_tokens=10,
    entry_specialist_horizon=_HORIZON,
    discovery_min_observations=1,
    discovery_q_value_threshold=Decimal("0.99"),
    follower_influx_window=timedelta(minutes=30),
    exit_after_influx_window=timedelta(minutes=30),
    predation_influx_normalization_cap=Decimal(10),
    exit_convergence_window=timedelta(minutes=30),
    exit_convergence_unknown_independence_weight=Decimal("0.75"),
    min_exit_specialist_score=Decimal(70),
)


def _sessionmaker() -> tuple[AsyncEngine, async_sessionmaker]:
    config = load_config()
    info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(info.as_asyncpg_url())
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _unique_mint() -> str:
    return f"R202ENTRY{uuid.uuid4().hex[:37]}"


def _unique_wallet() -> str:
    return f"R202ENTRYW{uuid.uuid4().hex[:35]}"


async def _seed_snapshot(
    session,
    *,
    token_id: uuid.UUID,
    observed_at: datetime,
    created_at: datetime,
    price_usd: Decimal,
) -> None:
    session.add(
        TokenMarketSnapshot(
            snapshot_id=uuid.uuid4(),
            token_id=token_id,
            observed_at=observed_at,
            lifecycle_stage="AMM_POOL",
            venue="r202-entry-test",
            price_usd=price_usd,
            liquidity_usd=Decimal(5_000),
            market_cap_usd=Decimal(10_000),
            source="r202-entry-test",
            algorithm_version="r202-entry-test",
            build_hash="r202-entry-test-build",
            created_at=created_at,
        )
    )
    await session.flush()


async def test_entry_specialist_market_evidence_mutation_end_to_end(
    admin_engine: AsyncEngine,
) -> None:
    """The exact 7-step mutation proof Clarification-002 section 3 requires,
    targeting the entry-specialist / counterfactual-alpha market-evidence
    path specifically:

    1. Seed E1 (a ``TokenMarketSnapshot``) known by T, sufficient to
       produce an entry-specialist result (a matched control token with an
       identical entry-time bucket, and both tokens' forward-return prices).
    2. Reconstruct Phase 9 at T.
    3. Capture the Phase 10 specialist decision input
       (``load_specialist_scores_as_of``) and the Phase 11 specialist-
       derived feature (``load_discovery_effect_size_by_wallet``) at T.
    4. Append E2: an ADDITIONAL snapshot for the SAME wallet token, whose
       ``observed_at`` lands exactly on the forward-return horizon target
       (closer than E1's, so it would WIN ``load_nearest_token_market_
       snapshot``'s selection if leaked) but whose ``created_at`` is
       strictly after T, carrying a price that would double the wallet's
       forward return if it leaked.
    5. Rebuild Phase 9 at T again, under a fresh ``computed_at``.
    6. Prove the T decision input/feature are semantically unchanged --
       E2 must never leak into T's own reconstruction.
    7. Move the cutoff past E2's own knowledge time and prove E2 can THEN
       legitimately affect the reconstruction.
    """
    engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            wallet_id = await _seed_wallet(session, address=_unique_wallet(), at=_T0)

            wallet_token_mint = _unique_mint()
            wallet_token_id = await _seed_token(session, mint=wallet_token_mint, at=_T0)
            control_token_mint = _unique_mint()
            control_token_id = await _seed_token(session, mint=control_token_mint, at=_T0)

            # Step 1: E1 -- both tokens share an identical entry-time bucket
            # (same market_cap/liquidity/venue, same first_observed_at ->
            # same age), so the control is genuinely matched. The wallet
            # token gains 10% by the horizon (E1); the control is flat.
            for token_id in (wallet_token_id, control_token_id):
                await _seed_snapshot(
                    session,
                    token_id=token_id,
                    observed_at=_ENTERED_AT,
                    created_at=_ENTERED_AT,
                    price_usd=Decimal(100),
                )
            e1_observed_at = _ENTERED_AT + _HORIZON - timedelta(seconds=30)
            await _seed_snapshot(
                session,
                token_id=wallet_token_id,
                observed_at=e1_observed_at,
                created_at=_ENTERED_AT,
                price_usd=Decimal(110),
            )
            await _seed_snapshot(
                session,
                token_id=control_token_id,
                observed_at=e1_observed_at,
                created_at=_ENTERED_AT,
                price_usd=Decimal(100),
            )

            await _seed_prospective_event(
                session,
                wallet_id=wallet_id,
                token_id=wallet_token_id,
                output_mint=wallet_token_mint,
                entered_at=_ENTERED_AT,
            )

        t = _ENTERED_AT + timedelta(minutes=10)

        # Step 2: reconstruct Phase 9 at T.
        async with sessionmaker() as session, session.begin():
            result = await compute_and_persist_phase9(
                session,
                cutoff=t,
                graph_config=_GRAPH_CONFIG,
                phase8_config=_PHASE8_CONFIG,
                config=_CONFIG,
                computed_at=_ENTERED_AT,
            )
        assert result.alpha_estimate_count >= 1

        # Step 3: capture the Phase 10 decision input and Phase 11 feature
        # at T, before E2 exists at all.
        async with sessionmaker() as session:
            baseline_rows = await load_specialist_scores_as_of(
                session,
                decision_time=t,
                algorithm_version=ALGORITHM_VERSION,
                config_hash=_CONFIG.config_hash(),
            )
            baseline_row = next(r for r in baseline_rows if r.wallet_id == wallet_id)
            assert baseline_row.entry_specialist_score == Decimal("0.10")
            assert baseline_row.entry_specialist_sample_size == 1
            assert baseline_row.source_knowledge_max_at == _ENTERED_AT

            baseline_phase11 = await load_discovery_effect_size_by_wallet(
                session,
                cutoff=t,
                algorithm_version=ALGORITHM_VERSION,
                config_hash=_CONFIG.config_hash(),
            )
            # No DirectionalEdge evidence exists for this wallet at all --
            # this mutation is scoped to the ENTRY dimension only, so the
            # Phase 11 discovery-effect-size feature stays absent
            # throughout. Captured here as the required Phase 11
            # specialist-derived-feature read, proving it is never
            # cross-contaminated by an entry-only mutation either.
            assert wallet_id not in baseline_phase11

        # Step 4: append E2 -- an additional wallet-token snapshot whose
        # observed_at lands exactly on the horizon target (closer than
        # E1's), but whose created_at is strictly after T.
        e2_created_at = t + timedelta(hours=2)
        async with sessionmaker() as session, session.begin():
            await _seed_snapshot(
                session,
                token_id=wallet_token_id,
                observed_at=_ENTERED_AT + _HORIZON,
                created_at=e2_created_at,
                price_usd=Decimal(200),
            )

        # Step 5: rebuild Phase 9 at T again, fresh computed_at -- proves no
        # reliance on any cached prior state.
        computed_at_2 = _ENTERED_AT + timedelta(seconds=1)
        async with sessionmaker() as session, session.begin():
            await compute_and_persist_phase9(
                session,
                cutoff=t,
                graph_config=_GRAPH_CONFIG,
                phase8_config=_PHASE8_CONFIG,
                config=_CONFIG,
                computed_at=computed_at_2,
            )

        # Step 6: T's own decision input/feature must remain semantically
        # identical -- E2 must never leak into T's reconstruction despite
        # now existing in the database.
        async with sessionmaker() as session:
            rebuilt_rows = await load_specialist_scores_as_of(
                session,
                decision_time=t,
                algorithm_version=ALGORITHM_VERSION,
                config_hash=_CONFIG.config_hash(),
            )
            rebuilt_row = next(r for r in rebuilt_rows if r.wallet_id == wallet_id)
            assert rebuilt_row.entry_specialist_score == Decimal("0.10")
            assert rebuilt_row.entry_specialist_sample_size == 1
            assert rebuilt_row.source_knowledge_max_at == _ENTERED_AT

            rebuilt_phase11 = await load_discovery_effect_size_by_wallet(
                session,
                cutoff=t,
                algorithm_version=ALGORITHM_VERSION,
                config_hash=_CONFIG.config_hash(),
            )
            assert wallet_id not in rebuilt_phase11

            # ``get_or_create_wallet_specialist_score`` is a true get-or-
            # create: once a row exists for (wallet_id, as_of, algorithm_
            # version, config_hash) a rebuild at that SAME identity always
            # returns the existing row untouched, regardless of what the
            # underlying query would now compute -- so the persisted-row
            # comparisons above hold trivially and are a consistency check,
            # not the regression proof. The genuine, unpersisted proof --
            # mirroring ``load_latest_exit_skill``'s role in the sibling
            # exit-dimension mutation test -- is calling the actual
            # forward-return computation directly: it must still resolve
            # to E1 (0.10), never E2, when asked "as of T" even now that
            # E2 physically exists in the table.
            live_forward_return = await _forward_return_for_token(
                session,
                token_id=wallet_token_id,
                entered_at=_ENTERED_AT,
                horizon=_HORIZON,
                config=_CONFIG,
                cutoff=t,
            )
            assert live_forward_return is not None
            assert live_forward_return[0] == Decimal("0.10")
            assert live_forward_return[1] == _ENTERED_AT

        # Step 7: move the cutoff forward past E2's own knowledge time --
        # it can NOW legitimately affect the result.
        t2 = _ENTERED_AT + timedelta(hours=3)
        assert t2 > e2_created_at
        async with sessionmaker() as session, session.begin():
            await compute_and_persist_phase9(
                session,
                cutoff=t2,
                graph_config=_GRAPH_CONFIG,
                phase8_config=_PHASE8_CONFIG,
                config=_CONFIG,
                computed_at=computed_at_2,
            )

        async with sessionmaker() as session:
            t2_rows = await load_specialist_scores_as_of(
                session,
                decision_time=t2,
                algorithm_version=ALGORITHM_VERSION,
                config_hash=_CONFIG.config_hash(),
            )
            t2_row = next(r for r in t2_rows if r.wallet_id == wallet_id)
            # 200/100 - 1 = 1.00, versus the control's flat 0.0 -- the
            # residual materially changed from the baseline 0.10. This IS
            # a genuine proof (unlike step 6's row comparison): (wallet_id,
            # as_of=t2, ...) is a BRAND NEW identity, never persisted
            # before, so this row reflects a real fresh computation.
            assert t2_row.entry_specialist_score == Decimal("1.00")
            assert t2_row.entry_specialist_sample_size == 1
            assert t2_row.source_knowledge_max_at == e2_created_at

            live_forward_return_t2 = await _forward_return_for_token(
                session,
                token_id=wallet_token_id,
                entered_at=_ENTERED_AT,
                horizon=_HORIZON,
                config=_CONFIG,
                cutoff=t2,
            )
            assert live_forward_return_t2 is not None
            assert live_forward_return_t2[0] == Decimal("1.00")
            assert live_forward_return_t2[1] == e2_created_at
    finally:
        await engine.dispose()


async def test_entry_specialist_nearest_snapshot_ignores_future_knowledge_row_directly(
    admin_engine: AsyncEngine,
) -> None:
    """A narrower, more direct proof of the same loader-level fix: a
    ``TokenMarketSnapshot`` whose ``observed_at`` would win ``load_nearest_
    token_market_snapshot``'s selection, but whose ``created_at`` is after
    the query's own ``cutoff``, must never be returned -- and once cutoff
    moves past it, it must be."""
    from argus.counterfactual.loaders import load_nearest_token_market_snapshot

    engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            token_id = await _seed_token(session, mint=_unique_mint(), at=_T0)
            target = _ENTERED_AT
            older_observed_at = target - timedelta(minutes=1)
            await _seed_snapshot(
                session,
                token_id=token_id,
                observed_at=older_observed_at,
                created_at=older_observed_at,
                price_usd=Decimal(100),
            )
            # This row's observed_at is EXACTLY at the target -- it would
            # win the nearest-selection over the older row above -- but its
            # created_at is deliberately set after the test's own cutoff.
            future_knowledge_created_at = target + timedelta(hours=1)
            await _seed_snapshot(
                session,
                token_id=token_id,
                observed_at=target,
                created_at=future_knowledge_created_at,
                price_usd=Decimal(999),
            )

        async with sessionmaker() as session:
            excluded = await load_nearest_token_market_snapshot(
                session,
                token_id=token_id,
                target=target,
                max_staleness_seconds=3600,
                cutoff=target,
            )
            assert excluded is not None
            assert excluded.observed_at == older_observed_at
            assert excluded.price_usd == Decimal(100)

            included = await load_nearest_token_market_snapshot(
                session,
                token_id=token_id,
                target=target,
                max_staleness_seconds=3600,
                cutoff=future_knowledge_created_at,
            )
            assert included is not None
            assert included.observed_at == target
            assert included.price_usd == Decimal(999)
    finally:
        await engine.dispose()

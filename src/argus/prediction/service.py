"""argus.prediction.service -- MASTER_SPEC.md Phase 11 (PREDICT INFORMED
ORDER FLOW) orchestration: builds the labeled observation population from
Phase 7's own tracked-wallet entries and Phase 3's wallet-tier history,
computes Phase 9's own full evidence cascade first (reusing
``compute_and_persist_phase9`` unchanged -- itself cascading through Phase
8's convergence evidence and Phase 7's directional edges) for the
discovery-specialist graph feature, then fits and evaluates all 7 named
model families per horizon under strict temporal (never random)
validation, persisting one row per (horizon, model family). This is the
one place Phase 11's models are assembled -- ``argus predict report`` (the
CLI command) calls this.

"Only begin with adequate clean prospective sample" -- a (horizon, model
family) combination whose feature-filtered, temporally-split train/test
population does not meet the configured minimum class-balance gate is
recorded honestly as ``INSUFFICIENT_SAMPLE`` with every metric ``NULL``,
never a number trained on too little (or single-class) data.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from argus.convergence.service import ConvergenceRunConfig as Phase8RunConfig
from argus.counterfactual.service import ALGORITHM_VERSION as PHASE9_ALGORITHM_VERSION
from argus.counterfactual.service import Phase9RunConfig, compute_and_persist_phase9
from argus.domain.order_flow_prediction_runs import (
    MODEL_BASELINE_GRAPH_TOKEN_STATE,
    MODEL_BASELINE_RANDOM,
    MODEL_BASELINE_TOKEN_MOMENTUM,
    MODEL_BASELINE_WALLET_HISTORY,
    MODEL_FAMILIES,
    MODEL_GRADIENT_BOOSTED_TREES,
    MODEL_LOGISTIC_REGRESSION,
    MODEL_REGULARIZED_LOGISTIC_REGRESSION,
    STATUS_EVALUATED,
    STATUS_INSUFFICIENT_SAMPLE,
)
from argus.domain.tokens import Token
from argus.graph.service import GraphRunConfig
from argus.prediction.elite import ELITE_TIERS
from argus.prediction.evaluation import evaluate_predictions
from argus.prediction.features import (
    FEATURES_FULL,
    FEATURES_GRAPH_TOKEN_STATE,
    FEATURES_TOKEN_MOMENTUM,
    FEATURES_WALLET_HISTORY,
    build_feature_dict,
    select_features,
)
from argus.prediction.labels import LabeledObservation, build_labeled_observations
from argus.prediction.loaders import (
    compute_raw_features,
    load_discovery_effect_size_by_wallet,
    load_tiered_entries,
    load_wallet_fingerprints,
)
from argus.prediction.models import (
    fit_predict_gradient_boosted_trees,
    fit_predict_logistic_regression,
    predict_base_rate,
)
from argus.prediction.persistence import get_or_create_order_flow_prediction_run
from argus.prediction.validation import has_adequate_sample, purged_embargoed_split

# FSR-13: bumped from "order_flow_prediction_v1" -- FSR-09/10/11 fixed
# real feature/label leakage and validation-split contamination, so any
# row persisted under the old version is contaminated and must never be
# silently presented as a current result (see
# ``contaminated_run_invalidations``).
#
# R2-02 (``argus-final-spec-recovery-002``): bumped from
# "order_flow_prediction_v2" -- this phase's own ``wallet_discovery_
# effect_size`` feature is read straight from Phase 9's
# ``WalletSpecialistScore.discovery_specialist_score`` via
# ``load_discovery_effect_size_by_wallet`` (imported as
# ``PHASE9_ALGORITHM_VERSION`` from ``argus.counterfactual.service``,
# which is itself now "counterfactual_alpha_v3"); every historical
# feature value computed under the OLD Phase 9 version could have been
# silently built from source evidence recorded after its own decision
# time (the fix described there). No code in THIS module changed, but
# its own output is different and must never be conflated with a
# "order_flow_prediction_v2" row computed against the leaky Phase 9
# input; every such row is invalidated by
# ``contaminated_run_invalidations``.
ALGORITHM_VERSION: Final[str] = "order_flow_prediction_v3"

_PHASE11_ARTIFACT_FILENAMES: Final[tuple[str, ...]] = (
    "elite.py",
    "labels.py",
    "features.py",
    "validation.py",
    "evaluation.py",
    "models.py",
    "loaders.py",
    "persistence.py",
    "service.py",
)


def _compute_build_hash() -> str:
    digest = hashlib.sha256()
    module_dir = Path(__file__).parent
    for filename in _PHASE11_ARTIFACT_FILENAMES:
        digest.update((module_dir / filename).read_bytes())
    return digest.hexdigest()


BUILD_HASH: Final[str] = _compute_build_hash()

# The three single-feature-set baselines PHASE 11 names all use
# unregularized logistic regression on their own named feature subset --
# these are baselines FOR FEATURE VALUE (does this group of signals alone
# predict anything), not a second, competing regularization scheme; the
# "logistic regression" / "regularized models" contrast is reserved for
# the two full-feature-set MODEL_FAMILIES entries below.
_MODEL_FEATURE_SETS: Final[dict[str, tuple[str, ...]]] = {
    MODEL_BASELINE_TOKEN_MOMENTUM: FEATURES_TOKEN_MOMENTUM,
    MODEL_BASELINE_WALLET_HISTORY: FEATURES_WALLET_HISTORY,
    MODEL_BASELINE_GRAPH_TOKEN_STATE: FEATURES_GRAPH_TOKEN_STATE,
    MODEL_LOGISTIC_REGRESSION: FEATURES_FULL,
    MODEL_REGULARIZED_LOGISTIC_REGRESSION: FEATURES_FULL,
    MODEL_GRADIENT_BOOSTED_TREES: FEATURES_FULL,
}


@dataclass(frozen=True)
class Phase11RunConfig:
    horizons: tuple[timedelta, ...]
    train_fraction: Decimal
    min_class_count: int
    max_price_staleness: timedelta
    token_momentum_window: timedelta
    classification_threshold: Decimal

    def config_hash(self) -> str:
        payload = (
            f"horizons_seconds={[h.total_seconds() for h in self.horizons]}|"
            f"train_fraction={self.train_fraction}|"
            f"min_class_count={self.min_class_count}|"
            f"max_price_staleness_seconds={self.max_price_staleness.total_seconds()}|"
            f"token_momentum_window_seconds={self.token_momentum_window.total_seconds()}|"
            f"classification_threshold={self.classification_threshold}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Phase11ComputationResult:
    as_of: datetime
    run_count: int = 0
    evaluated_count: int = 0
    insufficient_sample_count: int = 0


def _positive_rate(values: list[bool]) -> Decimal | None:
    if not values:
        return None
    return Decimal(sum(1 for v in values if v)) / Decimal(len(values))


async def _persist_insufficient_sample(
    session: AsyncSession,
    *,
    horizon_seconds: int,
    model_family: str,
    feature_set: tuple[str, ...],
    y_train: list[bool],
    y_test: list[bool],
    split_boundary: datetime | None,
    embargo: timedelta | None,
    purged_count: int,
    train_range: tuple[datetime, datetime] | None,
    test_range: tuple[datetime, datetime] | None,
    cutoff: datetime,
    config_hash: str,
    computed_at: datetime,
) -> None:
    await get_or_create_order_flow_prediction_run(
        session,
        horizon_seconds=horizon_seconds,
        model_family=model_family,
        status=STATUS_INSUFFICIENT_SAMPLE,
        train_sample_size=len(y_train),
        test_sample_size=len(y_test),
        positive_rate_train=_positive_rate(y_train),
        positive_rate_test=_positive_rate(y_test),
        auc_roc=None,
        log_loss=None,
        brier_score=None,
        accuracy_at_threshold=None,
        feature_set=list(feature_set),
        split_boundary=split_boundary,
        embargo=embargo,
        purged_count=purged_count,
        train_range=train_range,
        test_range=test_range,
        as_of=cutoff,
        algorithm_version=ALGORITHM_VERSION,
        config_hash=config_hash,
        now=computed_at,
    )


async def _run_model_family(
    session: AsyncSession,
    *,
    model_family: str,
    horizon_seconds: int,
    observations: list[LabeledObservation],
    feature_dicts: dict[tuple[uuid.UUID, uuid.UUID, datetime], dict[str, float | None]],
    cutoff: datetime,
    config: Phase11RunConfig,
    computed_at: datetime,
) -> str:
    config_hash = config.config_hash()
    horizon = timedelta(seconds=horizon_seconds)

    # FSR-10: an observation whose label at THIS horizon is right-censored
    # (``None`` -- the label window is not yet fully observable as of
    # cutoff) is excluded from this horizon's population entirely, never
    # coerced to False.
    if model_family == MODEL_BASELINE_RANDOM:
        feature_set: tuple[str, ...] = ()
        rows: list[tuple[LabeledObservation, list[float], bool]] = [
            (obs, [], label)
            for obs in observations
            if (label := obs.labels[horizon_seconds]) is not None
        ]
    else:
        feature_set = _MODEL_FEATURE_SETS[model_family]
        rows = []
        for obs in observations:
            label = obs.labels[horizon_seconds]
            if label is None:
                continue
            feature_dict = feature_dicts.get((obs.wallet_id, obs.token_id, obs.entered_at))
            if feature_dict is None:
                continue
            selected = select_features(feature_dict, feature_set)
            if selected is None:
                continue
            rows.append((obs, selected, label))

    if not rows:
        await _persist_insufficient_sample(
            session,
            horizon_seconds=horizon_seconds,
            model_family=model_family,
            feature_set=feature_set,
            y_train=[],
            y_test=[],
            split_boundary=None,
            embargo=None,
            purged_count=0,
            train_range=None,
            test_range=None,
            cutoff=cutoff,
            config_hash=config_hash,
            computed_at=computed_at,
        )
        return STATUS_INSUFFICIENT_SAMPLE

    # FSR-11: a deterministic purged + embargoed split, never a plain
    # chronological one -- a row whose own complete label window crosses
    # the boundary is purged from training, and the earliest test row is
    # held back by at least this horizon's own length past the boundary.
    timestamps = [obs.entered_at for obs, _, _ in rows]
    split = purged_embargoed_split(
        timestamps, horizon=horizon, train_fraction=config.train_fraction
    )

    y_all = [label for _, _, label in rows]
    x_all = [features for _, features, _ in rows]

    y_train = [y_all[i] for i in split.train_indices]
    y_test = [y_all[i] for i in split.test_indices]
    x_train = [x_all[i] for i in split.train_indices]
    x_test = [x_all[i] for i in split.test_indices]

    if not has_adequate_sample(y_train, y_test, min_class_count=config.min_class_count):
        await _persist_insufficient_sample(
            session,
            horizon_seconds=horizon_seconds,
            model_family=model_family,
            feature_set=feature_set,
            y_train=y_train,
            y_test=y_test,
            split_boundary=split.boundary,
            embargo=split.embargo,
            purged_count=split.purged_count,
            train_range=split.train_range,
            test_range=split.test_range,
            cutoff=cutoff,
            config_hash=config_hash,
            computed_at=computed_at,
        )
        return STATUS_INSUFFICIENT_SAMPLE

    if model_family == MODEL_BASELINE_RANDOM:
        y_score = predict_base_rate(y_train, len(y_test))
    elif model_family == MODEL_LOGISTIC_REGRESSION:
        y_score = fit_predict_logistic_regression(x_train, y_train, x_test, regularized=False)
    elif model_family == MODEL_REGULARIZED_LOGISTIC_REGRESSION:
        y_score = fit_predict_logistic_regression(x_train, y_train, x_test, regularized=True)
    elif model_family == MODEL_GRADIENT_BOOSTED_TREES:
        y_score = fit_predict_gradient_boosted_trees(x_train, y_train, x_test)
    else:
        y_score = fit_predict_logistic_regression(x_train, y_train, x_test, regularized=False)

    metrics = evaluate_predictions(y_test, y_score, threshold=config.classification_threshold)

    await get_or_create_order_flow_prediction_run(
        session,
        horizon_seconds=horizon_seconds,
        model_family=model_family,
        status=STATUS_EVALUATED,
        train_sample_size=len(y_train),
        test_sample_size=len(y_test),
        positive_rate_train=_positive_rate(y_train),
        positive_rate_test=_positive_rate(y_test),
        auc_roc=metrics.auc_roc,
        log_loss=metrics.log_loss,
        brier_score=metrics.brier_score,
        accuracy_at_threshold=metrics.accuracy_at_threshold,
        feature_set=list(feature_set),
        split_boundary=split.boundary,
        embargo=split.embargo,
        purged_count=split.purged_count,
        train_range=split.train_range,
        test_range=split.test_range,
        as_of=cutoff,
        algorithm_version=ALGORITHM_VERSION,
        config_hash=config_hash,
        now=computed_at,
    )
    return STATUS_EVALUATED


async def compute_and_persist_phase11(
    session: AsyncSession,
    *,
    cutoff: datetime,
    graph_config: GraphRunConfig,
    phase8_config: Phase8RunConfig,
    phase9_config: Phase9RunConfig,
    config: Phase11RunConfig,
    computed_at: datetime,
) -> Phase11ComputationResult:
    await compute_and_persist_phase9(
        session,
        cutoff=cutoff,
        graph_config=graph_config,
        phase8_config=phase8_config,
        config=phase9_config,
        computed_at=computed_at,
    )

    tiered_entries = await load_tiered_entries(session, cutoff=cutoff)
    observations = build_labeled_observations(
        tiered_entries, horizons=config.horizons, elite_tiers=ELITE_TIERS, cutoff=cutoff
    )

    token_ids = {o.token_id for o in observations}
    tokens = (
        (await session.execute(select(Token).where(Token.token_id.in_(token_ids)))).scalars().all()
        if token_ids
        else []
    )
    token_by_id = {t.token_id: t for t in tokens}

    wallet_ids = {o.wallet_id for o in observations}
    fingerprints_by_wallet = await load_wallet_fingerprints(session, wallet_ids=wallet_ids)

    # FSR-09: the discovery-specialist graph feature must be each
    # observation's own AS-OF value known AT ITS OWN ``entered_at``, never
    # a value computed once at the final run cutoff and reused backward.
    # Phase 9 only ever persists one snapshot per cutoff it is invoked
    # with, so every DISTINCT decision time actually needed here is
    # recomputed through Phase 9's own idempotent cascade (the same
    # disclosed O(distinct decision times) pattern FSR-08 established for
    # ``argus.synthetic.service``) and then queried back.
    phase9_config_hash = phase9_config.config_hash()
    decision_times = {o.entered_at for o in observations}
    discovery_effect_size_by_time: dict[datetime, dict[uuid.UUID, Decimal]] = {}
    for decision_time in decision_times:
        if decision_time != cutoff:
            await compute_and_persist_phase9(
                session,
                cutoff=decision_time,
                graph_config=graph_config,
                phase8_config=phase8_config,
                config=phase9_config,
                computed_at=computed_at,
            )
        discovery_effect_size_by_time[decision_time] = await load_discovery_effect_size_by_wallet(
            session,
            cutoff=decision_time,
            algorithm_version=PHASE9_ALGORITHM_VERSION,
            config_hash=phase9_config_hash,
        )

    max_staleness_seconds = config.max_price_staleness.total_seconds()
    feature_dicts: dict[tuple[uuid.UUID, uuid.UUID, datetime], dict[str, float | None]] = {}
    for obs in observations:
        discovery_effect_size_by_wallet = discovery_effect_size_by_time.get(obs.entered_at, {})
        raw = await compute_raw_features(
            session,
            wallet_id=obs.wallet_id,
            token_id=obs.token_id,
            entered_at=obs.entered_at,
            token_by_id=token_by_id,
            fingerprints_by_wallet=fingerprints_by_wallet,
            discovery_effect_size_by_wallet=discovery_effect_size_by_wallet,
            max_staleness_seconds=max_staleness_seconds,
            momentum_window=config.token_momentum_window,
        )
        feature_dicts[(obs.wallet_id, obs.token_id, obs.entered_at)] = build_feature_dict(raw)

    run_count = 0
    evaluated_count = 0
    insufficient_count = 0
    for horizon in config.horizons:
        horizon_seconds = int(horizon.total_seconds())
        for model_family in MODEL_FAMILIES:
            status = await _run_model_family(
                session,
                model_family=model_family,
                horizon_seconds=horizon_seconds,
                observations=observations,
                feature_dicts=feature_dicts,
                cutoff=cutoff,
                config=config,
                computed_at=computed_at,
            )
            run_count += 1
            if status == STATUS_EVALUATED:
                evaluated_count += 1
            else:
                insufficient_count += 1

    return Phase11ComputationResult(
        as_of=cutoff,
        run_count=run_count,
        evaluated_count=evaluated_count,
        insufficient_sample_count=insufficient_count,
    )

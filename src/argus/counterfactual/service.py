"""argus.counterfactual.service -- MASTER_SPEC.md Phase 9 (COUNTERFACTUAL
ALPHA + SPECIALISTS) orchestration: ties together counterfactual alpha
(section 55), entry/discovery/validation/exit specialist scoring
(section 62), predation detection (section 61), and exit convergence
(section 63) into one computation run, persisted idempotently. This is
the one place Phase 9's analytics are assembled -- ``argus counterfactual
report`` (the CLI command) calls this.

Computes Phase 8's own convergence/confirmation evidence first (reusing
``argus.convergence.service.compute_and_persist_phase8`` unchanged --
idempotent, and itself computes Phase 7's directional edges), since
discovery/validation specialist scores and predation's follower-influx
figure are all defined in terms of that already-persisted evidence --
the pipeline this mirrors is MASTER_SPEC's own "Alpha Ancestry ->
Convergence Surprise -> entry/exit specialists" ordering.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from argus.convergence.episodes import build_convergence_episodes
from argus.convergence.independence import (
    compute_independence_weights,
    estimated_independent_actors,
)
from argus.convergence.loaders import load_cluster_links_within_group
from argus.convergence.service import ConvergenceRunConfig as Phase8RunConfig
from argus.convergence.service import compute_and_persist_phase8
from argus.convergence.stats import compute_overlap_surprise
from argus.copyability.loaders import (
    WalletOpportunity,
    load_contamination_firewall,
    load_wallet_opportunities,
)
from argus.counterfactual.buckets import liquidity_bucket, market_cap_bucket, token_age_bucket
from argus.counterfactual.loaders import (
    load_candidate_tokens,
    load_latest_exit_skill,
    load_nearest_token_market_snapshot,
    load_token_market_snapshot_at_or_before,
    load_wallet_token_exits,
)
from argus.counterfactual.matching import (
    TokenFeatures,
    compute_forward_return,
    select_matched_control_tokens,
)
from argus.counterfactual.matching import (
    residual_selection_alpha as compute_residual_selection_alpha,
)
from argus.counterfactual.persistence import (
    get_or_create_counterfactual_alpha_estimate,
    get_or_create_exit_convergence_event,
    get_or_create_wallet_predation_score,
    get_or_create_wallet_specialist_score,
)
from argus.counterfactual.predation import compute_predation_score
from argus.counterfactual.specialists import dominant_specialty, percentile_rank
from argus.domain.directional_edges import DirectionalEdge
from argus.domain.expected_confirmation_events import ExpectedConfirmationEvent
from argus.domain.lead_follow_observations import LeadFollowObservation
from argus.domain.tokens import Token
from argus.domain.wallet_specialist_scores import WalletSpecialistScore
from argus.graph.lead_follow import WalletTokenEntry
from argus.graph.loaders import load_wallet_token_entries
from argus.graph.service import ALGORITHM_VERSION as GRAPH_ALGORITHM_VERSION
from argus.graph.service import GraphRunConfig

# R2-02 clarification-002: bumped from "counterfactual_alpha_v4" -- the
# entry-specialist contribution folded into
# WalletSpecialistScore.source_knowledge_max_at previously used
# CounterfactualAlphaEstimate.created_at (the physical creation time of a
# DERIVED row written during this very replay), not the actual maximum
# knowledge time of the TokenMarketSnapshot source rows used to compute
# the residual. The two Phase 9 market-state loaders
# (load_token_market_snapshot_at_or_before / load_nearest_token_market_
# snapshot) also gained an explicit created_at<=cutoff (and
# observed_at<=cutoff) bound -- previously unenforced, so a
# later-backfilled snapshot with an old observed_at could silently
# contaminate a historical reconstruction. No schema change is required
# (source_knowledge_max_at already exists, migration 0041) and no durable
# v4 row was ever computed against a real (non-disposable-test) database
# this session, so nothing requires a contaminated_run_invalidations
# entry -- this bump reflects a genuine algorithm change, not a
# contaminated-result correction.
ALGORITHM_VERSION: Final[str] = "counterfactual_alpha_v5"
"""FSR-07/FSR-13 (final spec recovery): renamed from
``counterfactual_alpha_specialists_v1`` -- besides versioning the
predation-score algorithm change below, the original name (36 chars)
never actually fit the real ``algorithm_version`` columns (``VARCHAR(32)``
on every Phase 9 table), so every Phase 9 persistence write failed
under a real role-enforced Postgres. ``_v2`` both fixes that and gives
the changed algorithm its own honest identity per FSR-13.

``_v3`` (R2-02, ``argus-final-spec-recovery-002``): the discovery- and
validation-specialist queries in ``_compute_and_persist_specialist_scores``
below previously filtered contributing ``DirectionalEdge``/
``ExpectedConfirmationEvent`` rows by ``as_of == cutoff`` alone --
``known_by_cutoff`` (M1) also requires ``created_at <= cutoff``, which was
missing, letting a specialist score labeled ``as_of=T`` be silently built
from source evidence only recorded (i.e. only knowable) AFTER T. Every
``counterfactual_alpha_v2`` row is invalidated by
``contaminated_run_invalidations`` (migration ``0038``) for this reason.

``_v4`` (R2-02 clarification-001): ``WalletSpecialistScore`` gained
persisted ``source_knowledge_max_at`` provenance; ``load_latest_exit_
skill`` gained the same ``created_at<=cutoff`` bound.

``_v5`` (R2-02 clarification-002): the entry-specialist contribution
folded into ``source_knowledge_max_at`` previously used
``CounterfactualAlphaEstimate.created_at`` -- a derived row's own
physical write time, not the real source evidence's knowledge time.
``_token_features_at``/``_forward_return_for_token`` now return the
actual ``TokenMarketSnapshot`` row(s) they used alongside their result,
and ``_compute_and_persist_counterfactual_alpha`` folds the MAX of those
real ``created_at`` values into each residual's entry, instead. The two
Phase 9 market-state loaders also gained an explicit
``created_at<=cutoff``/``observed_at<=cutoff`` bound they previously
lacked entirely -- ``load_nearest_token_market_snapshot``'s ``after``
branch in particular had no upper bound on either timestamp before this
fix."""

_PHASE9_ARTIFACT_FILENAMES: Final[tuple[str, ...]] = (
    "buckets.py",
    "matching.py",
    "specialists.py",
    "predation.py",
    "loaders.py",
    "persistence.py",
    "service.py",
)


def _compute_build_hash() -> str:
    digest = hashlib.sha256()
    module_dir = Path(__file__).parent
    for filename in _PHASE9_ARTIFACT_FILENAMES:
        digest.update((module_dir / filename).read_bytes())
    return digest.hexdigest()


BUILD_HASH: Final[str] = _compute_build_hash()


@dataclass(frozen=True)
class Phase9RunConfig:
    horizons: tuple[timedelta, ...]
    max_price_staleness: timedelta
    max_control_tokens: int
    entry_specialist_horizon: timedelta
    discovery_min_observations: int
    discovery_q_value_threshold: Decimal
    follower_influx_window: timedelta
    exit_after_influx_window: timedelta
    predation_influx_normalization_cap: Decimal
    exit_convergence_window: timedelta
    exit_convergence_unknown_independence_weight: Decimal
    min_exit_specialist_score: Decimal

    def config_hash(self) -> str:
        payload = (
            f"horizons_seconds={[h.total_seconds() for h in self.horizons]}|"
            f"max_price_staleness_seconds={self.max_price_staleness.total_seconds()}|"
            f"max_control_tokens={self.max_control_tokens}|"
            f"entry_specialist_horizon_seconds={self.entry_specialist_horizon.total_seconds()}|"
            f"discovery_min_observations={self.discovery_min_observations}|"
            f"discovery_q_value_threshold={self.discovery_q_value_threshold}|"
            f"follower_influx_window_seconds={self.follower_influx_window.total_seconds()}|"
            f"exit_after_influx_window_seconds={self.exit_after_influx_window.total_seconds()}|"
            f"predation_influx_normalization_cap={self.predation_influx_normalization_cap}|"
            f"exit_convergence_window_seconds={self.exit_convergence_window.total_seconds()}|"
            f"exit_convergence_unknown_independence_weight="
            f"{self.exit_convergence_unknown_independence_weight}|"
            f"min_exit_specialist_score={self.min_exit_specialist_score}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Phase9ComputationResult:
    as_of: datetime
    alpha_estimate_count: int = 0
    specialist_score_count: int = 0
    predation_score_count: int = 0
    exit_convergence_event_count: int = 0
    # R2-02 clarification-002: each entry pairs its own residual with the
    # MAX ``created_at`` among the actual ``TokenMarketSnapshot`` source
    # rows used to compute it -- never the persisted
    # ``CounterfactualAlphaEstimate`` row's own ``created_at`` (that only
    # reflects when this replay physically ran). ``_compute_and_persist_
    # specialist_scores`` folds this real source-evidence knowledge time
    # into ``WalletSpecialistScore.source_knowledge_max_at``.
    entry_alpha_by_wallet_horizon: dict[tuple[uuid.UUID, int], list[tuple[Decimal, datetime]]] = (
        field(default_factory=dict)
    )


async def _token_features_at(
    session: AsyncSession, *, token: Token, at: datetime, max_staleness: timedelta, cutoff: datetime
) -> tuple[TokenFeatures, datetime] | None:
    """Clarification-002 section 3: returns the matching-dimension
    features paired with the snapshot row's own ``created_at`` -- the
    caller needs this to fold the ACTUAL source evidence's knowledge time
    into ``source_knowledge_max_at``, never the physically-later
    ``CounterfactualAlphaEstimate.created_at`` merely because that derived
    row happened to be written during this replay."""
    snapshot = await load_token_market_snapshot_at_or_before(
        session, token_id=token.token_id, at=at, cutoff=cutoff
    )
    if snapshot is None or snapshot.market_cap_usd is None or snapshot.liquidity_usd is None:
        return None
    if (at - snapshot.observed_at) > max_staleness:
        return None
    age = at - token.first_observed_at
    if age < timedelta(0):
        return None
    return (
        TokenFeatures(
            token_id=token.token_id,
            market_cap_bucket=market_cap_bucket(snapshot.market_cap_usd),
            liquidity_bucket=liquidity_bucket(snapshot.liquidity_usd),
            token_age_bucket=token_age_bucket(age),
            launch_venue=snapshot.venue,
        ),
        snapshot.created_at,
    )


async def _forward_return_for_token(
    session: AsyncSession,
    *,
    token_id: uuid.UUID,
    entered_at: datetime,
    horizon: timedelta,
    config: Phase9RunConfig,
    cutoff: datetime,
) -> tuple[Decimal, datetime] | None:
    """Clarification-002 section 3: returns the forward return paired
    with the MAX ``created_at`` of the two ``TokenMarketSnapshot`` rows
    actually used to compute it -- the real source-evidence knowledge
    time, not any later derived row's own persistence time."""
    max_staleness_seconds = config.max_price_staleness.total_seconds()
    entry_snapshot = await load_nearest_token_market_snapshot(
        session,
        token_id=token_id,
        target=entered_at,
        max_staleness_seconds=max_staleness_seconds,
        cutoff=cutoff,
    )
    horizon_snapshot = await load_nearest_token_market_snapshot(
        session,
        token_id=token_id,
        target=entered_at + horizon,
        max_staleness_seconds=max_staleness_seconds,
        cutoff=cutoff,
    )
    if (
        entry_snapshot is None
        or horizon_snapshot is None
        or entry_snapshot.price_usd is None
        or horizon_snapshot.price_usd is None
    ):
        return None
    forward_return = compute_forward_return(entry_snapshot.price_usd, horizon_snapshot.price_usd)
    if forward_return is None:
        return None
    return forward_return, max(entry_snapshot.created_at, horizon_snapshot.created_at)


async def _compute_and_persist_counterfactual_alpha(
    session: AsyncSession,
    *,
    entries: list[WalletTokenEntry],
    tokens_by_id: dict[uuid.UUID, Token],
    candidate_tokens: list[Token],
    cutoff: datetime,
    config: Phase9RunConfig,
    computed_at: datetime,
) -> tuple[int, dict[tuple[uuid.UUID, int], list[tuple[Decimal, datetime]]]]:
    config_hash = config.config_hash()
    entry_alpha_by_wallet_horizon: dict[tuple[uuid.UUID, int], list[tuple[Decimal, datetime]]] = {}
    count = 0

    for entry in entries:
        wallet_token = tokens_by_id.get(entry.token_id)
        if wallet_token is None:
            continue
        wallet_features_result = await _token_features_at(
            session,
            token=wallet_token,
            at=entry.entered_at,
            max_staleness=config.max_price_staleness,
            cutoff=cutoff,
        )
        if wallet_features_result is None:
            continue
        wallet_features, wallet_features_created_at = wallet_features_result

        candidate_features: list[TokenFeatures] = []
        # R2-02 clarification-002: only candidates that are actually
        # SELECTED as controls below feed source_knowledge_max_at -- a
        # considered-but-non-matching candidate's snapshot never
        # influenced the residual value, so its knowledge time must not
        # be folded in either.
        candidate_features_created_at: dict[uuid.UUID, datetime] = {}
        for candidate in candidate_tokens:
            if candidate.token_id == wallet_token.token_id:
                continue
            candidate_result = await _token_features_at(
                session,
                token=candidate,
                at=entry.entered_at,
                max_staleness=config.max_price_staleness,
                cutoff=cutoff,
            )
            if candidate_result is not None:
                features, features_created_at = candidate_result
                candidate_features.append(features)
                candidate_features_created_at[features.token_id] = features_created_at

        control_token_ids = select_matched_control_tokens(
            wallet_features, candidate_features, max_control_tokens=config.max_control_tokens
        )

        for horizon in config.horizons:
            horizon_seconds = int(horizon.total_seconds())
            wallet_return_result = await _forward_return_for_token(
                session,
                token_id=wallet_token.token_id,
                entered_at=entry.entered_at,
                horizon=horizon,
                config=config,
                cutoff=cutoff,
            )
            wallet_return = wallet_return_result[0] if wallet_return_result is not None else None

            # R2-02 clarification-002: the real source-evidence knowledge
            # times that actually determined THIS residual -- the wallet's
            # own matching-feature snapshot (it decided which controls
            # matched), the wallet's own forward-return snapshots, and
            # each SELECTED control's matching-feature snapshot and
            # forward-return snapshots. Never the persisted estimate row's
            # own created_at, which only reflects when this replay ran.
            source_created_ats: list[datetime] = [wallet_features_created_at]
            if wallet_return_result is not None:
                source_created_ats.append(wallet_return_result[1])

            control_returns: list[Decimal] = []
            for control_token_id in control_token_ids:
                control_created_at = candidate_features_created_at.get(control_token_id)
                if control_created_at is not None:
                    source_created_ats.append(control_created_at)
                control_return_result = await _forward_return_for_token(
                    session,
                    token_id=control_token_id,
                    entered_at=entry.entered_at,
                    horizon=horizon,
                    config=config,
                    cutoff=cutoff,
                )
                if control_return_result is not None:
                    control_returns.append(control_return_result[0])
                    source_created_ats.append(control_return_result[1])

            matched_universe_return = (
                sum(control_returns, Decimal(0)) / Decimal(len(control_returns))
                if control_returns
                else None
            )
            residual = compute_residual_selection_alpha(wallet_return, control_returns)

            matching_snapshot = {
                "market_cap_bucket": wallet_features.market_cap_bucket,
                "liquidity_bucket": wallet_features.liquidity_bucket,
                "token_age_bucket": wallet_features.token_age_bucket,
                "launch_venue": wallet_features.launch_venue,
                "control_token_ids": [str(t) for t in control_token_ids],
            }

            await get_or_create_counterfactual_alpha_estimate(
                session,
                prospective_event_id=entry.source_id,
                wallet_id=entry.wallet_id,
                token_id=entry.token_id,
                entered_at=entry.entered_at,
                horizon_seconds=horizon_seconds,
                wallet_token_forward_return=wallet_return,
                matched_universe_forward_return=matched_universe_return,
                residual_selection_alpha=residual,
                matched_control_count=len(control_returns),
                matching_snapshot=matching_snapshot,
                as_of=cutoff,
                algorithm_version=ALGORITHM_VERSION,
                config_hash=config_hash,
                now=computed_at,
            )
            count += 1
            if residual is not None:
                key = (entry.wallet_id, horizon_seconds)
                # R2-02 clarification-002: pairs the residual with the MAX
                # created_at among the actual TokenMarketSnapshot rows that
                # determined it (wallet + selected-control matching
                # features and forward-return snapshots) --
                # _compute_and_persist_specialist_scores folds this real
                # source-evidence knowledge time into
                # source_knowledge_max_at. Never the persisted estimate
                # row's own created_at (clarification-001's prior, weaker
                # bound) -- that only reflects when THIS replay ran, not
                # when its source evidence became knowable.
                entry_alpha_by_wallet_horizon.setdefault(key, []).append(
                    (residual, max(source_created_ats))
                )

    return count, entry_alpha_by_wallet_horizon


async def _compute_and_persist_specialist_scores(
    session: AsyncSession,
    *,
    entries: list[WalletTokenEntry],
    entry_alpha_by_wallet_horizon: dict[tuple[uuid.UUID, int], list[tuple[Decimal, datetime]]],
    cutoff: datetime,
    graph_config: GraphRunConfig,
    config: Phase9RunConfig,
    computed_at: datetime,
) -> int:
    """R2-02 clarification-001 section 3: the persisted
    ``WalletSpecialistScore.source_knowledge_max_at`` is the MAX
    ``created_at`` among every source row that actually contributed to
    THIS wallet's score (across all four specialist dimensions) --
    machine-checkable proof that every source item was known by
    ``cutoff``, independent of the score row's own physical persistence
    time. A wallet with zero contributing sources in every dimension
    gets ``cutoff`` itself (a trivially safe bound: no evidence was used,
    so there is nothing to leak)."""
    config_hash = config.config_hash()
    entry_horizon_seconds = int(config.entry_specialist_horizon.total_seconds())

    all_wallet_ids = {e.wallet_id for e in entries}

    entry_scores: dict[uuid.UUID, tuple[Decimal, int]] = {}
    entry_max_created_at: dict[uuid.UUID, datetime] = {}
    for wallet_id in all_wallet_ids:
        pairs = entry_alpha_by_wallet_horizon.get((wallet_id, entry_horizon_seconds), [])
        if pairs:
            values = [residual for residual, _ in pairs]
            entry_scores[wallet_id] = (sum(values, Decimal(0)) / Decimal(len(values)), len(values))
            entry_max_created_at[wallet_id] = max(created_at for _, created_at in pairs)

    discovery_scores: dict[uuid.UUID, tuple[Decimal, int]] = {}
    validation_scores: dict[uuid.UUID, tuple[Decimal, int]] = {}
    exit_scores: dict[uuid.UUID, Decimal] = {}
    discovery_max_created_at: dict[uuid.UUID, datetime] = {}
    validation_max_created_at: dict[uuid.UUID, datetime] = {}
    exit_created_at: dict[uuid.UUID, datetime] = {}

    for wallet_id in all_wallet_ids:
        outgoing = (
            (
                await session.execute(
                    select(DirectionalEdge).where(
                        DirectionalEdge.leader_wallet_id == wallet_id,
                        DirectionalEdge.algorithm_version == GRAPH_ALGORITHM_VERSION,
                        DirectionalEdge.config_hash == graph_config.config_hash(),
                        DirectionalEdge.as_of == cutoff,
                        # R2-02: as_of == cutoff alone only bounds the edge's own
                        # EFFECTIVE time -- known_by_cutoff (M1) requires BOTH
                        # effective_at <= cutoff AND created_at <= cutoff. Without
                        # this second bound, an edge computed/persisted AFTER
                        # cutoff (using source evidence only knowable later) could
                        # still be selected here just because its as_of label says
                        # cutoff -- a causal information leak dressed up as a valid
                        # historical reconstruction.
                        DirectionalEdge.created_at <= cutoff,
                        DirectionalEdge.q_value <= config.discovery_q_value_threshold,
                        DirectionalEdge.observation_count >= config.discovery_min_observations,
                    )
                )
            )
            .scalars()
            .all()
        )
        effect_sizes = [e.effect_size for e in outgoing if e.effect_size is not None]
        if effect_sizes:
            discovery_scores[wallet_id] = (
                sum(effect_sizes, Decimal(0)) / Decimal(len(effect_sizes)),
                len(effect_sizes),
            )
            discovery_max_created_at[wallet_id] = max(e.created_at for e in outgoing)

        confirmations = (
            (
                await session.execute(
                    select(ExpectedConfirmationEvent).where(
                        ExpectedConfirmationEvent.follower_wallet_id == wallet_id,
                        ExpectedConfirmationEvent.as_of == cutoff,
                        # R2-02: same known_by_cutoff discipline as the discovery
                        # query above -- as_of alone is not knowledge-time safe.
                        ExpectedConfirmationEvent.created_at <= cutoff,
                    )
                )
            )
            .scalars()
            .all()
        )
        if confirmations:
            not_absent = sum(1 for c in confirmations if c.outcome != "ABSENT")
            validation_scores[wallet_id] = (
                Decimal(not_absent) / Decimal(len(confirmations)),
                len(confirmations),
            )
            validation_max_created_at[wallet_id] = max(c.created_at for c in confirmations)

        exit_skill = await load_latest_exit_skill(session, wallet_id=wallet_id, cutoff=cutoff)
        if exit_skill is not None:
            exit_scores[wallet_id], exit_created_at[wallet_id] = exit_skill

    entry_population = [v for v, _ in entry_scores.values()]
    discovery_population = [v for v, _ in discovery_scores.values()]
    validation_population = [v for v, _ in validation_scores.values()]
    exit_population = list(exit_scores.values())

    count = 0
    for wallet_id in sorted(all_wallet_ids, key=str):
        entry_value = entry_scores.get(wallet_id)
        discovery_value = discovery_scores.get(wallet_id)
        validation_value = validation_scores.get(wallet_id)
        exit_value = exit_scores.get(wallet_id)

        entry_percentile = (
            percentile_rank(entry_value[0], entry_population) if entry_value else None
        )
        discovery_percentile = (
            percentile_rank(discovery_value[0], discovery_population) if discovery_value else None
        )
        validation_percentile = (
            percentile_rank(validation_value[0], validation_population)
            if validation_value
            else None
        )
        exit_percentile = percentile_rank(exit_value, exit_population) if exit_value else None

        specialty = dominant_specialty(
            {
                "ENTRY": entry_percentile,
                "DISCOVERY": discovery_percentile,
                "VALIDATION": validation_percentile,
                "EXIT": exit_percentile,
            }
        )

        # R2-02 clarification-001: the max known-by-cutoff creation time
        # across every dimension that actually contributed a value for
        # this wallet -- never the score row's OWN created_at, which
        # only reflects when THIS computation ran, not when its source
        # evidence became knowable. A wallet with no contributing source
        # in any dimension falls back to cutoff itself (no evidence used
        # -> nothing to leak).
        contributing_times = [
            t
            for t in (
                entry_max_created_at.get(wallet_id),
                discovery_max_created_at.get(wallet_id),
                validation_max_created_at.get(wallet_id),
                exit_created_at.get(wallet_id),
            )
            if t is not None
        ]
        source_knowledge_max_at = max(contributing_times) if contributing_times else cutoff

        await get_or_create_wallet_specialist_score(
            session,
            wallet_id=wallet_id,
            as_of=cutoff,
            entry_specialist_score=entry_value[0] if entry_value else None,
            entry_specialist_sample_size=entry_value[1] if entry_value else 0,
            discovery_specialist_score=discovery_value[0] if discovery_value else None,
            discovery_specialist_sample_size=discovery_value[1] if discovery_value else 0,
            validation_specialist_score=validation_value[0] if validation_value else None,
            validation_specialist_sample_size=validation_value[1] if validation_value else 0,
            exit_specialist_score=exit_value,
            entry_percentile=entry_percentile,
            discovery_percentile=discovery_percentile,
            validation_percentile=validation_percentile,
            exit_percentile=exit_percentile,
            dominant_specialty=specialty,
            source_knowledge_max_at=source_knowledge_max_at,
            algorithm_version=ALGORITHM_VERSION,
            config_hash=config_hash,
            now=computed_at,
        )
        count += 1

    return count


@dataclass(frozen=True)
class _LeaderPredationCounts:
    total_entries_count: int
    entries_with_influx_count: int
    exit_after_influx_count: int
    influx_values: list[int]


async def _compute_and_persist_predation_scores(
    session: AsyncSession,
    *,
    entries: list[WalletTokenEntry],
    exits: list[WalletTokenEntry],
    cutoff: datetime,
    graph_config: GraphRunConfig,
    config: Phase9RunConfig,
    computed_at: datetime,
) -> int:
    """FSR-07: incorporates all four of section 61's required evidence
    families -- follower influx, leader-exit timing, repetition
    frequency (how many times the influx-then-exit pattern has actually
    repeated for this leader), and real contemporaneous price-impact
    evidence (the FOLLOWERS' own Phase 5 executable-entry price impact
    on the same token shortly after the leader, since "follower-driven
    price impact" is section 61's own causal term for what followers
    experience piling in behind a leader -- never inferred from a later
    chart). Missing price impact never silently behaves as zero/safe:
    ``compute_predation_score`` leaves the core score unchanged and
    reports ``price_impact_incorporated=False`` instead."""
    config_hash = config.config_hash()
    exits_by_wallet_token: dict[tuple[uuid.UUID, uuid.UUID], list[datetime]] = {}
    for e in exits:
        exits_by_wallet_token.setdefault((e.wallet_id, e.token_id), []).append(e.entered_at)

    leader_wallet_ids = sorted({e.wallet_id for e in entries}, key=str)

    # Phase A: per-leader counts, plus every follower (wallet_id, token_id,
    # entered_at) triple seen in an influx episode -- the SAME MemberRef
    # shape FSR-05/06 already use for reusing Phase 5 evidence.
    per_leader: dict[uuid.UUID, _LeaderPredationCounts] = {}
    influx_followers_by_leader: dict[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID, datetime]]] = {}
    for wallet_id in leader_wallet_ids:
        leader_entries = [e for e in entries if e.wallet_id == wallet_id]
        influx_values: list[int] = []
        entries_with_influx = 0
        exits_after_influx = 0
        influx_followers: list[tuple[uuid.UUID, uuid.UUID, datetime]] = []

        for entry in leader_entries:
            observations = (
                (
                    await session.execute(
                        select(LeadFollowObservation).where(
                            LeadFollowObservation.leader_wallet_id == wallet_id,
                            LeadFollowObservation.token_id == entry.token_id,
                            LeadFollowObservation.algorithm_version == GRAPH_ALGORITHM_VERSION,
                            LeadFollowObservation.lag_seconds
                            <= Decimal(str(config.follower_influx_window.total_seconds())),
                            # FSR-04: an observation not yet known by this
                            # run's own cutoff must not leak into a
                            # follower-influx count computed as-of cutoff.
                            LeadFollowObservation.created_at <= cutoff,
                        )
                    )
                )
                .scalars()
                .all()
            )
            distinct_followers = {o.follower_wallet_id for o in observations}
            influx_values.append(len(distinct_followers))
            if distinct_followers:
                entries_with_influx += 1
                exit_times = exits_by_wallet_token.get((wallet_id, entry.token_id), [])
                window_end = entry.entered_at + config.exit_after_influx_window
                if any(entry.entered_at < t <= window_end for t in exit_times):
                    exits_after_influx += 1
                for o in observations:
                    if o.follower_wallet_id in distinct_followers:
                        influx_followers.append(
                            (o.follower_wallet_id, entry.token_id, o.follower_entered_at)
                        )

        per_leader[wallet_id] = _LeaderPredationCounts(
            total_entries_count=len(leader_entries),
            entries_with_influx_count=entries_with_influx,
            exit_after_influx_count=exits_after_influx,
            influx_values=influx_values,
        )
        influx_followers_by_leader[wallet_id] = influx_followers

    # Phase B: real follower price-impact evidence, batched -- each
    # distinct follower wallet's Phase 5 opportunity population is loaded
    # exactly once, shared across every leader that references it.
    distinct_follower_wallet_ids = {
        wallet_id
        for followers in influx_followers_by_leader.values()
        for wallet_id, _, _ in followers
    }
    opportunities_by_follower: dict[uuid.UUID, list[WalletOpportunity]] = {}
    for wallet_id in distinct_follower_wallet_ids:
        firewall = await load_contamination_firewall(session, wallet_id=wallet_id)
        loaded = await load_wallet_opportunities(
            session, wallet_id=wallet_id, cutoff=cutoff, firewall=firewall
        )
        opportunities_by_follower[wallet_id] = loaded.opportunities

    count = 0
    for wallet_id in leader_wallet_ids:
        stats = per_leader[wallet_id]
        influx_values = stats.influx_values
        entries_with_influx = stats.entries_with_influx_count
        exits_after_influx = stats.exit_after_influx_count

        follower_influx_mean = (
            Decimal(sum(influx_values)) / Decimal(len(influx_values)) if influx_values else None
        )
        exit_after_influx_rate = (
            Decimal(exits_after_influx) / Decimal(entries_with_influx)
            if entries_with_influx > 0
            else None
        )

        price_impacts: list[Decimal] = []
        for follower_wallet_id, token_id, follower_entered_at in influx_followers_by_leader[
            wallet_id
        ]:
            opportunity = next(
                (
                    opp
                    for opp in opportunities_by_follower.get(follower_wallet_id, [])
                    if opp.token_id == token_id and opp.first_seen_at == follower_entered_at
                ),
                None,
            )
            if opportunity is not None and opportunity.entry_price_impact_pct is not None:
                price_impacts.append(opportunity.entry_price_impact_pct)
        price_impact_mean = (
            sum(price_impacts, Decimal(0)) / Decimal(len(price_impacts)) if price_impacts else None
        )

        result = compute_predation_score(
            follower_influx_mean=follower_influx_mean,
            exit_after_influx_rate=exit_after_influx_rate,
            repeated_pattern_count=exits_after_influx,
            price_impact_mean=price_impact_mean,
            follower_influx_cap=config.predation_influx_normalization_cap,
        )

        await get_or_create_wallet_predation_score(
            session,
            wallet_id=wallet_id,
            as_of=cutoff,
            total_entries_count=stats.total_entries_count,
            entries_with_influx_count=entries_with_influx,
            follower_influx_mean=follower_influx_mean,
            exit_after_influx_count=exits_after_influx,
            exit_after_influx_rate=exit_after_influx_rate,
            price_impact_mean=price_impact_mean,
            price_impact_incorporated=result.price_impact_incorporated,
            predation_score=result.score,
            algorithm_version=ALGORITHM_VERSION,
            config_hash=config_hash,
            now=computed_at,
        )
        count += 1

    return count


async def _compute_and_persist_exit_convergence(
    session: AsyncSession,
    *,
    exits: list[WalletTokenEntry],
    exit_specialist_wallet_ids: set[uuid.UUID],
    cutoff: datetime,
    config: Phase9RunConfig,
    computed_at: datetime,
) -> int:
    config_hash = config.config_hash()
    qualifying_exits = [e for e in exits if e.wallet_id in exit_specialist_wallet_ids]
    episodes = build_convergence_episodes(qualifying_exits, window=config.exit_convergence_window)
    episodes.sort(key=lambda e: e.window_start)

    all_wallet_ids = {e.wallet_id for episode in episodes for e in episode.entries}
    links_by_wallet = await load_cluster_links_within_group(session, all_wallet_ids)

    historical_overlaps: list[Decimal] = []
    count = 0
    for episode in episodes:
        member_wallet_ids = [e.wallet_id for e in episode.entries]
        weights = compute_independence_weights(
            member_wallet_ids,
            links_by_wallet,
            cutoff=episode.window_end,
            unknown_independence_weight=config.exit_convergence_unknown_independence_weight,
        )
        observed = estimated_independent_actors(member_wallet_ids, weights)
        surprise = compute_overlap_surprise(observed, historical_overlaps)

        await get_or_create_exit_convergence_event(
            session,
            episode=episode,
            estimated_independent_actors=observed,
            surprise=surprise,
            as_of=cutoff,
            algorithm_version=ALGORITHM_VERSION,
            config_hash=config_hash,
            now=computed_at,
        )
        historical_overlaps.append(observed)
        count += 1

    return count


async def compute_and_persist_phase9(
    session: AsyncSession,
    *,
    cutoff: datetime,
    graph_config: GraphRunConfig,
    phase8_config: Phase8RunConfig,
    config: Phase9RunConfig,
    computed_at: datetime,
) -> Phase9ComputationResult:
    await compute_and_persist_phase8(
        session,
        cutoff=cutoff,
        graph_config=graph_config,
        config=phase8_config,
        computed_at=computed_at,
    )

    entries = await load_wallet_token_entries(session, cutoff=cutoff)
    exits = await load_wallet_token_exits(session, cutoff=cutoff)

    token_ids = {e.token_id for e in entries} | {e.token_id for e in exits}
    tokens = (
        (await session.execute(select(Token).where(Token.token_id.in_(token_ids)))).scalars().all()
        if token_ids
        else []
    )
    tokens_by_id = {t.token_id: t for t in tokens}
    candidate_tokens = await load_candidate_tokens(session, cutoff=cutoff)

    alpha_count, entry_alpha_by_wallet_horizon = await _compute_and_persist_counterfactual_alpha(
        session,
        entries=entries,
        tokens_by_id=tokens_by_id,
        candidate_tokens=candidate_tokens,
        cutoff=cutoff,
        config=config,
        computed_at=computed_at,
    )

    specialist_count = await _compute_and_persist_specialist_scores(
        session,
        entries=entries,
        entry_alpha_by_wallet_horizon=entry_alpha_by_wallet_horizon,
        cutoff=cutoff,
        graph_config=graph_config,
        config=config,
        computed_at=computed_at,
    )

    predation_count = await _compute_and_persist_predation_scores(
        session,
        entries=entries,
        exits=exits,
        cutoff=cutoff,
        graph_config=graph_config,
        config=config,
        computed_at=computed_at,
    )

    exit_specialist_rows = (await session.execute(select(WalletSpecialistScore))).scalars().all()

    exit_convergence_count = await _compute_and_persist_exit_convergence(
        session,
        exits=exits,
        exit_specialist_wallet_ids={
            r.wallet_id
            for r in exit_specialist_rows
            if r.as_of == cutoff
            and r.algorithm_version == ALGORITHM_VERSION
            and r.config_hash == config.config_hash()
            and r.exit_specialist_score is not None
            and r.exit_specialist_score >= config.min_exit_specialist_score
        },
        cutoff=cutoff,
        config=config,
        computed_at=computed_at,
    )

    return Phase9ComputationResult(
        as_of=cutoff,
        alpha_estimate_count=alpha_count,
        specialist_score_count=specialist_count,
        predation_score_count=predation_count,
        exit_convergence_event_count=exit_convergence_count,
        entry_alpha_by_wallet_horizon=entry_alpha_by_wallet_horizon,
    )

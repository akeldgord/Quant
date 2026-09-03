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

ALGORITHM_VERSION: Final[str] = "counterfactual_alpha_specialists_v1"

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
    entry_alpha_by_wallet_horizon: dict[tuple[uuid.UUID, int], list[Decimal]] = field(
        default_factory=dict
    )


async def _token_features_at(
    session: AsyncSession, *, token: Token, at: datetime, max_staleness: timedelta
) -> TokenFeatures | None:
    snapshot = await load_token_market_snapshot_at_or_before(
        session, token_id=token.token_id, at=at
    )
    if snapshot is None or snapshot.market_cap_usd is None or snapshot.liquidity_usd is None:
        return None
    if (at - snapshot.observed_at) > max_staleness:
        return None
    age = at - token.first_observed_at
    if age < timedelta(0):
        return None
    return TokenFeatures(
        token_id=token.token_id,
        market_cap_bucket=market_cap_bucket(snapshot.market_cap_usd),
        liquidity_bucket=liquidity_bucket(snapshot.liquidity_usd),
        token_age_bucket=token_age_bucket(age),
        launch_venue=snapshot.venue,
    )


async def _forward_return_for_token(
    session: AsyncSession,
    *,
    token_id: uuid.UUID,
    entered_at: datetime,
    horizon: timedelta,
    config: Phase9RunConfig,
) -> Decimal | None:
    max_staleness_seconds = config.max_price_staleness.total_seconds()
    entry_snapshot = await load_nearest_token_market_snapshot(
        session, token_id=token_id, target=entered_at, max_staleness_seconds=max_staleness_seconds
    )
    horizon_snapshot = await load_nearest_token_market_snapshot(
        session,
        token_id=token_id,
        target=entered_at + horizon,
        max_staleness_seconds=max_staleness_seconds,
    )
    if (
        entry_snapshot is None
        or horizon_snapshot is None
        or entry_snapshot.price_usd is None
        or horizon_snapshot.price_usd is None
    ):
        return None
    return compute_forward_return(entry_snapshot.price_usd, horizon_snapshot.price_usd)


async def _compute_and_persist_counterfactual_alpha(
    session: AsyncSession,
    *,
    entries: list[WalletTokenEntry],
    tokens_by_id: dict[uuid.UUID, Token],
    candidate_tokens: list[Token],
    cutoff: datetime,
    config: Phase9RunConfig,
    computed_at: datetime,
) -> tuple[int, dict[tuple[uuid.UUID, int], list[Decimal]]]:
    config_hash = config.config_hash()
    entry_alpha_by_wallet_horizon: dict[tuple[uuid.UUID, int], list[Decimal]] = {}
    count = 0

    for entry in entries:
        wallet_token = tokens_by_id.get(entry.token_id)
        if wallet_token is None:
            continue
        wallet_features = await _token_features_at(
            session,
            token=wallet_token,
            at=entry.entered_at,
            max_staleness=config.max_price_staleness,
        )
        if wallet_features is None:
            continue

        candidate_features: list[TokenFeatures] = []
        for candidate in candidate_tokens:
            if candidate.token_id == wallet_token.token_id:
                continue
            features = await _token_features_at(
                session,
                token=candidate,
                at=entry.entered_at,
                max_staleness=config.max_price_staleness,
            )
            if features is not None:
                candidate_features.append(features)

        control_token_ids = select_matched_control_tokens(
            wallet_features, candidate_features, max_control_tokens=config.max_control_tokens
        )

        for horizon in config.horizons:
            horizon_seconds = int(horizon.total_seconds())
            wallet_return = await _forward_return_for_token(
                session,
                token_id=wallet_token.token_id,
                entered_at=entry.entered_at,
                horizon=horizon,
                config=config,
            )
            control_returns: list[Decimal] = []
            for control_token_id in control_token_ids:
                control_return = await _forward_return_for_token(
                    session,
                    token_id=control_token_id,
                    entered_at=entry.entered_at,
                    horizon=horizon,
                    config=config,
                )
                if control_return is not None:
                    control_returns.append(control_return)

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
                entry_alpha_by_wallet_horizon.setdefault(key, []).append(residual)

    return count, entry_alpha_by_wallet_horizon


async def _compute_and_persist_specialist_scores(
    session: AsyncSession,
    *,
    entries: list[WalletTokenEntry],
    entry_alpha_by_wallet_horizon: dict[tuple[uuid.UUID, int], list[Decimal]],
    cutoff: datetime,
    graph_config: GraphRunConfig,
    config: Phase9RunConfig,
    computed_at: datetime,
) -> int:
    config_hash = config.config_hash()
    entry_horizon_seconds = int(config.entry_specialist_horizon.total_seconds())

    all_wallet_ids = {e.wallet_id for e in entries}

    entry_scores: dict[uuid.UUID, tuple[Decimal, int]] = {}
    for wallet_id in all_wallet_ids:
        values = entry_alpha_by_wallet_horizon.get((wallet_id, entry_horizon_seconds), [])
        if values:
            entry_scores[wallet_id] = (sum(values, Decimal(0)) / Decimal(len(values)), len(values))

    discovery_scores: dict[uuid.UUID, tuple[Decimal, int]] = {}
    validation_scores: dict[uuid.UUID, tuple[Decimal, int]] = {}
    exit_scores: dict[uuid.UUID, Decimal] = {}

    for wallet_id in all_wallet_ids:
        outgoing = (
            (
                await session.execute(
                    select(DirectionalEdge).where(
                        DirectionalEdge.leader_wallet_id == wallet_id,
                        DirectionalEdge.algorithm_version == GRAPH_ALGORITHM_VERSION,
                        DirectionalEdge.config_hash == graph_config.config_hash(),
                        DirectionalEdge.as_of == cutoff,
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

        confirmations = (
            (
                await session.execute(
                    select(ExpectedConfirmationEvent).where(
                        ExpectedConfirmationEvent.follower_wallet_id == wallet_id,
                        ExpectedConfirmationEvent.as_of == cutoff,
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

        exit_skill = await load_latest_exit_skill(session, wallet_id=wallet_id, cutoff=cutoff)
        if exit_skill is not None:
            exit_scores[wallet_id] = exit_skill

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
            algorithm_version=ALGORITHM_VERSION,
            config_hash=config_hash,
            now=computed_at,
        )
        count += 1

    return count


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
    config_hash = config.config_hash()
    exits_by_wallet_token: dict[tuple[uuid.UUID, uuid.UUID], list[datetime]] = {}
    for e in exits:
        exits_by_wallet_token.setdefault((e.wallet_id, e.token_id), []).append(e.entered_at)

    leader_wallet_ids = {e.wallet_id for e in entries}
    count = 0
    for wallet_id in sorted(leader_wallet_ids, key=str):
        leader_entries = [e for e in entries if e.wallet_id == wallet_id]
        influx_values: list[int] = []
        entries_with_influx = 0
        exits_after_influx = 0

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

        follower_influx_mean = (
            Decimal(sum(influx_values)) / Decimal(len(influx_values)) if influx_values else None
        )
        exit_after_influx_rate = (
            Decimal(exits_after_influx) / Decimal(entries_with_influx)
            if entries_with_influx > 0
            else None
        )
        score = compute_predation_score(
            follower_influx_mean=follower_influx_mean,
            exit_after_influx_rate=exit_after_influx_rate,
            cap=config.predation_influx_normalization_cap,
        )

        await get_or_create_wallet_predation_score(
            session,
            wallet_id=wallet_id,
            as_of=cutoff,
            total_entries_count=len(leader_entries),
            entries_with_influx_count=entries_with_influx,
            follower_influx_mean=follower_influx_mean,
            exit_after_influx_count=exits_after_influx,
            exit_after_influx_rate=exit_after_influx_rate,
            # Always None in this build -- a disclosed scope limitation
            # (would require synchronized pre/post-entry price snapshots,
            # rarely available -- see docs/DECISION_LOG.md).
            price_impact_mean=None,
            predation_score=score,
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

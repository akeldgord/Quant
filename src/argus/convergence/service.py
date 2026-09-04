"""argus.convergence.service -- MASTER_SPEC.md Phase 8 (CONVERGENCE +
NEGATIVE EVIDENCE) orchestration: ties together convergence-episode
surprisal (section 59) and dog-that-didn't-bark confirmation
classification (section 60) into one computation run, persisted
idempotently. This is the one place Phase 8's analytics are assembled --
``argus convergence report`` (the CLI command) calls this.

Computes Phase 7's own directional edges first (reusing
``argus.graph.service.compute_and_persist_directional_edges`` unchanged
-- idempotent, so a prior run at the same cutoff/config is reused, never
recomputed) since dog-that-didn't-bark classification is defined in terms
of Phase 7's own significant edges; the pipeline this mirrors is
MASTER_SPEC.md's own "Alpha Ancestry -> Convergence Surprise" ordering.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from argus.convergence.confirmation import (
    OUTCOME_STRONG,
    classify_confirmation,
    expected_confirmation_window,
)
from argus.convergence.episodes import ConvergenceEpisode, build_convergence_episodes
from argus.convergence.independence import (
    compute_independence_weights,
    estimated_independent_actors,
)
from argus.convergence.loaders import (
    load_cluster_links_within_group,
    load_observations_for_edge,
    load_significant_directional_edges,
)
from argus.convergence.persistence import (
    get_or_create_convergence_event,
    get_or_create_expected_confirmation_event,
)
from argus.convergence.stats import compute_overlap_surprise
from argus.domain.convergence_events import ConvergenceEvent
from argus.graph.lead_follow import WalletTokenEntry
from argus.graph.loaders import load_wallet_token_entries
from argus.graph.service import (
    ALGORITHM_VERSION as GRAPH_ALGORITHM_VERSION,
)
from argus.graph.service import (
    GraphRunConfig,
    compute_and_persist_directional_edges,
)

ALGORITHM_VERSION: Final[str] = "convergence_negative_evidence_v1"

_PHASE8_ARTIFACT_FILENAMES: Final[tuple[str, ...]] = (
    "episodes.py",
    "independence.py",
    "stats.py",
    "confirmation.py",
    "loaders.py",
    "persistence.py",
    "service.py",
)


def _compute_build_hash() -> str:
    digest = hashlib.sha256()
    module_dir = Path(__file__).parent
    for filename in _PHASE8_ARTIFACT_FILENAMES:
        digest.update((module_dir / filename).read_bytes())
    return digest.hexdigest()


BUILD_HASH: Final[str] = _compute_build_hash()


@dataclass(frozen=True)
class ConvergenceRunConfig:
    window: timedelta
    unknown_independence_weight: Decimal
    q_value_threshold: Decimal
    min_observations: int
    strong_surprisal_threshold: Decimal

    def config_hash(self) -> str:
        payload = (
            f"window_seconds={self.window.total_seconds()}|"
            f"unknown_independence_weight={self.unknown_independence_weight}|"
            f"q_value_threshold={self.q_value_threshold}|"
            f"min_observations={self.min_observations}|"
            f"strong_surprisal_threshold={self.strong_surprisal_threshold}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ComputedConvergenceEvent:
    episode: ConvergenceEpisode
    row: ConvergenceEvent
    estimated_independent_actors: Decimal
    surprisal: Decimal
    calibration_confidence: str


@dataclass(frozen=True)
class Phase8ComputationResult:
    as_of: datetime
    convergence_events: list[ComputedConvergenceEvent] = field(default_factory=list)
    expected_confirmation_outcome_counts: dict[str, int] = field(default_factory=dict)
    expected_confirmation_total: int = 0


async def _compute_and_persist_convergence_events(
    session: AsyncSession,
    *,
    entries: list[WalletTokenEntry],
    cutoff: datetime,
    config: ConvergenceRunConfig,
    computed_at: datetime,
) -> list[ComputedConvergenceEvent]:
    episodes = build_convergence_episodes(entries, window=config.window)
    episodes.sort(key=lambda e: e.window_start)

    all_wallet_ids = {e.wallet_id for episode in episodes for e in episode.entries}
    links_by_wallet = await load_cluster_links_within_group(session, all_wallet_ids)

    computed: list[ComputedConvergenceEvent] = []
    historical_overlaps: list[Decimal] = []
    for episode in episodes:
        member_wallet_ids = [e.wallet_id for e in episode.entries]
        weights = compute_independence_weights(
            member_wallet_ids,
            links_by_wallet,
            cutoff=episode.window_end,
            unknown_independence_weight=config.unknown_independence_weight,
        )
        observed = estimated_independent_actors(member_wallet_ids, weights)
        surprise = compute_overlap_surprise(observed, historical_overlaps)

        row, _created = await get_or_create_convergence_event(
            session,
            episode=episode,
            estimated_independent_actors=observed,
            surprise=surprise,
            as_of=cutoff,
            algorithm_version=ALGORITHM_VERSION,
            config_hash=config.config_hash(),
            now=computed_at,
        )
        computed.append(
            ComputedConvergenceEvent(
                episode=episode,
                row=row,
                estimated_independent_actors=observed,
                surprisal=surprise.surprisal,
                calibration_confidence=surprise.calibration_confidence,
            )
        )
        historical_overlaps.append(observed)

    return computed


async def _compute_and_persist_expected_confirmations(
    session: AsyncSession,
    *,
    entries: list[WalletTokenEntry],
    convergence_by_token: dict[uuid.UUID, ComputedConvergenceEvent],
    cutoff: datetime,
    graph_config: GraphRunConfig,
    config: ConvergenceRunConfig,
    computed_at: datetime,
) -> dict[str, int]:
    edges = await load_significant_directional_edges(
        session,
        algorithm_version=GRAPH_ALGORITHM_VERSION,
        config_hash=graph_config.config_hash(),
        as_of=cutoff,
        q_value_threshold=config.q_value_threshold,
        min_observations=config.min_observations,
    )

    outcome_counts: dict[str, int] = {}
    for edge in edges:
        observations = await load_observations_for_edge(
            session,
            leader_wallet_id=edge.leader_wallet_id,
            follower_wallet_id=edge.follower_wallet_id,
            algorithm_version=GRAPH_ALGORITHM_VERSION,
        )
        observations_by_token = {o.token_id: o for o in observations}

        leader_entries_by_token: dict[uuid.UUID, WalletTokenEntry] = {}
        for e in entries:
            if e.wallet_id != edge.leader_wallet_id:
                continue
            existing = leader_entries_by_token.get(e.token_id)
            if existing is None or e.entered_at < existing.entered_at:
                leader_entries_by_token[e.token_id] = e
        ordered_leader_entries = sorted(
            leader_entries_by_token.values(), key=lambda e: e.entered_at
        )

        for leader_entry in ordered_leader_entries:
            historical_lags = [
                o.lag_seconds for o in observations if o.leader_entered_at < leader_entry.entered_at
            ]
            if not historical_lags:
                continue

            low, high = expected_confirmation_window(historical_lags)
            matching_observation = observations_by_token.get(leader_entry.token_id)
            follower_entered_at = (
                matching_observation.follower_entered_at
                if matching_observation is not None
                else None
            )

            convergence_event = convergence_by_token.get(leader_entry.token_id)
            is_strong = (
                convergence_event is not None
                and convergence_event.surprisal >= config.strong_surprisal_threshold
                and convergence_event.calibration_confidence != "INSUFFICIENT_SAMPLE"
            )

            classification = classify_confirmation(
                leader_entered_at=leader_entry.entered_at,
                follower_entered_at=follower_entered_at,
                expected_window_low_seconds=low,
                expected_window_high_seconds=high,
                is_strong=is_strong,
            )

            await get_or_create_expected_confirmation_event(
                session,
                directional_edge_id=edge.edge_id,
                leader_prospective_event_id=leader_entry.source_id,
                token_id=leader_entry.token_id,
                leader_wallet_id=edge.leader_wallet_id,
                follower_wallet_id=edge.follower_wallet_id,
                classification=classification,
                convergence_event_id=(
                    convergence_event.row.convergence_event_id
                    if classification.outcome == OUTCOME_STRONG and convergence_event is not None
                    else None
                ),
                as_of=cutoff,
                algorithm_version=ALGORITHM_VERSION,
                config_hash=config.config_hash(),
                now=computed_at,
            )
            outcome_counts[classification.outcome] = (
                outcome_counts.get(classification.outcome, 0) + 1
            )

    return outcome_counts


async def compute_and_persist_phase8(
    session: AsyncSession,
    *,
    cutoff: datetime,
    graph_config: GraphRunConfig,
    config: ConvergenceRunConfig,
    computed_at: datetime,
) -> Phase8ComputationResult:
    await compute_and_persist_directional_edges(
        session, cutoff=cutoff, config=graph_config, computed_at=computed_at
    )

    entries = await load_wallet_token_entries(session, cutoff=cutoff)

    convergence_events = await _compute_and_persist_convergence_events(
        session, entries=entries, cutoff=cutoff, config=config, computed_at=computed_at
    )
    convergence_by_token = {c.episode.token_id: c for c in convergence_events}

    outcome_counts = await _compute_and_persist_expected_confirmations(
        session,
        entries=entries,
        convergence_by_token=convergence_by_token,
        cutoff=cutoff,
        graph_config=graph_config,
        config=config,
        computed_at=computed_at,
    )

    return Phase8ComputationResult(
        as_of=cutoff,
        convergence_events=convergence_events,
        expected_confirmation_outcome_counts=outcome_counts,
        expected_confirmation_total=sum(outcome_counts.values()),
    )

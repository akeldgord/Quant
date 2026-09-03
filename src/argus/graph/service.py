"""argus.graph.service — MASTER_SPEC.md Phase 7 (ALPHA ANCESTRY)
orchestration: ties the pure lead/follow mechanics and the production
loader together into one computation run, persisted idempotently. This
is the one place Phase 7's analytics are assembled -- ``argus graph
report`` (the CLI command) calls this.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from argus.graph.lead_follow import (
    DirectionalEdgeWithSignificance,
    apply_multiple_comparison_correction,
    build_lead_follow_observations,
    compute_directional_edge,
)
from argus.graph.loaders import compute_follower_base_rates, load_wallet_token_entries
from argus.graph.persistence import (
    get_or_create_directional_edge,
    get_or_create_lead_follow_observation,
)

ALGORITHM_VERSION = "alpha_ancestry_v1"

_PHASE7_ARTIFACT_FILENAMES: Final[tuple[str, ...]] = (
    "lead_follow.py",
    "stats.py",
    "loaders.py",
    "persistence.py",
    "service.py",
)


def _compute_build_hash() -> str:
    digest = hashlib.sha256()
    module_dir = Path(__file__).parent
    for filename in _PHASE7_ARTIFACT_FILENAMES:
        digest.update((module_dir / filename).read_bytes())
    return digest.hexdigest()


BUILD_HASH: Final[str] = _compute_build_hash()


@dataclass(frozen=True)
class GraphRunConfig:
    max_lag: timedelta
    min_observations: int
    q_value_threshold: Decimal

    def config_hash(self) -> str:
        payload = (
            f"max_lag_seconds={self.max_lag.total_seconds()}|"
            f"min_observations={self.min_observations}|"
            f"q_value_threshold={self.q_value_threshold}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GraphComputationResult:
    edges: list[DirectionalEdgeWithSignificance]
    observation_count: int
    wallet_count: int
    as_of: datetime


async def compute_and_persist_directional_edges(
    session: AsyncSession,
    *,
    cutoff: datetime,
    config: GraphRunConfig,
    computed_at: datetime,
) -> GraphComputationResult:
    """Loads all tracked-wallet token entries known by ``cutoff``, builds
    every lead/follow observation within ``config.max_lag``, persists
    them idempotently, aggregates into directional edges against each
    follower's own empirical base rate, applies Benjamini-Hochberg
    correction across every edge computed in this SAME run, and persists
    the edges idempotently under this run's own ``config_hash``.

    ``forward_information_after_leader_pct`` is always persisted as
    ``None`` in this build -- computing it honestly requires reusing
    Phase 5's own cohort-matched executable-return evidence for the
    follower's specific entry, which is deferred as a disclosed scope
    limitation rather than approximated or fabricated (see
    ``docs/DECISION_LOG.md``'s Phase 7 entry)."""
    entries = await load_wallet_token_entries(session, cutoff=cutoff)
    base_rates = compute_follower_base_rates(entries)

    observations = build_lead_follow_observations(entries, max_lag=config.max_lag)
    for observation in observations:
        await get_or_create_lead_follow_observation(
            session, observation=observation, algorithm_version=ALGORITHM_VERSION, now=computed_at
        )

    observations_by_pair: dict[tuple[uuid.UUID, uuid.UUID], list] = {}
    for observation in observations:
        key = (observation.leader_wallet_id, observation.follower_wallet_id)
        observations_by_pair.setdefault(key, []).append(observation)

    tokens_entered_by_wallet = {
        wallet_id: distinct_tokens for wallet_id, (distinct_tokens, _) in base_rates.items()
    }
    universe_size = next(iter(base_rates.values()), (0, 0))[1]

    edges = []
    for (leader_wallet_id, follower_wallet_id), pair_observations in observations_by_pair.items():
        follower_distinct, _ = base_rates.get(follower_wallet_id, (0, universe_size))
        follower_base_rate = (
            Decimal(follower_distinct) / Decimal(universe_size) if universe_size > 0 else Decimal(0)
        )
        edges.append(
            compute_directional_edge(
                leader_wallet_id=leader_wallet_id,
                follower_wallet_id=follower_wallet_id,
                observations=pair_observations,
                tokens_leader_entered=tokens_entered_by_wallet.get(leader_wallet_id, 0),
                follower_base_rate=follower_base_rate,
            )
        )

    edges_with_significance = apply_multiple_comparison_correction(edges)

    config_hash = config.config_hash()
    for result in edges_with_significance:
        await get_or_create_directional_edge(
            session,
            result=result,
            forward_information_after_leader_pct=None,
            as_of=cutoff,
            algorithm_version=ALGORITHM_VERSION,
            config_hash=config_hash,
            now=computed_at,
        )

    return GraphComputationResult(
        edges=edges_with_significance,
        observation_count=len(observations),
        wallet_count=len(base_rates),
        as_of=cutoff,
    )

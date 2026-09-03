"""argus.convergence.loaders -- MASTER_SPEC.md Phase 8 (CONVERGENCE +
NEGATIVE EVIDENCE) production data loaders: Phase 3 wallet-cluster-link
evidence restricted to a specific group of wallets, and the significant
(FDR-surviving) Phase 7 directional edges and their own underlying
lead/follow observations that seed dog-that-didn't-bark checks.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from argus.domain.directional_edges import DirectionalEdge
from argus.domain.lead_follow_observations import LeadFollowObservation
from argus.domain.wallet_cluster_links import WalletClusterLink
from argus.wallets.clustering import ClusterLinkEvidence


async def load_cluster_links_within_group(
    session: AsyncSession, wallet_ids: set[uuid.UUID]
) -> dict[uuid.UUID, list[ClusterLinkEvidence]]:
    """Every ``wallet_cluster_links`` row where BOTH endpoints are members
    of ``wallet_ids`` -- a link to a wallet outside this universe carries
    no information about any group formed from within it. Safe to call
    once with the full universe of entrant wallets across many episodes;
    ``argus.convergence.independence.compute_independence_weights`` does
    its own further per-group restriction."""
    if not wallet_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(WalletClusterLink).where(
                    WalletClusterLink.wallet_a_id.in_(wallet_ids),
                    WalletClusterLink.wallet_b_id.in_(wallet_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    links_by_wallet: dict[uuid.UUID, list[ClusterLinkEvidence]] = {w: [] for w in wallet_ids}
    for row in rows:
        links_by_wallet[row.wallet_a_id].append(
            ClusterLinkEvidence(
                other_wallet_id=str(row.wallet_b_id),
                evidence_type=row.evidence_type,
                probability=row.probability,
            )
        )
        links_by_wallet[row.wallet_b_id].append(
            ClusterLinkEvidence(
                other_wallet_id=str(row.wallet_a_id),
                evidence_type=row.evidence_type,
                probability=row.probability,
            )
        )
    return links_by_wallet


async def load_significant_directional_edges(
    session: AsyncSession,
    *,
    algorithm_version: str,
    config_hash: str,
    as_of: datetime,
    q_value_threshold: Decimal,
    min_observations: int,
) -> list[DirectionalEdge]:
    """The Phase 7 edges from one specific prior run (identified by its
    own ``algorithm_version``/``config_hash``/``as_of``) that clear
    THIS Phase 8 run's own significance bar -- independent of whatever
    threshold that Phase 7 run itself used for candidate generation
    (``compute_and_persist_directional_edges`` persists every observed
    pair, regardless of significance)."""
    rows = (
        (
            await session.execute(
                select(DirectionalEdge).where(
                    DirectionalEdge.algorithm_version == algorithm_version,
                    DirectionalEdge.config_hash == config_hash,
                    DirectionalEdge.as_of == as_of,
                    DirectionalEdge.q_value <= q_value_threshold,
                    DirectionalEdge.observation_count >= min_observations,
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def load_observations_for_edge(
    session: AsyncSession,
    *,
    leader_wallet_id: uuid.UUID,
    follower_wallet_id: uuid.UUID,
    algorithm_version: str,
) -> list[LeadFollowObservation]:
    """Every persisted Phase 7 lead/follow observation for one specific
    (leader, follower) pair -- the raw evidence both the expected
    confirmation window (its ``lag_seconds`` distribution) and the
    per-token confirmation lookup (its ``token_id``/``follower_entered_at``)
    are built from."""
    rows = (
        (
            await session.execute(
                select(LeadFollowObservation).where(
                    LeadFollowObservation.leader_wallet_id == leader_wallet_id,
                    LeadFollowObservation.follower_wallet_id == follower_wallet_id,
                    LeadFollowObservation.algorithm_version == algorithm_version,
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)

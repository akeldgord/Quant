"""argus.graph.persistence — MASTER_SPEC.md Phase 7 (ALPHA ANCESTRY):
append-only, idempotent persistence for lead/follow observations and
directional edges. Follows the SAME ``INSERT ... ON CONFLICT DO NOTHING``
+ re-select-within-transaction pattern F5-05 established for Phase 5
snapshots (``argus.copyability.persistence``) -- a rerun over identical
evidence always reuses the existing row; a genuinely new observation or
a changed ``config_hash`` always produces a new row.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from argus.domain.directional_edges import DirectionalEdge
from argus.domain.lead_follow_observations import LeadFollowObservation
from argus.graph.lead_follow import (
    DirectionalEdgeWithSignificance,
)
from argus.graph.lead_follow import (
    LeadFollowObservation as LeadFollowObservationResult,
)


def _row_values(row: object, table) -> dict:
    return {column.name: getattr(row, column.name) for column in table.columns}


async def get_or_create_lead_follow_observation(
    session: AsyncSession,
    *,
    observation: LeadFollowObservationResult,
    algorithm_version: str,
    now: datetime,
) -> tuple[LeadFollowObservation, bool]:
    identity = (
        LeadFollowObservation.token_id == observation.token_id,
        LeadFollowObservation.leader_wallet_id == observation.leader_wallet_id,
        LeadFollowObservation.follower_wallet_id == observation.follower_wallet_id,
        LeadFollowObservation.algorithm_version == algorithm_version,
    )
    existing = (
        await session.execute(select(LeadFollowObservation).where(*identity))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    row = LeadFollowObservation(
        observation_id=uuid.uuid4(),
        token_id=observation.token_id,
        leader_wallet_id=observation.leader_wallet_id,
        follower_wallet_id=observation.follower_wallet_id,
        leader_prospective_event_id=observation.leader_source_id,
        follower_prospective_event_id=observation.follower_source_id,
        leader_entered_at=observation.leader_entered_at,
        follower_entered_at=observation.follower_entered_at,
        lag_seconds=observation.lag_seconds,
        algorithm_version=algorithm_version,
        created_at=now,
    )
    stmt = (
        pg_insert(LeadFollowObservation)
        .values(**_row_values(row, LeadFollowObservation.__table__))
        .on_conflict_do_nothing(constraint="uq_lead_follow_observations_identity")
        .returning(LeadFollowObservation.observation_id)
    )
    inserted_id = (await session.execute(stmt)).scalar_one_or_none()
    if inserted_id is not None:
        return row, True

    return (
        await session.execute(select(LeadFollowObservation).where(*identity))
    ).scalar_one(), False


async def get_or_create_directional_edge(
    session: AsyncSession,
    *,
    result: DirectionalEdgeWithSignificance,
    forward_information_after_leader_pct: Decimal | None,
    as_of: datetime,
    algorithm_version: str,
    config_hash: str,
    now: datetime,
) -> tuple[DirectionalEdge, bool]:
    edge = result.edge
    identity = (
        DirectionalEdge.leader_wallet_id == edge.leader_wallet_id,
        DirectionalEdge.follower_wallet_id == edge.follower_wallet_id,
        DirectionalEdge.as_of == as_of,
        DirectionalEdge.algorithm_version == algorithm_version,
        DirectionalEdge.config_hash == config_hash,
    )
    existing = (
        await session.execute(select(DirectionalEdge).where(*identity))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    row = DirectionalEdge(
        edge_id=uuid.uuid4(),
        leader_wallet_id=edge.leader_wallet_id,
        follower_wallet_id=edge.follower_wallet_id,
        as_of=as_of,
        algorithm_version=algorithm_version,
        config_hash=config_hash,
        observation_count=edge.observation_count,
        tokens_leader_entered=edge.tokens_leader_entered,
        follower_base_rate=edge.follower_base_rate,
        median_lag_seconds=edge.median_lag_seconds,
        expected_follows=edge.expected_follows,
        lift=edge.lift,
        effect_size=edge.effect_size,
        p_value=edge.p_value,
        q_value=result.q_value,
        forward_information_after_leader_pct=forward_information_after_leader_pct,
        created_at=now,
    )
    stmt = (
        pg_insert(DirectionalEdge)
        .values(**_row_values(row, DirectionalEdge.__table__))
        .on_conflict_do_nothing(constraint="uq_directional_edges_identity")
        .returning(DirectionalEdge.edge_id)
    )
    inserted_id = (await session.execute(stmt)).scalar_one_or_none()
    if inserted_id is not None:
        return row, True

    return (await session.execute(select(DirectionalEdge).where(*identity))).scalar_one(), False

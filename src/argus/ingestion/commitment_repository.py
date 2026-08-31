"""Real, database-backed :class:`argus.ingestion.commitment.CommitmentObservationStore`.

Persists to ``commitment_observations`` (append-only; rows are never
updated or deleted by application code).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from argus.domain.commitment import CommitmentObservation
from argus.ingestion.commitment import CommitmentObservationDraft


def _to_dataclass(row: CommitmentObservation) -> CommitmentObservationDraft:
    return CommitmentObservationDraft(
        observation_id=row.observation_id,
        event_id=row.event_id,
        commitment_level=row.commitment_level,
        transaction_succeeded=row.transaction_succeeded,
        observed_at=row.observed_at,
        provider=row.provider,
        provider_received_at=row.provider_received_at,
        created_at=row.created_at,
    )


class SqlCommitmentObservationStore:
    """One instance per unit-of-work; callers manage the session lifetime."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_event(self, event_id: uuid.UUID) -> list[CommitmentObservationDraft]:
        result = await self._session.execute(
            select(CommitmentObservation)
            .where(CommitmentObservation.event_id == event_id)
            .order_by(CommitmentObservation.created_at)
        )
        return [_to_dataclass(row) for row in result.scalars().all()]

    async def append(self, observation: CommitmentObservationDraft) -> None:
        row = CommitmentObservation(
            observation_id=observation.observation_id,
            event_id=observation.event_id,
            commitment_level=observation.commitment_level,
            transaction_succeeded=observation.transaction_succeeded,
            observed_at=observation.observed_at,
            provider=observation.provider,
            provider_received_at=observation.provider_received_at,
            created_at=observation.created_at,
        )
        self._session.add(row)
        await self._session.flush()

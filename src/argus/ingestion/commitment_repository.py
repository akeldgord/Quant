"""Real, database-backed :class:`argus.ingestion.commitment.CommitmentObservationStore`.

Persists to ``commitment_observations`` (append-only; rows are never
updated or deleted by application code -- enforced at the role layer by
migration 0004, finding #6) plus ``commitment_observation_rejections``
(the append-only audit trail for a refused write, finding #5).

:meth:`SqlCommitmentObservationStore.lock` uses a Postgres transaction-
scoped advisory lock (``pg_advisory_xact_lock``) keyed by a hash of the
event id: it serializes every ``CommitmentTracker.record()`` call for the
same event across concurrent sessions/tasks without needing a row to
already exist to lock (append-only tables have nothing to
``SELECT ... FOR UPDATE`` on a first observation), and it releases
automatically at the end of the current transaction -- no explicit
unlock call, so it cannot be leaked by a crash or a cancelled task
between acquire and release. ``hashtext`` is a 32-bit hash, so two
different event ids may rarely collide onto the same lock key; this only
ever costs extra, harmless serialization between unrelated events, never
an incorrect result.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from argus.domain.commitment import CommitmentObservation, CommitmentObservationRejection
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
        sequence=row.sequence,
    )


class SqlCommitmentObservationStore:
    """One instance per unit-of-work; callers manage the session lifetime."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_event(self, event_id: uuid.UUID) -> list[CommitmentObservationDraft]:
        result = await self._session.execute(
            select(CommitmentObservation)
            .where(CommitmentObservation.event_id == event_id)
            .order_by(CommitmentObservation.sequence)
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

    async def append_rejection(
        self,
        *,
        event_id: uuid.UUID,
        attempted_commitment_level: str,
        attempted_transaction_succeeded: bool | None,
        attempted_observed_at: datetime,
        attempted_provider: str,
        reason: str,
        created_at: datetime,
    ) -> None:
        row = CommitmentObservationRejection(
            event_id=event_id,
            attempted_commitment_level=attempted_commitment_level,
            attempted_transaction_succeeded=attempted_transaction_succeeded,
            attempted_observed_at=attempted_observed_at,
            attempted_provider=attempted_provider,
            reason=reason[:512],
            created_at=created_at,
        )
        self._session.add(row)
        await self._session.flush()

    def lock(self, event_id: uuid.UUID) -> AbstractAsyncContextManager[None]:
        @asynccontextmanager
        async def _cm() -> AsyncIterator[None]:
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key)::bigint)"),
                {"key": str(event_id)},
            )
            yield

        return _cm()

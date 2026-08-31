"""Real, database-backed :class:`argus.ingestion.reconciliation.ReconciliationUnitOfWork`.

Phase 1 remediation round 2 (argus-phase-1-remediation-002), finding #2:
the live CLI previously created one ``AsyncSession`` and shared it across
every wallet task, periodic reconciliation, and every repository for the
whole process lifetime -- ``AsyncSession`` is a mutable unit of work and
is not safe for concurrent task use. ``SqlReconciliationUnitOfWork``
replaces that with a factory: every call opens a brand-new session
scoped to exactly one atomic operation (see
``ReconciliationEngine._process_one_item`` and friends), commits it on a
clean exit, and rolls it back on any exception -- a failure in one
wallet's item can never partially commit, and can never touch another
wallet's or another operation's pending work, because they were never
the same session to begin with.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from argus.ingestion.commitment_repository import SqlCommitmentObservationStore
from argus.ingestion.event_repository import SqlEventRecorder
from argus.ingestion.parse_attempt_repository import SqlParseAttemptRecorder
from argus.ingestion.reconciliation import ReconciliationRepos
from argus.ingestion.swap_repository import SqlSwapRecorder
from argus.ingestion.watermark_repository import SqlWatermarkStore


class SqlReconciliationUnitOfWork:
    """Callable unit-of-work factory wrapping an
    ``async_sessionmaker[AsyncSession]``. Each call:

    1. opens a new ``AsyncSession`` (a new pooled connection, not shared
       with any other in-flight operation);
    2. wraps the block in ``session.begin()`` -- SQLAlchemy commits on a
       clean exit and rolls back on any exception raised inside the
       ``async with`` block, ``asyncio.CancelledError`` included, since
       cancellation still runs ``__aexit__`` with exception info before
       propagating;
    3. always closes the session on the way out via the outer
       ``async with self._sessionmaker() as session:``, regardless of
       whether step 2 committed or rolled back.

    This is what makes "session rollback/closure is guaranteed on
    cancellation and exceptions" (finding #2) true by construction rather
    than by every caller remembering to do it.
    """

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[ReconciliationRepos]:
        async with self._sessionmaker() as session, session.begin():
            yield ReconciliationRepos(
                watermark_store=SqlWatermarkStore(session),
                event_recorder=SqlEventRecorder(session),
                commitment_store=SqlCommitmentObservationStore(session),
                swap_recorder=SqlSwapRecorder(session),
                parse_attempt_recorder=SqlParseAttemptRecorder(session),
                recent_event_source=SqlEventRecorder(session),
            )

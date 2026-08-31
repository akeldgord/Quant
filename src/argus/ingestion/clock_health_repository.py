"""Real, database-backed :class:`argus.ingestion.clock_monitor.ClockHealthRecorder`.

Persists to ``clock_health_events`` (MASTER_SPEC.md section 17) via an
injected SQLAlchemy async session and :class:`argus.clock.Clock`, so every
health comparison -- healthy or anomalous -- survives process restart.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from argus.clock import Clock, ClockHealth
from argus.domain.clock_health import ClockHealthEvent


class SqlClockHealthRecorder:
    """One instance per unit-of-work; callers manage the session lifetime
    (commit/rollback) the same way as elsewhere in this codebase."""

    def __init__(self, session: AsyncSession, *, clock: Clock) -> None:
        self._session = session
        self._clock = clock

    async def record(self, health: ClockHealth, *, sampled_at_monotonic: float) -> None:
        row = ClockHealthEvent(
            event_id=uuid.uuid4(),
            sampled_at=self._clock.utc_now(),
            monotonic_seconds=sampled_at_monotonic,
            wall_delta_seconds=health.wall_delta_seconds,
            monotonic_delta_seconds=health.monotonic_delta_seconds,
            drift_seconds=health.drift_seconds,
            healthy=health.healthy,
            reason=health.reason,
            created_at=self._clock.utc_now(),
        )
        self._session.add(row)
        await self._session.flush()

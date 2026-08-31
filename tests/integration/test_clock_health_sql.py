"""Integration test: `SqlClockHealthRecorder` + `PersistentClockMonitor`
against a real Postgres database (Phase 1 mandatory acceptance criterion
#10: "clock health and anomalies are stored").
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from argus.clock import Clock, ClockSample
from argus.config import load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.clock_health import ClockHealthEvent
from argus.ingestion.clock_health_repository import SqlClockHealthRecorder
from argus.ingestion.clock_monitor import PersistentClockMonitor

pytestmark = pytest.mark.asyncio


class _ScriptedClock(Clock):
    def __init__(self, samples: list[ClockSample], *, max_drift_seconds: float = 1.0) -> None:
        super().__init__(max_drift_seconds=max_drift_seconds)
        self._samples = iter(samples)

    def sample(self) -> ClockSample:
        return next(self._samples)


async def test_clock_health_and_anomaly_persist_to_real_database(admin_engine) -> None:
    config = load_config()
    ingest_info = connection_for_role(config, DbRole.INGEST)
    ingest_engine = create_async_engine(ingest_info.as_asyncpg_url())
    sessionmaker = async_sessionmaker(ingest_engine, expire_on_commit=False)

    t0 = datetime(2026, 1, 1, tzinfo=UTC)

    try:
        async with sessionmaker() as session:
            clock = _ScriptedClock(
                [
                    ClockSample(wall_time=t0, monotonic_seconds=100.0),
                    ClockSample(wall_time=t0 + timedelta(hours=1), monotonic_seconds=102.0),
                ],
                max_drift_seconds=1.0,
            )
            recorder = SqlClockHealthRecorder(session, clock=clock)
            monitor = PersistentClockMonitor(clock=clock, recorder=recorder)

            await monitor.tick()  # baseline, no comparison yet
            health = await monitor.tick()  # 1 hour wall jump vs 2s monotonic -> anomaly
            await session.commit()

        assert health is not None
        assert health.healthy is False

        async with sessionmaker() as session:
            rows = (await session.execute(select(ClockHealthEvent))).scalars().all()
            anomalous = [r for r in rows if not r.healthy]
            assert len(anomalous) >= 1
            row = anomalous[-1]
            assert row.healthy is False
            assert row.reason is not None
            assert row.drift_seconds > 1.0
    finally:
        async with admin_engine.connect() as conn:
            await conn.execute(text("DELETE FROM clock_health_events"))
            await conn.commit()
        await ingest_engine.dispose()

"""Tests for `argus.ingestion.clock_monitor.PersistentClockMonitor`
(Phase 1 mandatory acceptance criterion #10: "clock health and anomalies
are stored").
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from argus.clock import Clock, ClockSample
from argus.ingestion.clock_monitor import InMemoryClockHealthRecorder, PersistentClockMonitor


class _ScriptedClock(Clock):
    """Returns a fixed sequence of samples instead of real wall/monotonic
    time, so anomaly detection is exercised deterministically."""

    def __init__(self, samples: list[ClockSample], *, max_drift_seconds: float = 1.0) -> None:
        super().__init__(max_drift_seconds=max_drift_seconds)
        self._samples = iter(samples)

    def sample(self) -> ClockSample:
        return next(self._samples)


def _sample(wall_time: datetime, monotonic_seconds: float) -> ClockSample:
    return ClockSample(wall_time=wall_time, monotonic_seconds=monotonic_seconds)


async def test_first_tick_records_nothing_no_comparison_yet() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    clock = _ScriptedClock([_sample(t0, 100.0)])
    recorder = InMemoryClockHealthRecorder()
    monitor = PersistentClockMonitor(clock=clock, recorder=recorder)

    health = await monitor.tick()

    assert health is None
    assert recorder.records == []
    assert monitor.anomaly_detected is False


async def test_healthy_tick_is_persisted_and_no_anomaly() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    clock = _ScriptedClock(
        [_sample(t0, 100.0), _sample(t0 + timedelta(seconds=2), 102.0)], max_drift_seconds=1.0
    )
    recorder = InMemoryClockHealthRecorder()
    monitor = PersistentClockMonitor(clock=clock, recorder=recorder)

    await monitor.tick()
    health = await monitor.tick()

    assert health is not None
    assert health.healthy is True
    assert len(recorder.records) == 1
    assert recorder.records[0].healthy is True
    assert monitor.anomaly_detected is False


async def test_anomalous_tick_latches_and_is_persisted() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    clock = _ScriptedClock(
        [_sample(t0, 100.0), _sample(t0 + timedelta(hours=1), 102.0)], max_drift_seconds=1.0
    )
    recorder = InMemoryClockHealthRecorder()
    monitor = PersistentClockMonitor(clock=clock, recorder=recorder)

    await monitor.tick()
    health = await monitor.tick()

    assert health is not None
    assert health.healthy is False
    assert monitor.anomaly_detected is True
    assert len(recorder.records) == 1
    assert recorder.records[0].healthy is False
    assert recorder.records[0].reason is not None


async def test_acknowledge_clears_anomaly_but_does_not_erase_the_persisted_record() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    clock = _ScriptedClock(
        [_sample(t0, 100.0), _sample(t0 + timedelta(hours=1), 102.0)], max_drift_seconds=1.0
    )
    recorder = InMemoryClockHealthRecorder()
    monitor = PersistentClockMonitor(clock=clock, recorder=recorder)
    await monitor.tick()
    await monitor.tick()
    assert monitor.anomaly_detected is True

    monitor.acknowledge()

    assert monitor.anomaly_detected is False
    assert len(recorder.records) == 1  # the anomaly is still durably on record

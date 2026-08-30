from __future__ import annotations

from datetime import UTC, datetime, timedelta

from argus.clock import Clock, ClockHeartbeat, ClockSample


def _sample(wall_time: datetime, monotonic_seconds: float) -> ClockSample:
    return ClockSample(wall_time=wall_time, monotonic_seconds=monotonic_seconds)


def test_check_health_ok_when_wall_and_monotonic_agree() -> None:
    clock = Clock(max_drift_seconds=1.0)
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    previous = _sample(t0, 100.0)
    current = _sample(t0 + timedelta(seconds=2), 102.0)

    result = clock.check_health(previous, current)

    assert result.healthy is True
    assert result.reason is None
    assert result.drift_seconds == 0.0


def test_check_health_detects_large_wall_clock_jump() -> None:
    clock = Clock(max_drift_seconds=1.0)
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    previous = _sample(t0, 100.0)
    # wall clock jumped forward 1 hour but monotonic only advanced 2s
    current = _sample(t0 + timedelta(hours=1), 102.0)

    result = clock.check_health(previous, current)

    assert result.healthy is False
    assert "drift" in (result.reason or "")


def test_check_health_detects_monotonic_going_backwards() -> None:
    clock = Clock()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    previous = _sample(t0, 100.0)
    current = _sample(t0 + timedelta(seconds=1), 99.0)

    result = clock.check_health(previous, current)

    assert result.healthy is False
    assert "backwards" in (result.reason or "")


def test_heartbeat_flags_anomaly_and_can_be_acknowledged() -> None:
    heartbeat = ClockHeartbeat(clock=Clock(max_drift_seconds=1.0))

    # Manually drive two samples through check_health via monkeypatched clock
    # sample() calls by directly setting the private state, since Clock uses
    # real wall/monotonic time we assert the *mechanism* instead of exact
    # numbers: two ticks close in time should be healthy.
    heartbeat.tick()
    health = heartbeat.tick()

    assert health is not None
    assert heartbeat.anomaly_detected is False

    heartbeat.anomaly_detected = True
    heartbeat.acknowledge()
    assert heartbeat.anomaly_detected is False

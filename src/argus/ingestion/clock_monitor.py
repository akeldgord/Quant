"""Durable clock-anomaly monitoring wired into truth-path reconciliation
(MASTER_SPEC.md section 17 + section 19).

:class:`argus.clock.ClockHeartbeat` already latches an in-memory
``anomaly_detected`` flag from consecutive wall/monotonic samples.
:class:`PersistentClockMonitor` wraps it to (a) persist every comparison
so anomalies are auditable after the fact, not just a transient flag, and
(b) is the thing :class:`argus.ingestion.reconciliation.ReconciliationEngine`
consults so a wallet cannot be reported live-entry-eligible again purely
because one reconciliation succeeded -- section 17 requires clock health
recovery as an independent, additional condition alongside provider
reconnection and chain reconciliation.
"""

from __future__ import annotations

from typing import Protocol

from argus.clock import Clock, ClockHealth, ClockHeartbeat


class ClockHealthRecorder(Protocol):
    """Persists one clock health comparison. A real implementation backs
    onto ``clock_health_events``; a fake for tests is a plain in-memory
    list."""

    async def record(self, health: ClockHealth, *, sampled_at_monotonic: float) -> None: ...


class PersistentClockMonitor:
    """Ticks a :class:`ClockHeartbeat` and persists every comparison via an
    injected :class:`ClockHealthRecorder`, so "clock health and anomalies
    are stored" (Phase 1 mandatory acceptance criterion #10) is true of the
    database, not merely of process memory that a restart would erase."""

    def __init__(self, *, clock: Clock, recorder: ClockHealthRecorder) -> None:
        self._heartbeat = ClockHeartbeat(clock=clock)
        self._recorder = recorder

    @property
    def anomaly_detected(self) -> bool:
        return self._heartbeat.anomaly_detected

    async def tick(self) -> ClockHealth | None:
        health = self._heartbeat.tick()
        if health is not None:
            sample = self._heartbeat.last_sample
            assert sample is not None  # tick() always sets it once health is non-None
            await self._recorder.record(health, sampled_at_monotonic=sample.monotonic_seconds)
        return health

    def acknowledge(self) -> None:
        """Clear the anomaly latch -- callers must independently have
        already re-established provider connectivity and completed a
        successful chain reconciliation; this alone is only the "clock
        health recovered" leg of the three-part gate in section 17."""
        self._heartbeat.acknowledge()


class InMemoryClockHealthRecorder:
    """Test double: keeps every recorded :class:`ClockHealth` in a list."""

    def __init__(self) -> None:
        self.records: list[ClockHealth] = []

    async def record(self, health: ClockHealth, *, sampled_at_monotonic: float) -> None:
        del sampled_at_monotonic  # not needed by the in-memory fake
        self.records.append(health)


__all__ = ["ClockHealthRecorder", "PersistentClockMonitor", "InMemoryClockHealthRecorder"]

"""UTC wall-clock + monotonic clock abstraction (MASTER_SPEC.md section 17).

Every timestamp ARGUS persists must come from :func:`Clock.utc_now`, and every
latency/duration measurement must come from :func:`Clock.monotonic`, so that
clock-anomaly detection has exactly one place to live. Domain code should
never call ``datetime.utcnow()`` or ``time.monotonic()`` directly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class ClockSample:
    """A paired wall-clock / monotonic reading taken at the same instant."""

    wall_time: datetime
    monotonic_seconds: float


@dataclass(frozen=True, slots=True)
class ClockHealth:
    """Result of comparing two samples for anomalies (section 17)."""

    healthy: bool
    wall_delta_seconds: float
    monotonic_delta_seconds: float
    drift_seconds: float
    reason: str | None = None


class Clock:
    """The single source of truth for "now" in ARGUS.

    ``max_drift_seconds`` bounds how far wall-clock elapsed time may diverge
    from monotonic elapsed time between two samples before the pair is
    considered a clock anomaly (host suspend/resume, large NTP step, etc.).
    """

    def __init__(self, max_drift_seconds: float = 5.0) -> None:
        self.max_drift_seconds = max_drift_seconds

    def utc_now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    def sample(self) -> ClockSample:
        return ClockSample(wall_time=self.utc_now(), monotonic_seconds=self.monotonic())

    def check_health(self, previous: ClockSample, current: ClockSample) -> ClockHealth:
        """Compare two samples taken over the same real interval.

        If wall-clock elapsed time and monotonic elapsed time disagree by more
        than ``max_drift_seconds``, the interval is flagged unhealthy. Callers
        (e.g. a heartbeat loop) are expected to react to an unhealthy result
        per section 17: disable new live entries, reconnect providers,
        reconcile chain state, verify clock health, and only then resume.
        """
        wall_delta = (current.wall_time - previous.wall_time).total_seconds()
        mono_delta = current.monotonic_seconds - previous.monotonic_seconds
        drift = wall_delta - mono_delta
        healthy = abs(drift) <= self.max_drift_seconds and mono_delta >= 0
        reason = None
        if mono_delta < 0:
            reason = "monotonic clock moved backwards"
        elif not healthy:
            reason = f"wall/monotonic drift {drift:.3f}s exceeds {self.max_drift_seconds:.3f}s"
        return ClockHealth(
            healthy=healthy,
            wall_delta_seconds=wall_delta,
            monotonic_delta_seconds=mono_delta,
            drift_seconds=drift,
            reason=reason,
        )


@dataclass
class ClockHeartbeat:
    """Tracks consecutive clock samples to detect anomalies over time.

    Intended to be polled periodically (e.g. once per second) by a
    long-running process. A single unhealthy comparison is enough to flip
    :attr:`anomaly_detected`; callers must clear it explicitly (typically
    after completing the resume/reconciliation sequence in section 83)
    via :meth:`acknowledge`.
    """

    clock: Clock = field(default_factory=Clock)
    _last: ClockSample | None = field(default=None, init=False, repr=False)
    anomaly_detected: bool = field(default=False, init=False)
    last_health: ClockHealth | None = field(default=None, init=False)

    def tick(self) -> ClockHealth | None:
        current = self.clock.sample()
        if self._last is None:
            self._last = current
            return None
        health = self.clock.check_health(self._last, current)
        self._last = current
        self.last_health = health
        if not health.healthy:
            self.anomaly_detected = True
        return health

    def acknowledge(self) -> None:
        """Clear a detected anomaly after successful reconciliation."""
        self.anomaly_detected = False

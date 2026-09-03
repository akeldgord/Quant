"""argus.executor.reconciliation — MASTER_SPEC.md section 83 (HOST
SUSPEND / RESUME), Phase 6 (``argus-phase-6-001``).

If the host sleeps, hibernates, pauses, or exhibits a major scheduling
discontinuity, new entries auto-disarm immediately. On resume, ALL
seven required dimensions -- clock, streams, tracked-wallet watermarks,
live positions, executor wallet balance, provider health, and open
orders/intents -- must independently report ``HEALTHY`` before new
live entry may resume; a partial recovery (even six of seven healthy)
still blocks new entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

DimensionStatus = Literal["HEALTHY", "UNHEALTHY", "PENDING"]

DIMENSION_CLOCK = "clock"
DIMENSION_STREAMS = "streams"
DIMENSION_WATERMARKS = "tracked_wallet_watermarks"
DIMENSION_POSITIONS = "live_positions"
DIMENSION_BALANCE = "executor_wallet_balance"
DIMENSION_PROVIDER_HEALTH = "provider_health"
DIMENSION_OPEN_ORDERS = "open_orders_intents"

ALL_DIMENSIONS: tuple[str, ...] = (
    DIMENSION_CLOCK,
    DIMENSION_STREAMS,
    DIMENSION_WATERMARKS,
    DIMENSION_POSITIONS,
    DIMENSION_BALANCE,
    DIMENSION_PROVIDER_HEALTH,
    DIMENSION_OPEN_ORDERS,
)


def detect_discontinuity(*, observed_gap: timedelta, max_allowed_gap: timedelta) -> bool:
    """True means a major scheduling discontinuity occurred (host
    suspend/resume or equivalent) -- callers must AUTO-DISARM new
    entries immediately when this is true."""
    return observed_gap > max_allowed_gap


@dataclass(frozen=True)
class ReconciliationChecklist:
    statuses: dict[str, DimensionStatus]

    @property
    def fully_healthy(self) -> bool:
        return all(self.statuses.get(d) == "HEALTHY" for d in ALL_DIMENSIONS)

    @property
    def unhealthy_or_pending(self) -> tuple[str, ...]:
        return tuple(d for d in ALL_DIMENSIONS if self.statuses.get(d) != "HEALTHY")


def may_resume_new_entries(checklist: ReconciliationChecklist) -> bool:
    """Only ``True`` once every required dimension independently
    reports ``HEALTHY`` -- a partial recovery never re-enables new
    entries."""
    return checklist.fully_healthy

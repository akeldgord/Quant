"""``clock_health_events`` — durable record of every wall/monotonic clock
comparison and any detected anomaly (MASTER_SPEC.md section 17; Phase 1
mandatory acceptance criterion #10, "clock health and anomalies are
stored").

``argus.clock.ClockHeartbeat`` already detects an anomaly in memory
(``anomaly_detected``); this table is the durable side of that -- so a
clock anomaly is independently auditable after the fact, not just a
transient in-process flag that vanishes on restart.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base


class ClockHealthEvent(Base):
    """One wall/monotonic clock comparison, healthy or anomalous."""

    __tablename__ = "clock_health_events"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    monotonic_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    wall_delta_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    monotonic_delta_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    drift_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    healthy: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(256), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

"""``risk_exit_events`` — MASTER_SPEC.md section 67 (INDEPENDENT RISK
EXITS), Phase 6 (``argus-phase-6-001``).

Audited record of every independently-triggered risk exit
(``argus.executor.risk_exits``) -- maximum position loss, liquidity
collapse, token-risk-state change, maximum daily loss, maximum
aggregate exposure, and operator emergency exit. Never depends on
source-wallet (leader) sell evidence.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

TRIGGER_MAX_POSITION_LOSS = "MAX_POSITION_LOSS"
TRIGGER_LIQUIDITY_COLLAPSE = "LIQUIDITY_COLLAPSE"
TRIGGER_TOKEN_RISK_STATE_CHANGE = "TOKEN_RISK_STATE_CHANGE"
TRIGGER_MAX_DAILY_LOSS = "MAX_DAILY_LOSS"
TRIGGER_MAX_AGGREGATE_EXPOSURE = "MAX_AGGREGATE_EXPOSURE"
TRIGGER_OPERATOR_EMERGENCY_EXIT = "OPERATOR_EMERGENCY_EXIT"

TRIGGER_TYPES: tuple[str, ...] = (
    TRIGGER_MAX_POSITION_LOSS,
    TRIGGER_LIQUIDITY_COLLAPSE,
    TRIGGER_TOKEN_RISK_STATE_CHANGE,
    TRIGGER_MAX_DAILY_LOSS,
    TRIGGER_MAX_AGGREGATE_EXPOSURE,
    TRIGGER_OPERATOR_EMERGENCY_EXIT,
)
_TRIGGER_TYPES_SQL = ", ".join(f"'{t}'" for t in TRIGGER_TYPES)


class RiskExitEvent(Base):
    __tablename__ = "risk_exit_events"
    __table_args__ = (
        CheckConstraint(
            f"trigger_type IN ({_TRIGGER_TYPES_SQL})", name="ck_risk_exit_events_trigger_type"
        ),
    )

    risk_exit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live_positions.position_id"), nullable=False, index=True
    )
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

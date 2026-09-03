"""``live_positions`` — MASTER_SPEC.md section 65 (ONE OPEN POSITION PER
MINT DEFAULT), Phase 6 (``argus-phase-6-001``).

At most one ``OPEN`` row may ever exist per ``token_id`` -- enforced by
a partial unique index (``WHERE status = 'OPEN'``, see migration
``0024``), the actual database-level backstop behind
``ALLOW_AUTOMATIC_SCALE_IN = false`` (``argus.executor.position_
policy``): a second automatic buy for the same mint cannot be
represented no matter what application logic does.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

STATUS_OPEN = "OPEN"
STATUS_CLOSED = "CLOSED"
STATUSES: tuple[str, ...] = (STATUS_OPEN, STATUS_CLOSED)


class LivePosition(Base):
    __tablename__ = "live_positions"
    __table_args__ = (
        UniqueConstraint("opening_intent_id", name="uq_live_positions_opening_intent_id"),
        CheckConstraint("status IN ('OPEN', 'CLOSED')", name="ck_live_positions_status"),
        CheckConstraint(
            "(status = 'OPEN' AND closed_at IS NULL) OR "
            "(status = 'CLOSED' AND closed_at IS NOT NULL)",
            name="ck_live_positions_closed_at_matches_status",
        ),
    )

    position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=False, index=True
    )
    opening_intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_intents.intent_id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

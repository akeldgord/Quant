"""``archaeology_triggers`` — bounded, idempotent record of "ARGUS decided
to run archaeology on this token" (MASTER_SPEC.md Phase 2 build item 11
"automatic archaeology trigger"; required-implementation item 6).

Automatic archaeology here means automatic creation/execution of a
*research job* inside the Phase 2 system -- never a trade, quote, order,
or live execution action (this instruction's explicit distinction).

Two partial-unique indexes (declared in the owning migration, not here --
Postgres partial indexes aren't expressible as a plain SQLAlchemy
``UniqueConstraint``) enforce idempotency per trigger type:

- at most one ``HISTORICAL_WINNER`` trigger per token (a human/CLI asked
  ARGUS to study a specific already-known historical winner once);
- at most one ``PROSPECTIVE_WINNER`` trigger per
  ``(token_id, source_milestone_id)`` pair -- a token crossing the SAME
  versioned milestone twice (e.g. a replayed observation) must never
  create a second trigger, but crossing a *different* category
  (``MONSTER`` after ``MAJOR_WINNER``) legitimately creates a second one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

TRIGGER_TYPE_HISTORICAL_WINNER = "HISTORICAL_WINNER"
TRIGGER_TYPE_PROSPECTIVE_WINNER = "PROSPECTIVE_WINNER"

TRIGGER_TYPES: tuple[str, ...] = (TRIGGER_TYPE_HISTORICAL_WINNER, TRIGGER_TYPE_PROSPECTIVE_WINNER)


class ArchaeologyTrigger(Base):
    """One bounded, idempotent instruction to run (or queue) one
    archaeology run for one token."""

    __tablename__ = "archaeology_triggers"
    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ('HISTORICAL_WINNER', 'PROSPECTIVE_WINNER')",
            name="ck_archaeology_triggers_trigger_type",
        ),
        CheckConstraint(
            "(trigger_type = 'PROSPECTIVE_WINNER') = (source_milestone_id IS NOT NULL)",
            name="ck_archaeology_triggers_prospective_has_milestone",
        ),
    )

    trigger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=False, index=True
    )

    trigger_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    source_milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("token_winner_milestones.milestone_id"), nullable=True
    )
    trigger_reason: Mapped[str] = mapped_column(String(256), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    # Set once an archaeology_runs row has been created from this trigger.
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

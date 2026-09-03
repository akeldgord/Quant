"""``execution_intents`` — MASTER_SPEC.md section 76 (EXECUTION STATE
MACHINE) and section 77 (EXECUTION IDEMPOTENCY), Phase 6
(``argus-phase-6-001``).

One row per live trade intent, carrying the frozen 11-state machine
(``argus.executor.state_machine``) and a unique ``idempotency_
fingerprint`` (``argus.executor.idempotency``) that makes a restart/
replay structurally unable to create two rows for the same semantic
intent -- the database's own unique constraint is the final backstop,
not merely an application-level check.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base
from argus.domain.identity_mixin import FullIdentityMixin, full_identity_check_constraints

SIDE_BUY = "BUY"
SIDE_SELL = "SELL"
SIDES: tuple[str, ...] = (SIDE_BUY, SIDE_SELL)

STATE_CREATED = "CREATED"
STATE_VALIDATING = "VALIDATING"
STATE_REJECTED = "REJECTED"
STATE_ORDER_REQUESTED = "ORDER_REQUESTED"
STATE_ORDER_READY = "ORDER_READY"
STATE_ATTESTING = "ATTESTING"
STATE_SIGNED = "SIGNED"
STATE_SUBMITTED = "SUBMITTED"
STATE_CONFIRMED = "CONFIRMED"
STATE_FAILED = "FAILED"
STATE_UNKNOWN = "UNKNOWN"

EXECUTION_STATES: tuple[str, ...] = (
    STATE_CREATED,
    STATE_VALIDATING,
    STATE_REJECTED,
    STATE_ORDER_REQUESTED,
    STATE_ORDER_READY,
    STATE_ATTESTING,
    STATE_SIGNED,
    STATE_SUBMITTED,
    STATE_CONFIRMED,
    STATE_FAILED,
    STATE_UNKNOWN,
)
_STATES_SQL = ", ".join(f"'{s}'" for s in EXECUTION_STATES)


class ExecutionIntent(FullIdentityMixin, Base):
    """One live trade intent and its current state-machine position."""

    __tablename__ = "execution_intents"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_fingerprint", name="uq_execution_intents_idempotency_fingerprint"
        ),
        CheckConstraint(f"side IN ('{SIDE_BUY}', '{SIDE_SELL}')", name="ck_execution_intents_side"),
        CheckConstraint(f"state IN ({_STATES_SQL})", name="ck_execution_intents_state"),
        CheckConstraint("notional_input_raw > 0", name="ck_execution_intents_notional_positive"),
        CheckConstraint(
            "length(idempotency_fingerprint) > 0",
            name="ck_execution_intents_fingerprint_nonempty",
        ),
        *full_identity_check_constraints("execution_intents"),
    )

    intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    prospective_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prospective_events.prospective_event_id"), nullable=True
    )
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=False, index=True
    )
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quote_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    notional_input_raw: Mapped[int] = mapped_column(BigInteger, nullable=False)

    state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    idempotency_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

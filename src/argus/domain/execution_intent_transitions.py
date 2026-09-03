"""``execution_intent_transitions`` — MASTER_SPEC.md section 76
("Transitions are transactional and audited"), Phase 6
(``argus-phase-6-001``).

Append-only audit trail of every state-machine transition an
:class:`~argus.domain.execution_intents.ExecutionIntent` ever makes --
never updated or deleted, mirroring ``argus.domain.parse_attempts``'s
established append-only decision-ledger convention.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base
from argus.domain.execution_intents import EXECUTION_STATES

_TO_STATES_SQL = ", ".join(f"'{s}'" for s in EXECUTION_STATES)


class ExecutionIntentTransition(Base):
    __tablename__ = "execution_intent_transitions"
    __table_args__ = (
        CheckConstraint(
            f"to_state IN ({_TO_STATES_SQL})", name="ck_execution_intent_transitions_to_state"
        ),
        CheckConstraint(
            "length(reason) > 0", name="ck_execution_intent_transitions_reason_nonempty"
        ),
    )

    transition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_intents.intent_id"), nullable=False, index=True
    )
    from_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_state: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

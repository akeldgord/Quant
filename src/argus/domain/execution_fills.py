"""``execution_fills`` — MASTER_SPEC.md section 79 (ACTUAL FILL
ACCOUNTING), Phase 6 (``argus-phase-6-001``), evidence-reference columns
added by FSR-02 (``argus-final-spec-recovery-001``).

Quoted/simulated/actual input/output plus network fee, priority fee,
tip, and rent/account costs, kept as separate columns so the confirmed
on-chain value can win without discarding the quote/simulation
provenance (``argus.executor.fill_accounting``). Any value not yet
evidenced stays ``NULL`` -- never fabricated from an earlier-stage
value.

``transaction_signature``/``slot``/``confirmation_state`` (migration
``0037``) record exactly WHICH confirmed transaction the ``actual_*``
evidence came from and at what commitment level -- proof the row's
"actual" values are real chain evidence, not a re-labeled quote. A fill
row is created at submission time with only quoted/simulated evidence and
``confirmation_state IS NULL``; ``argus.executor.confirmation`` then
updates it in place (``updated_at``) as ambiguous/pending chain state
resolves, never regressing to a weaker confirmation level once evidenced.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base


class ExecutionFill(Base):
    __tablename__ = "execution_fills"
    __table_args__ = (
        UniqueConstraint("intent_id", name="uq_execution_fills_intent_id"),
        CheckConstraint(
            "confirmation_state IN ('UNKNOWN', 'PROCESSED', 'CONFIRMED', 'FINALIZED', 'FAILED') "
            "OR confirmation_state IS NULL",
            name="ck_execution_fills_confirmation_state",
        ),
    )

    fill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_intents.intent_id"), nullable=False
    )

    quoted_input_raw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    quoted_output_raw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    simulated_input_raw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    simulated_output_raw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actual_input_raw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actual_output_raw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    network_fee_raw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    priority_fee_raw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tip_raw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rent_raw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    transaction_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    slot: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    confirmation_state: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

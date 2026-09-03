"""``execution_fills`` — MASTER_SPEC.md section 79 (ACTUAL FILL
ACCOUNTING), Phase 6 (``argus-phase-6-001``).

Quoted/simulated/actual input/output plus network fee, priority fee,
tip, and rent/account costs, kept as separate columns so the confirmed
on-chain value can win without discarding the quote/simulation
provenance (``argus.executor.fill_accounting``). Any value not yet
evidenced stays ``NULL`` -- never fabricated from an earlier-stage
value.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base


class ExecutionFill(Base):
    __tablename__ = "execution_fills"
    __table_args__ = (UniqueConstraint("intent_id", name="uq_execution_fills_intent_id"),)

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

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

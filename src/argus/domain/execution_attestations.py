"""``execution_attestations`` — MASTER_SPEC.md section 78 (TRANSACTION
ATTESTATION BEFORE SIGNING), Phase 6 (``argus-phase-6-001``).

One row per attestation dimension checked for one intent
(``argus.executor.attestation``) -- signer identity, wallet identity,
input mint, output mint, amount, user-controlled asset outflows,
fee/tip/rent ceiling, and simulated-balance-change inspection. The
signer is never called unless every dimension for that intent is
``PASS``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

RESULT_PASS = "PASS"
RESULT_FAIL = "FAIL"
RESULTS: tuple[str, ...] = (RESULT_PASS, RESULT_FAIL)


class ExecutionAttestation(Base):
    __tablename__ = "execution_attestations"
    __table_args__ = (
        CheckConstraint("result IN ('PASS', 'FAIL')", name="ck_execution_attestations_result"),
        CheckConstraint(
            "length(dimension) > 0", name="ck_execution_attestations_dimension_nonempty"
        ),
    )

    attestation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_intents.intent_id"), nullable=False, index=True
    )
    dimension: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

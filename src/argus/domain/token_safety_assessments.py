"""``token_safety_assessments`` — MASTER_SPEC.md section 68 (TOKEN
SAFETY GATE), Phase 6 (``argus-phase-6-001``).

Stores ``token_risk_flags``/``token_risk_version`` exactly as section 68
requires. Unknown dangerous token mechanics (``overall_status =
'UNKNOWN'``) block auto-live eligibility exactly like an explicit
``'UNSAFE'`` -- see ``argus.executor.token_safety``. No safety screen
here is ever described as a guarantee.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

OVERALL_SAFE = "SAFE"
OVERALL_UNSAFE = "UNSAFE"
OVERALL_UNKNOWN = "UNKNOWN"
OVERALL_STATUSES: tuple[str, ...] = (OVERALL_SAFE, OVERALL_UNSAFE, OVERALL_UNKNOWN)


class TokenSafetyAssessment(Base):
    __tablename__ = "token_safety_assessments"
    __table_args__ = (
        CheckConstraint(
            "overall_status IN ('SAFE', 'UNSAFE', 'UNKNOWN')",
            name="ck_token_safety_assessments_overall_status",
        ),
        CheckConstraint(
            "length(token_risk_version) > 0",
            name="ck_token_safety_assessments_version_nonempty",
        ),
    )

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=False, index=True
    )
    # {"mint_authority": "PASS"|"FAIL"|"UNKNOWN", "freeze_authority": ...,
    #  "token_2022_extensions": ..., "transfer_fees": ...,
    #  "unsupported_transfer_behavior": ..., "supply_concentration": ...,
    #  "extreme_liquidity_weakness": ..., "suspicious_mutability": ...}
    token_risk_flags: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    token_risk_version: Mapped[str] = mapped_column(String(32), nullable=False)
    overall_status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

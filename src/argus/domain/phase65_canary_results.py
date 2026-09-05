"""``phase65_canary_results`` — Clarification-002
(``argus-final-spec-recovery-002-clarification-002``) section 2: the
persisted evidence a genuinely successful, human-authorized Phase 6.5
canary produces -- and the ONLY thing that can ever let ordinary
single-intent execution construct ``LiveRiskInputs.canary_passed=True``
afterward (``argus.executor.persistence.load_passed_canary_result_for_
identity``). A row here is never created for a failed/rejected/unresolved
canary attempt -- only after the pipeline reaches a genuine on-chain
``CONFIRMED`` success for an intent that was itself run under a real,
external, human-authored, hash/expiry-bound canary-authorization file
(``argus.executor.canary``), never a repository default or a generic
operator params-file boolean.

Bound to the exact running identity (``approved_git_commit``/
``approved_executor_build_hash``/``approved_risk_config_hash``) that
produced it -- a canary pass recorded under one build/config identity
never silently authorizes live execution under a DIFFERENT one; a
material code/config change requires a fresh canary, never a stale
carried-over pass.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base


class Phase65CanaryResult(Base):
    __tablename__ = "phase65_canary_results"
    __table_args__ = (
        UniqueConstraint("intent_id", name="uq_phase65_canary_results_intent_id"),
        CheckConstraint(
            "length(transaction_signature) > 0",
            name="ck_phase65_canary_results_signature_nonempty",
        ),
        CheckConstraint(
            "length(approved_git_commit) > 0",
            name="ck_phase65_canary_results_git_commit_nonempty",
        ),
        CheckConstraint(
            "length(approved_executor_build_hash) > 0",
            name="ck_phase65_canary_results_build_hash_nonempty",
        ),
        CheckConstraint(
            "length(approved_risk_config_hash) > 0",
            name="ck_phase65_canary_results_config_hash_nonempty",
        ),
    )

    canary_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_intents.intent_id"), nullable=False
    )
    transaction_signature: Mapped[str] = mapped_column(String(128), nullable=False)

    approved_git_commit: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_executor_build_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_risk_config_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

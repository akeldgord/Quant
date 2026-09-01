"""``archaeology_runs`` — the actual execution record of one historical or
prospective archaeology job (MASTER_SPEC.md Phase 2 build items 9/11;
required-implementation item 4).

Every run persists its own token, input evidence set, provider/source,
time range, algorithm/config/git identity, known gaps, completeness
statement, winner-definition/baseline version, and terminal status --
this is the audit trail required-implementation item 4 and required test
P2-T4/P2-T8 check against, not merely a log line. A partial unique index
on ``trigger_id`` (declared in the owning migration; ``NULL`` for a
directly CLI-invoked historical run with no watcher trigger) prevents two
concurrent workers from double-delivering the same trigger into two runs
(P2-T10) -- a manual/historical retry legitimately creates a second run
row (``trigger_id IS NULL`` rows are unconstrained), but its *outputs*
(``early_buyers`` etc.) must still not duplicate, which is enforced by
those tables' own idempotency keys, not by this table refusing a retry.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base
from argus.domain.archaeology_triggers import TRIGGER_TYPES
from argus.domain.identity_mixin import FullIdentityMixin, full_identity_check_constraints

RUN_STATUS_RUNNING = "RUNNING"
RUN_STATUS_COMPLETED = "COMPLETED"
RUN_STATUS_FAILED = "FAILED"
RUN_STATUS_PARTIAL = "PARTIAL"

RUN_STATUSES: tuple[str, ...] = (
    RUN_STATUS_RUNNING,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_PARTIAL,
)

_RUN_TYPE_LIST_SQL = ", ".join(f"'{t}'" for t in TRIGGER_TYPES)
_RUN_STATUS_LIST_SQL = ", ".join(f"'{s}'" for s in RUN_STATUSES)


class ArchaeologyRun(FullIdentityMixin, Base):
    """One execution (successful, partial, or failed) of the historical or
    prospective archaeology job for one token."""

    __tablename__ = "archaeology_runs"
    __table_args__ = (
        CheckConstraint(f"run_type IN ({_RUN_TYPE_LIST_SQL})", name="ck_archaeology_runs_type"),
        CheckConstraint(f"status IN ({_RUN_STATUS_LIST_SQL})", name="ck_archaeology_runs_status"),
        CheckConstraint(
            "length(input_evidence_reference) > 0",
            name="ck_archaeology_runs_input_evidence_reference_nonempty",
        ),
        CheckConstraint(
            "length(completeness_statement) > 0",
            name="ck_archaeology_runs_completeness_statement_nonempty",
        ),
        *full_identity_check_constraints("archaeology_runs"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=False, index=True
    )
    trigger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("archaeology_triggers.trigger_id"), nullable=True
    )

    run_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    source_provider_set: Mapped[str] = mapped_column(String(256), nullable=False)
    time_range_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    time_range_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_evidence_reference: Mapped[str] = mapped_column(String(256), nullable=False)

    known_gaps: Mapped[str | None] = mapped_column(Text, nullable=True)
    completeness_statement: Mapped[str] = mapped_column(Text, nullable=False)
    winner_definition_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)

    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

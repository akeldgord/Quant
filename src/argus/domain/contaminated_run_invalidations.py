"""``contaminated_run_invalidations`` — FSR-13 (``argus-final-spec-
recovery-001``): CORE-002 forbids deleting or rewriting evidence, so the
derived Phase 8-11 rows produced by the known-leaky algorithm versions at
or before ``TARGET_COMMIT`` are never touched, dropped, or relabeled.
Instead this is a small, deterministic, migration-seeded REGISTRY: one row
per (phase, contaminated algorithm_version) pair, naming the corrected
algorithm_version that supersedes it and the reason it was contaminated.

Every Phase 8-11 CLI report already filters its own table by the CURRENT
``ALGORITHM_VERSION`` module constant (never by "the newest row"), so a
version bump alone already excludes old-version rows from a DEFAULT
report -- this registry is the "explicit persisted state/reason" FSR-13
requires ON TOP of that: an old row is never silently dropped (CORE-002),
it stays fully queryable by its own ``algorithm_version``, and this table
is the audit trail explaining WHY it is excluded and WHAT superseded it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

STATUS_INVALID_FOR_EVALUATION = "INVALID_FOR_EVALUATION"
STATUS_SUPERSEDED = "SUPERSEDED"

STATUSES: tuple[str, ...] = (STATUS_INVALID_FOR_EVALUATION, STATUS_SUPERSEDED)

PHASE_8_CONVERGENCE = "PHASE_8_CONVERGENCE"
PHASE_9_COUNTERFACTUAL = "PHASE_9_COUNTERFACTUAL"
PHASE_10_SYNTHETIC = "PHASE_10_SYNTHETIC"
PHASE_11_PREDICTION = "PHASE_11_PREDICTION"

PHASES: tuple[str, ...] = (
    PHASE_8_CONVERGENCE,
    PHASE_9_COUNTERFACTUAL,
    PHASE_10_SYNTHETIC,
    PHASE_11_PREDICTION,
)


class ContaminatedRunInvalidation(Base):
    __tablename__ = "contaminated_run_invalidations"
    __table_args__ = (
        UniqueConstraint(
            "phase_name",
            "invalidated_algorithm_version",
            name="uq_contaminated_run_invalidations_identity",
        ),
        CheckConstraint(
            "phase_name IN ('PHASE_8_CONVERGENCE', 'PHASE_9_COUNTERFACTUAL', "
            "'PHASE_10_SYNTHETIC', 'PHASE_11_PREDICTION')",
            name="ck_contaminated_run_invalidations_phase_name",
        ),
        CheckConstraint(
            "status IN ('INVALID_FOR_EVALUATION', 'SUPERSEDED')",
            name="ck_contaminated_run_invalidations_status",
        ),
        CheckConstraint(
            "length(invalidated_algorithm_version) > 0",
            name="ck_contaminated_run_invalidations_invalidated_version_nonempty",
        ),
        CheckConstraint(
            "superseded_by_algorithm_version IS NULL "
            "OR length(superseded_by_algorithm_version) > 0",
            name="ck_contaminated_run_invalidations_superseded_version_nonempty",
        ),
        CheckConstraint(
            "invalidated_algorithm_version != superseded_by_algorithm_version",
            name="ck_contaminated_run_invalidations_distinct_versions",
        ),
        CheckConstraint(
            "length(reason) > 0", name="ck_contaminated_run_invalidations_reason_nonempty"
        ),
        CheckConstraint(
            "length(target_commit) = 40", name="ck_contaminated_run_invalidations_target_commit_sha"
        ),
    )

    invalidation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    phase_name: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # 64, not 32 -- this table names a phase's OWN algorithm_version
    # column value (some of which pre-date the FSR-07 width fix and are
    # themselves wider than 32; this registry must be able to name any
    # historical version, not only ones already narrow enough to fit its
    # source column).
    invalidated_algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # NULL only if a contaminated version is retired with no direct
    # successor yet -- every FSR-13 seed row has one.
    superseded_by_algorithm_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    # The exact audited-contaminated commit SHA this invalidation responds
    # to (CORE-002: never a rewritten/rebased history, always a real,
    # resolvable commit).
    target_commit: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

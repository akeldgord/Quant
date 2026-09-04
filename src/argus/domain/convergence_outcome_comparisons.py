"""``convergence_outcome_comparisons`` — FSR-06 (final spec recovery),
MASTER_SPEC.md Phase 8 (CONVERGENCE + NEGATIVE EVIDENCE) sections 59/60's
own required "outcome comparisons for ordinary overlap, high-surprisal
overlap, rapid confirmation and failed confirmation" report unit.

One row per (class_name, as_of, algorithm_version, config_hash) -- the
same F5-05 idempotent-identity pattern every other Phase 5-11 derived
table uses. Never a 0-100 score (FSR-06's own explicit prohibition):
``eligible_count``/``sample_count``/``mean_return_pct``/
``median_return_pct``/``win_rate``/``no_route_unsellable_missing_rate``
are the class's own executable-outcome evidence, kept fully separate
from ``mark_sample_count``/``mark_mean_return_pct`` (descriptive-only,
section 47/48). ``insufficient_executable_sample`` is True (with every
executable numeric field NULL) when a class has no eligible
known-by-cutoff evidence at all -- never a fabricated mark-return
substitute.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

_CLASS_NAMES_SQL = (
    "'ORDINARY_OVERLAP', 'HIGH_SURPRISAL_OVERLAP', 'RAPID_CONFIRMATION', 'FAILED_CONFIRMATION'"
)


class ConvergenceOutcomeComparison(Base):
    __tablename__ = "convergence_outcome_comparisons"
    __table_args__ = (
        UniqueConstraint(
            "class_name",
            "as_of",
            "algorithm_version",
            "config_hash",
            name="uq_convergence_outcome_comparisons_identity",
        ),
        CheckConstraint(f"class_name IN ({_CLASS_NAMES_SQL})", name="ck_convergence_outcome_class"),
        CheckConstraint("member_count >= 0", name="ck_convergence_outcome_member_count_nonneg"),
        CheckConstraint("eligible_count >= 0", name="ck_convergence_outcome_eligible_nonneg"),
        CheckConstraint("sample_count >= 0", name="ck_convergence_outcome_sample_nonneg"),
        CheckConstraint(
            "eligible_count <= member_count", name="ck_convergence_outcome_eligible_le_member"
        ),
        CheckConstraint(
            "sample_count <= eligible_count", name="ck_convergence_outcome_sample_le_eligible"
        ),
        CheckConstraint(
            "win_rate IS NULL OR (win_rate >= 0 AND win_rate <= 1)",
            name="ck_convergence_outcome_win_rate_range",
        ),
        CheckConstraint(
            "no_route_unsellable_missing_rate IS NULL "
            "OR (no_route_unsellable_missing_rate >= 0 AND no_route_unsellable_missing_rate <= 1)",
            name="ck_convergence_outcome_no_route_rate_range",
        ),
        CheckConstraint("mark_sample_count >= 0", name="ck_convergence_outcome_mark_sample_nonneg"),
        CheckConstraint(
            "NOT insufficient_executable_sample OR ("
            "mean_return_pct IS NULL AND median_return_pct IS NULL "
            "AND win_rate IS NULL AND no_route_unsellable_missing_rate IS NULL)",
            name="ck_convergence_outcome_insufficient_implies_null",
        ),
        CheckConstraint(
            "length(algorithm_version) > 0", name="ck_convergence_outcome_algo_version_nonempty"
        ),
        CheckConstraint(
            "length(config_hash) > 0", name="ck_convergence_outcome_config_hash_nonempty"
        ),
    )

    comparison_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    class_name: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mean_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    median_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    win_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    no_route_unsellable_missing_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 15), nullable=True
    )
    insufficient_executable_sample: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Descriptive-only mark-return evidence -- always kept separate from
    # the executable fields above (section 47/48's own explicit rule).
    mark_sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mark_mean_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

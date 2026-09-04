"""FSR-06: Phase 8 required outcome-comparison layer

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-04

ARGUS-INSTRUCTION-ID: argus-final-spec-recovery-001

Additive-only: no existing table, column, or grant is altered; migration
`0031` (and everything before it) is unmodified.

``convergence_outcome_comparisons`` is MASTER_SPEC.md Phase 8 sections
59/60's own required report unit that the original build silently
omitted: one row per (class_name, as_of, algorithm_version, config_hash)
covering the four required classes (ORDINARY_OVERLAP,
HIGH_SURPRISAL_OVERLAP, RAPID_CONFIRMATION, FAILED_CONFIRMATION), each
carrying sample/eligible counts, mean/median executable return, win
rate, and no-route/unsellable/missing-outcome rate -- never collapsed
into a 0-100 score -- plus a separately-tracked, descriptive-only mark-
return summary (section 47/48). See ``argus.convergence.outcome_
comparison`` for the pure statistics this table stores.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLASS_NAMES_SQL = (
    "'ORDINARY_OVERLAP', 'HIGH_SURPRISAL_OVERLAP', 'RAPID_CONFIRMATION', 'FAILED_CONFIRMATION'"
)


def upgrade() -> None:
    op.create_table(
        "convergence_outcome_comparisons",
        sa.Column("comparison_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("class_name", sa.String(32), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("eligible_count", sa.Integer(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("mean_return_pct", sa.Numeric(20, 15), nullable=True),
        sa.Column("median_return_pct", sa.Numeric(20, 15), nullable=True),
        sa.Column("win_rate", sa.Numeric(20, 15), nullable=True),
        sa.Column("no_route_unsellable_missing_rate", sa.Numeric(20, 15), nullable=True),
        sa.Column("insufficient_executable_sample", sa.Boolean(), nullable=False),
        sa.Column("mark_sample_count", sa.Integer(), nullable=False),
        sa.Column("mark_mean_return_pct", sa.Numeric(20, 15), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "class_name",
            "as_of",
            "algorithm_version",
            "config_hash",
            name="uq_convergence_outcome_comparisons_identity",
        ),
        sa.CheckConstraint(
            f"class_name IN ({_CLASS_NAMES_SQL})", name="ck_convergence_outcome_class"
        ),
        sa.CheckConstraint("member_count >= 0", name="ck_convergence_outcome_member_count_nonneg"),
        sa.CheckConstraint("eligible_count >= 0", name="ck_convergence_outcome_eligible_nonneg"),
        sa.CheckConstraint("sample_count >= 0", name="ck_convergence_outcome_sample_nonneg"),
        sa.CheckConstraint(
            "eligible_count <= member_count", name="ck_convergence_outcome_eligible_le_member"
        ),
        sa.CheckConstraint(
            "sample_count <= eligible_count", name="ck_convergence_outcome_sample_le_eligible"
        ),
        sa.CheckConstraint(
            "win_rate IS NULL OR (win_rate >= 0 AND win_rate <= 1)",
            name="ck_convergence_outcome_win_rate_range",
        ),
        sa.CheckConstraint(
            "no_route_unsellable_missing_rate IS NULL "
            "OR (no_route_unsellable_missing_rate >= 0 AND no_route_unsellable_missing_rate <= 1)",
            name="ck_convergence_outcome_no_route_rate_range",
        ),
        sa.CheckConstraint(
            "mark_sample_count >= 0", name="ck_convergence_outcome_mark_sample_nonneg"
        ),
        sa.CheckConstraint(
            "NOT insufficient_executable_sample OR ("
            "mean_return_pct IS NULL AND median_return_pct IS NULL "
            "AND win_rate IS NULL AND no_route_unsellable_missing_rate IS NULL)",
            name="ck_convergence_outcome_insufficient_implies_null",
        ),
        sa.CheckConstraint(
            "length(algorithm_version) > 0", name="ck_convergence_outcome_algo_version_nonempty"
        ),
        sa.CheckConstraint(
            "length(config_hash) > 0", name="ck_convergence_outcome_config_hash_nonempty"
        ),
    )
    op.create_index(
        "ix_convergence_outcome_comparisons_class_name",
        "convergence_outcome_comparisons",
        ["class_name"],
    )
    op.create_index(
        "ix_convergence_outcome_comparisons_as_of", "convergence_outcome_comparisons", ["as_of"]
    )

    for table in ("convergence_outcome_comparisons",):
        op.execute(f"GRANT SELECT, INSERT ON {table} TO argus_ingest;")
        op.execute(f"GRANT SELECT ON {table} TO argus_research;")
        op.execute(f"GRANT SELECT ON {table} TO argus_executor;")


def downgrade() -> None:
    for table in ("convergence_outcome_comparisons",):
        op.execute(f"REVOKE ALL ON {table} FROM argus_ingest;")
        op.execute(f"REVOKE ALL ON {table} FROM argus_research;")
        op.execute(f"REVOKE ALL ON {table} FROM argus_executor;")

    op.drop_index(
        "ix_convergence_outcome_comparisons_as_of", table_name="convergence_outcome_comparisons"
    )
    op.drop_index(
        "ix_convergence_outcome_comparisons_class_name",
        table_name="convergence_outcome_comparisons",
    )
    op.drop_table("convergence_outcome_comparisons")

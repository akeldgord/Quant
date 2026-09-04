"""FSR-13: contaminated_run_invalidations registry + Phase 8/10/11 version bump

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-04

ARGUS-INSTRUCTION-ID: argus-final-spec-recovery-001

Additive-only, and CORE-002-compliant: no existing row in any Phase 8-11
derived table is deleted, rewritten, or relabeled. This migration creates
one new, small registry table and seeds it with the four known-contaminated
(phase, algorithm_version) pairs this recovery's own FSR-05..12 items fixed
(Phase 7/ALPHA ANCESTRY is intentionally out of scope -- FSR-13's own text
scopes to "Phase 8-11" only). The corresponding ``ALGORITHM_VERSION``
module constants were bumped in this same commit (Phase 9's own bump
already happened in FSR-07); since every Phase 8-11 CLI report already
filters its own table by the CURRENT ``ALGORITHM_VERSION`` constant (never
"the newest row"), that bump alone already excludes the old, contaminated
rows from any DEFAULT report -- they remain fully queryable by their own
(unaltered) ``algorithm_version``. This table is the explicit, persisted
audit trail naming WHY each old version is excluded and WHAT superseded it
(FSR-13's own "explicit persisted state/reason" requirement).

``TARGET_COMMIT`` (``ea77dd55b1e6be91b61b2f8b37e1d70449a3cb30``) is the
exact audited-contaminated commit this recovery responds to, per
``orchestration/ORCHESTRATOR_INSTRUCTIONS.md``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TARGET_COMMIT = "ea77dd55b1e6be91b61b2f8b37e1d70449a3cb30"

_SEED_ROWS: tuple[tuple[str, str, str, str], ...] = (
    (
        "PHASE_8_CONVERGENCE",
        "convergence_negative_evidence_v1",
        "convergence_negative_evidence_v2",
        "FSR-06: Phase 8 convergence/confirmation evidence was not "
        "computed with the shared point-in-time knowledge-cutoff "
        "invariant, allowing future evidence to leak into a past "
        "observation.",
    ),
    (
        "PHASE_9_COUNTERFACTUAL",
        "counterfactual_alpha_specialists_v1",
        "counterfactual_alpha_v2",
        "FSR-07: Phase 9 predation inputs were incomplete (repetition "
        "frequency and real follower price-impact evidence were not "
        "incorporated), and a price-impact blend formula defect capped "
        "the predation score below its price-impact-blind core value.",
    ),
    (
        "PHASE_10_SYNTHETIC",
        "synthetic_super_wallet_v1",
        "synthetic_super_wallet_v2",
        "FSR-08: Phase 10's primary backtest result was a fixed-cost-"
        "haircut mark price rather than the entry wallet's own real "
        "Phase 5 executable-return quote, and Strategy B/D's specialist "
        "filters used a single classification computed once at the "
        "final run cutoff instead of each entry's own decision time.",
    ),
    (
        "PHASE_11_PREDICTION",
        "order_flow_prediction_v1",
        "order_flow_prediction_v2",
        "FSR-09/10/11: Phase 11 features leaked future specialist scores "
        "and future market snapshots, incomplete forward label windows "
        "were fabricated as negatives instead of right-censored, and the "
        "train/test split was a plain chronological split rather than a "
        "purged+embargoed one -- all three are real look-ahead-bias "
        "sources in a temporally-overlapping-label supervised dataset.",
    ),
)


def upgrade() -> None:
    op.create_table(
        "contaminated_run_invalidations",
        sa.Column("invalidation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("phase_name", sa.String(32), nullable=False),
        sa.Column("invalidated_algorithm_version", sa.String(64), nullable=False),
        sa.Column("superseded_by_algorithm_version", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("target_commit", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "phase_name",
            "invalidated_algorithm_version",
            name="uq_contaminated_run_invalidations_identity",
        ),
        sa.CheckConstraint(
            "phase_name IN ('PHASE_8_CONVERGENCE', 'PHASE_9_COUNTERFACTUAL', "
            "'PHASE_10_SYNTHETIC', 'PHASE_11_PREDICTION')",
            name="ck_contaminated_run_invalidations_phase_name",
        ),
        sa.CheckConstraint(
            "status IN ('INVALID_FOR_EVALUATION', 'SUPERSEDED')",
            name="ck_contaminated_run_invalidations_status",
        ),
        sa.CheckConstraint(
            "length(invalidated_algorithm_version) > 0",
            name="ck_contaminated_run_invalidations_invalidated_version_nonempty",
        ),
        sa.CheckConstraint(
            "superseded_by_algorithm_version IS NULL "
            "OR length(superseded_by_algorithm_version) > 0",
            name="ck_contaminated_run_invalidations_superseded_version_nonempty",
        ),
        sa.CheckConstraint(
            "invalidated_algorithm_version != superseded_by_algorithm_version",
            name="ck_contaminated_run_invalidations_distinct_versions",
        ),
        sa.CheckConstraint(
            "length(reason) > 0", name="ck_contaminated_run_invalidations_reason_nonempty"
        ),
        sa.CheckConstraint(
            "length(target_commit) = 40",
            name="ck_contaminated_run_invalidations_target_commit_sha",
        ),
    )
    op.create_index(
        "ix_contaminated_run_invalidations_phase_name",
        "contaminated_run_invalidations",
        ["phase_name"],
    )

    op.execute("GRANT SELECT ON contaminated_run_invalidations TO argus_ingest;")
    op.execute("GRANT SELECT ON contaminated_run_invalidations TO argus_research;")
    op.execute("GRANT SELECT ON contaminated_run_invalidations TO argus_executor;")

    table = sa.table(
        "contaminated_run_invalidations",
        sa.column("invalidation_id", postgresql.UUID(as_uuid=True)),
        sa.column("phase_name", sa.String),
        sa.column("invalidated_algorithm_version", sa.String),
        sa.column("superseded_by_algorithm_version", sa.String),
        sa.column("status", sa.String),
        sa.column("reason", sa.Text),
        sa.column("target_commit", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    seeded_at = datetime(2026, 9, 4, tzinfo=UTC)
    op.bulk_insert(
        table,
        [
            {
                "invalidation_id": uuid.uuid4(),
                "phase_name": phase_name,
                "invalidated_algorithm_version": invalidated,
                "superseded_by_algorithm_version": superseded_by,
                "status": "SUPERSEDED",
                "reason": reason,
                "target_commit": _TARGET_COMMIT,
                "created_at": seeded_at,
            }
            for phase_name, invalidated, superseded_by, reason in _SEED_ROWS
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_contaminated_run_invalidations_phase_name", table_name="contaminated_run_invalidations"
    )
    op.drop_table("contaminated_run_invalidations")

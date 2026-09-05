"""Clarification-002 section 2: phase65_canary_results evidence table

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-05

ARGUS-INSTRUCTION-ID: argus-final-spec-recovery-002-clarification-002

Adds ``phase65_canary_results`` -- the ONLY persisted signal that can
ever let ordinary single-intent execution construct
``LiveRiskInputs.canary_passed=True`` after the very first authorized
Phase 6.5 human canary succeeds (see
``argus.executor.persistence.load_passed_canary_result_for_identity``/
``record_canary_result``, and ``argus.executor.canary`` for the external,
human-authored, hash/expiry-bound canary-authorization file that gates
the one-time pre-pass path itself). A row is written ONLY after the
pipeline reaches a genuine on-chain ``CONFIRMED`` success for an intent
run under that authorization -- never for a rejected/failed/unresolved
attempt, and never from repository defaults or an operator params-file
boolean.

Purely additive (CORE-002): a new table, no change to any existing
table/column/grant. Least-privilege grants mirror migration 0024's own
executor-table pattern: ``argus_executor`` gets SELECT/INSERT only (this
table is never updated once written -- a canary result is a one-time,
append-only fact); ``argus_research``/``argus_ingest`` get SELECT-only
for reporting/audit.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "phase65_canary_results",
        sa.Column("canary_result_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "intent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("execution_intents.intent_id"),
            nullable=False,
        ),
        sa.Column("transaction_signature", sa.String(128), nullable=False),
        sa.Column("approved_git_commit", sa.String(64), nullable=False),
        sa.Column("approved_executor_build_hash", sa.String(64), nullable=False),
        sa.Column("approved_risk_config_hash", sa.String(64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("intent_id", name="uq_phase65_canary_results_intent_id"),
        sa.CheckConstraint(
            "length(transaction_signature) > 0",
            name="ck_phase65_canary_results_signature_nonempty",
        ),
        sa.CheckConstraint(
            "length(approved_git_commit) > 0",
            name="ck_phase65_canary_results_git_commit_nonempty",
        ),
        sa.CheckConstraint(
            "length(approved_executor_build_hash) > 0",
            name="ck_phase65_canary_results_build_hash_nonempty",
        ),
        sa.CheckConstraint(
            "length(approved_risk_config_hash) > 0",
            name="ck_phase65_canary_results_config_hash_nonempty",
        ),
    )
    op.create_index(
        "ix_phase65_canary_results_identity",
        "phase65_canary_results",
        ["approved_git_commit", "approved_executor_build_hash", "approved_risk_config_hash"],
    )

    op.execute("GRANT SELECT, INSERT ON phase65_canary_results TO argus_executor;")
    op.execute("GRANT SELECT ON phase65_canary_results TO argus_research;")
    op.execute("GRANT SELECT ON phase65_canary_results TO argus_ingest;")


def downgrade() -> None:
    op.execute("REVOKE ALL ON phase65_canary_results FROM argus_executor;")
    op.execute("REVOKE ALL ON phase65_canary_results FROM argus_research;")
    op.execute("REVOKE ALL ON phase65_canary_results FROM argus_ingest;")
    op.drop_index("ix_phase65_canary_results_identity", table_name="phase65_canary_results")
    op.drop_table("phase65_canary_results")

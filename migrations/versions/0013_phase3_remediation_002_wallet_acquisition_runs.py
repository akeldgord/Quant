"""Phase 3 remediation round 2 (P3-R1/P3-R2): wallet_acquisition_runs.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-01

Per orchestrator instruction ``argus-phase-3-remediation-002``
(``AUTHORIZED_ACTION: CLOSE_REMAINING_FROZEN_PHASE_3_DEFECTS_AND_
MIGRATION_REGRESSION``), findings P3-R1/P3-R2: the original Phase 3 CLI
accepted an arbitrary caller-supplied JSON file as the authority for a
wallet's history completeness -- a fabricated manifest (COMPLETE, every
account enumerated=true, an evidence_reference naming nothing real) could
promote a wallet to HIGH completeness with no real acquisition ever
having occurred.

``wallet_acquisition_runs`` is the real, structured, immutable RESULT of
an actually-executed acquisition walk
(``argus.wallets.acquisition.run_wallet_acquisition``), persisted with an
explicit wallet binding. A score computation now loads an
``AcquisitionManifest`` ONLY by verified ``run_id`` lookup against this
table (``argus.wallets.acquisition.load_verified_acquisition_manifest``)
-- there is no remaining path from caller-supplied JSON to a manifest.

``wallet_history_quality.excluded_evidence`` (also P3-R1): every swap
excluded from a history assessment's usable-evidence set because its
economic timestamp (``block_time``) is later than the score's ``as_of``,
with an explicit reason -- previously silently dropped inside
``reconstruct_positions_for_wallet`` alone, invisible to
``assess_wallet_history`` and never persisted anywhere.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wallet_acquisition_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=False,
        ),
        sa.Column("observation_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(algorithm_version) > 0", name="ck_wallet_acquisition_runs_algo_version"
        ),
    )
    op.create_index(
        "ix_wallet_acquisition_runs_wallet_id", "wallet_acquisition_runs", ["wallet_id"]
    )
    op.create_index(
        "ix_wallet_acquisition_runs_observation_cutoff",
        "wallet_acquisition_runs",
        ["observation_cutoff"],
    )
    op.create_index(
        "ix_wallet_acquisition_runs_created_at", "wallet_acquisition_runs", ["created_at"]
    )

    # Append-only, like every other Phase 3 decision ledger.
    op.execute("GRANT SELECT, INSERT ON wallet_acquisition_runs TO argus_ingest;")
    op.execute("GRANT SELECT ON wallet_acquisition_runs TO argus_research;")

    op.add_column(
        "wallet_history_quality",
        sa.Column("excluded_evidence", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.alter_column("wallet_history_quality", "excluded_evidence", server_default=None)


def downgrade() -> None:
    op.drop_column("wallet_history_quality", "excluded_evidence")

    op.execute("REVOKE ALL ON wallet_acquisition_runs FROM argus_ingest;")
    op.execute("REVOKE ALL ON wallet_acquisition_runs FROM argus_research;")

    op.drop_index("ix_wallet_acquisition_runs_created_at", table_name="wallet_acquisition_runs")
    op.drop_index(
        "ix_wallet_acquisition_runs_observation_cutoff", table_name="wallet_acquisition_runs"
    )
    op.drop_index("ix_wallet_acquisition_runs_wallet_id", table_name="wallet_acquisition_runs")
    op.drop_table("wallet_acquisition_runs")

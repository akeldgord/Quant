"""Phase 5: wallet_copyability_snapshots, opportunity_readiness_snapshots

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-02

Per orchestrator instruction ``argus-phase-5-001`` (P5-09): two new,
additive-only, immutable, append-only analytical tables implementing
MASTER_SPEC.md sections 46-53 mechanics M1-M7 -- per-wallet copyability
(delay curve, information half-life, forward-information grid, size
surprise, copyability score/components/confidence) and per-opportunity
trade readiness (six master hard gates + actionable/diagnostic scores).
No existing table, column, or grant changes. Same least-privilege grant
pattern as every prior analytics/decision-ledger table this project has
added (0008/0010/0016): the write path runs under ``argus_ingest`` (see
every other ``argus <noun> <verb>`` CLI command's own DB role choice --
``argus_research`` stays read-only project-wide).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_TABLES = ("wallet_copyability_snapshots", "opportunity_readiness_snapshots")


def upgrade() -> None:
    op.create_table(
        "wallet_copyability_snapshots",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=False,
        ),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column(
            "contributing_source_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "excluded_source_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("evidence_manifest_digest", sa.String(64), nullable=False),
        sa.Column(
            "delay_curve", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "half_life_result",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "forward_information_grid",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "size_surprise",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("copyability_score", sa.Numeric(20, 15), nullable=True),
        sa.Column(
            "copyability_components",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "available_weight", sa.Numeric(6, 5), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("sample_n", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("sample_k", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "sample_coverage", sa.Numeric(20, 15), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("sample_c", sa.Numeric(20, 15), nullable=False, server_default=sa.text("0")),
        sa.Column("confidence", sa.String(16), nullable=False, server_default=sa.text("'UNKNOWN'")),
        sa.Column(
            "descriptive_extras",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("build_hash", sa.String(64), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("master_spec_hash", sa.String(64), nullable=False),
        sa.Column("git_commit", sa.String(64), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "wallet_id",
            "as_of",
            "algorithm_version",
            "evidence_manifest_digest",
            name="uq_wallet_copyability_identity",
        ),
        sa.CheckConstraint(
            "length(algorithm_version) > 0", name="ck_wallet_copyability_algo_nonempty"
        ),
        sa.CheckConstraint(
            "length(evidence_manifest_digest) > 0",
            name="ck_wallet_copyability_manifest_digest_nonempty",
        ),
        sa.CheckConstraint(
            "confidence IN ('UNKNOWN', 'LOW', 'MEDIUM', 'HIGH')",
            name="ck_wallet_copyability_confidence",
        ),
        sa.CheckConstraint(
            "sample_n >= 0 AND sample_k >= 0", name="ck_wallet_copyability_sample_nonneg"
        ),
        sa.CheckConstraint(
            "length(build_hash) > 0", name="ck_wallet_copyability_snapshots_build_hash_nonempty"
        ),
        sa.CheckConstraint(
            "length(config_hash) > 0", name="ck_wallet_copyability_snapshots_config_hash_nonempty"
        ),
        sa.CheckConstraint(
            "length(master_spec_hash) > 0",
            name="ck_wallet_copyability_snapshots_master_spec_hash_nonempty",
        ),
        sa.CheckConstraint(
            "length(git_commit) > 0", name="ck_wallet_copyability_snapshots_git_commit_nonempty"
        ),
    )
    op.create_index(
        "ix_wallet_copyability_snapshots_wallet_id",
        "wallet_copyability_snapshots",
        ["wallet_id"],
    )
    op.create_index(
        "ix_wallet_copyability_snapshots_as_of", "wallet_copyability_snapshots", ["as_of"]
    )
    op.create_index(
        "ix_wallet_copyability_snapshots_algorithm_version",
        "wallet_copyability_snapshots",
        ["algorithm_version"],
    )
    op.create_index(
        "ix_wallet_copyability_snapshots_computed_at",
        "wallet_copyability_snapshots",
        ["computed_at"],
    )

    op.create_table(
        "opportunity_readiness_snapshots",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "prospective_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prospective_events.prospective_event_id"),
            nullable=False,
        ),
        sa.Column(
            "wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=False,
        ),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column(
            "contributing_source_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "excluded_source_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("evidence_manifest_digest", sa.String(64), nullable=False),
        sa.Column(
            "gates", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("eligible", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("actionable_score", sa.Numeric(20, 15), nullable=True),
        sa.Column("diagnostic_score", sa.Numeric(20, 15), nullable=True),
        sa.Column(
            "components", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("build_hash", sa.String(64), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("master_spec_hash", sa.String(64), nullable=False),
        sa.Column("git_commit", sa.String(64), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "prospective_event_id",
            "as_of",
            "algorithm_version",
            "evidence_manifest_digest",
            name="uq_opportunity_readiness_identity",
        ),
        sa.CheckConstraint(
            "length(algorithm_version) > 0", name="ck_opportunity_readiness_algo_nonempty"
        ),
        sa.CheckConstraint(
            "length(evidence_manifest_digest) > 0",
            name="ck_opportunity_readiness_manifest_digest_nonempty",
        ),
        sa.CheckConstraint(
            "eligible = false OR actionable_score IS NOT NULL",
            name="ck_opportunity_readiness_eligible_has_score",
        ),
        sa.CheckConstraint(
            "length(build_hash) > 0",
            name="ck_opportunity_readiness_snapshots_build_hash_nonempty",
        ),
        sa.CheckConstraint(
            "length(config_hash) > 0",
            name="ck_opportunity_readiness_snapshots_config_hash_nonempty",
        ),
        sa.CheckConstraint(
            "length(master_spec_hash) > 0",
            name="ck_opportunity_readiness_snapshots_master_spec_hash_nonempty",
        ),
        sa.CheckConstraint(
            "length(git_commit) > 0",
            name="ck_opportunity_readiness_snapshots_git_commit_nonempty",
        ),
    )
    op.create_index(
        "ix_opportunity_readiness_snapshots_prospective_event_id",
        "opportunity_readiness_snapshots",
        ["prospective_event_id"],
    )
    op.create_index(
        "ix_opportunity_readiness_snapshots_wallet_id",
        "opportunity_readiness_snapshots",
        ["wallet_id"],
    )
    op.create_index(
        "ix_opportunity_readiness_snapshots_as_of", "opportunity_readiness_snapshots", ["as_of"]
    )
    op.create_index(
        "ix_opportunity_readiness_snapshots_algorithm_version",
        "opportunity_readiness_snapshots",
        ["algorithm_version"],
    )
    op.create_index(
        "ix_opportunity_readiness_snapshots_computed_at",
        "opportunity_readiness_snapshots",
        ["computed_at"],
    )

    for table in _NEW_TABLES:
        op.execute(f"GRANT SELECT, INSERT ON {table} TO argus_ingest;")
        op.execute(f"GRANT SELECT ON {table} TO argus_research;")


def downgrade() -> None:
    for table in _NEW_TABLES:
        op.execute(f"REVOKE ALL ON {table} FROM argus_ingest;")
        op.execute(f"REVOKE ALL ON {table} FROM argus_research;")

    op.drop_index(
        "ix_opportunity_readiness_snapshots_computed_at",
        table_name="opportunity_readiness_snapshots",
    )
    op.drop_index(
        "ix_opportunity_readiness_snapshots_algorithm_version",
        table_name="opportunity_readiness_snapshots",
    )
    op.drop_index(
        "ix_opportunity_readiness_snapshots_as_of", table_name="opportunity_readiness_snapshots"
    )
    op.drop_index(
        "ix_opportunity_readiness_snapshots_wallet_id",
        table_name="opportunity_readiness_snapshots",
    )
    op.drop_index(
        "ix_opportunity_readiness_snapshots_prospective_event_id",
        table_name="opportunity_readiness_snapshots",
    )
    op.drop_table("opportunity_readiness_snapshots")

    op.drop_index(
        "ix_wallet_copyability_snapshots_computed_at", table_name="wallet_copyability_snapshots"
    )
    op.drop_index(
        "ix_wallet_copyability_snapshots_algorithm_version",
        table_name="wallet_copyability_snapshots",
    )
    op.drop_index(
        "ix_wallet_copyability_snapshots_as_of", table_name="wallet_copyability_snapshots"
    )
    op.drop_index(
        "ix_wallet_copyability_snapshots_wallet_id", table_name="wallet_copyability_snapshots"
    )
    op.drop_table("wallet_copyability_snapshots")

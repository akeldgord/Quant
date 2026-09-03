"""Phase 7: ALPHA ANCESTRY -- lead/follow observations + directional edges

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-03

MASTER_SPEC.md PHASE 7 (ALPHA ANCESTRY): find wallets that lead other
skilled wallets. Additive-only: two new tables built purely from
already-persisted Phase 4 ``prospective_events`` evidence (one row per
tracked wallet's real buy entry into a token) -- no existing table,
column, or grant is altered; migration ``0024`` (and everything before
it) is unmodified.

``lead_follow_observations`` is the raw, append-only observational unit:
one row per (token, leader wallet, follower wallet) pair where the
follower entered the token after the leader within the algorithm's
configured lag window. ``directional_edges`` is the aggregated,
statistically-corrected report unit: one row per (leader, follower) pair
per computation run, carrying the base-rate-corrected lift, effect size,
p-value, and Benjamini-Hochberg q-value MASTER_SPEC's own required report
fields list. Both follow the same idempotent-identity pattern F5-05
established for Phase 5 snapshots (``config_hash`` bound into the unique
identity so a changed config always produces a new row, never a silent
overwrite).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lead_follow_observations",
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.token_id"),
            nullable=False,
        ),
        sa.Column(
            "leader_wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=False,
        ),
        sa.Column(
            "follower_wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=False,
        ),
        sa.Column(
            "leader_prospective_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prospective_events.prospective_event_id"),
            nullable=False,
        ),
        sa.Column(
            "follower_prospective_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prospective_events.prospective_event_id"),
            nullable=False,
        ),
        sa.Column("leader_entered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("follower_entered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lag_seconds", sa.Numeric(20, 6), nullable=False),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "token_id",
            "leader_wallet_id",
            "follower_wallet_id",
            "algorithm_version",
            name="uq_lead_follow_observations_identity",
        ),
        sa.CheckConstraint("lag_seconds > 0", name="ck_lead_follow_observations_lag_positive"),
        sa.CheckConstraint(
            "leader_wallet_id != follower_wallet_id",
            name="ck_lead_follow_observations_distinct_wallets",
        ),
        sa.CheckConstraint(
            "follower_entered_at > leader_entered_at",
            name="ck_lead_follow_observations_follower_after_leader",
        ),
        sa.CheckConstraint(
            "length(algorithm_version) > 0",
            name="ck_lead_follow_observations_algo_version_nonempty",
        ),
    )
    op.create_index(
        "ix_lead_follow_observations_leader", "lead_follow_observations", ["leader_wallet_id"]
    )
    op.create_index(
        "ix_lead_follow_observations_follower", "lead_follow_observations", ["follower_wallet_id"]
    )
    op.create_index("ix_lead_follow_observations_token", "lead_follow_observations", ["token_id"])

    op.create_table(
        "directional_edges",
        sa.Column("edge_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "leader_wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=False,
        ),
        sa.Column(
            "follower_wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=False,
        ),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False),
        sa.Column("tokens_leader_entered", sa.Integer(), nullable=False),
        sa.Column("follower_base_rate", sa.Numeric(20, 15), nullable=False),
        sa.Column("median_lag_seconds", sa.Numeric(20, 6), nullable=False),
        sa.Column("expected_follows", sa.Numeric(20, 15), nullable=False),
        sa.Column("lift", sa.Numeric(20, 15), nullable=True),
        sa.Column("effect_size", sa.Numeric(20, 15), nullable=True),
        sa.Column("p_value", sa.Numeric(20, 15), nullable=False),
        sa.Column("q_value", sa.Numeric(20, 15), nullable=False),
        sa.Column("forward_information_after_leader_pct", sa.Numeric(20, 15), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "leader_wallet_id",
            "follower_wallet_id",
            "as_of",
            "algorithm_version",
            "config_hash",
            name="uq_directional_edges_identity",
        ),
        sa.CheckConstraint(
            "leader_wallet_id != follower_wallet_id", name="ck_directional_edges_distinct_wallets"
        ),
        sa.CheckConstraint("observation_count >= 0", name="ck_directional_edges_obs_nonneg"),
        sa.CheckConstraint("tokens_leader_entered >= 0", name="ck_directional_edges_tokens_nonneg"),
        sa.CheckConstraint(
            "p_value >= 0 AND p_value <= 1", name="ck_directional_edges_p_value_range"
        ),
        sa.CheckConstraint(
            "q_value >= 0 AND q_value <= 1", name="ck_directional_edges_q_value_range"
        ),
        sa.CheckConstraint(
            "length(algorithm_version) > 0", name="ck_directional_edges_algo_version_nonempty"
        ),
        sa.CheckConstraint(
            "length(config_hash) > 0", name="ck_directional_edges_config_hash_nonempty"
        ),
    )
    op.create_index("ix_directional_edges_leader", "directional_edges", ["leader_wallet_id"])
    op.create_index("ix_directional_edges_follower", "directional_edges", ["follower_wallet_id"])
    op.create_index("ix_directional_edges_as_of", "directional_edges", ["as_of"])

    for table in ("lead_follow_observations", "directional_edges"):
        op.execute(f"GRANT SELECT, INSERT ON {table} TO argus_research;")
        op.execute(f"GRANT SELECT ON {table} TO argus_ingest;")
        op.execute(f"GRANT SELECT ON {table} TO argus_executor;")


def downgrade() -> None:
    for table in ("lead_follow_observations", "directional_edges"):
        op.execute(f"REVOKE ALL ON {table} FROM argus_research;")
        op.execute(f"REVOKE ALL ON {table} FROM argus_ingest;")
        op.execute(f"REVOKE ALL ON {table} FROM argus_executor;")

    op.drop_index("ix_directional_edges_as_of", table_name="directional_edges")
    op.drop_index("ix_directional_edges_follower", table_name="directional_edges")
    op.drop_index("ix_directional_edges_leader", table_name="directional_edges")
    op.drop_table("directional_edges")

    op.drop_index("ix_lead_follow_observations_token", table_name="lead_follow_observations")
    op.drop_index("ix_lead_follow_observations_follower", table_name="lead_follow_observations")
    op.drop_index("ix_lead_follow_observations_leader", table_name="lead_follow_observations")
    op.drop_table("lead_follow_observations")

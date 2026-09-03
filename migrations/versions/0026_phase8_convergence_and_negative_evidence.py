"""Phase 8: CONVERGENCE + NEGATIVE EVIDENCE -- convergence surprise + dog-that-didn't-bark

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-03

MASTER_SPEC.md PHASE 8 (CONVERGENCE + NEGATIVE EVIDENCE). Additive-only:
two new tables built from already-persisted Phase 4 ``prospective_events``,
Phase 3 ``wallet_cluster_links``, and Phase 7 ``directional_edges``/
``lead_follow_observations`` evidence -- no existing table, column, or
grant is altered; migration ``0025`` (and everything before it) is
unmodified.

``convergence_events`` is section 59's (CONVERGENCE SURPRISE) required
report unit: one row per (token, episode) -- the token's own first wave
of tracked-wallet interest within a configured window -- carrying raw
wallet count, cluster-corrected effective independent-actor count, and a
non-parametric empirical overlap probability/surprisal built from prior
episodes' own observed independent-actor counts (never an assumed
parametric distribution -- section 59's own "empirical overlap
probabilities" term, plural). No 0-100 score is ever produced (section
59's own explicit prohibition); ``calibration_confidence`` is a disclosed
sample-size bucket instead.

``expected_confirmation_events`` is section 60's (DOG-THAT-DIDN'T-BARK
SIGNAL) required report unit: one row per (significant Phase 7
directional edge, leader's own real buy entry) classification of whether
the historically-expected follower confirmation occurred, and how
(ABSENT/EARLY/LATE/STRONG/NORMAL).

Both follow the same idempotent-identity pattern F5-05 established for
Phase 5 snapshots (``config_hash`` bound into the unique identity so a
changed config always produces a new row, never a silent overwrite).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "convergence_events",
        sa.Column("convergence_event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.token_id"),
            nullable=False,
        ),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_wallet_count", sa.Integer(), nullable=False),
        sa.Column("estimated_independent_actors", sa.Numeric(20, 15), nullable=False),
        sa.Column("expected_overlap", sa.Numeric(20, 15), nullable=False),
        sa.Column("observed_overlap", sa.Numeric(20, 15), nullable=False),
        sa.Column("empirical_probability", sa.Numeric(20, 15), nullable=False),
        sa.Column("surprisal", sa.Numeric(20, 15), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("calibration_confidence", sa.String(32), nullable=False),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "token_id",
            "window_start",
            "as_of",
            "algorithm_version",
            "config_hash",
            name="uq_convergence_events_identity",
        ),
        sa.CheckConstraint(
            "raw_wallet_count >= 1", name="ck_convergence_events_raw_count_positive"
        ),
        sa.CheckConstraint(
            "estimated_independent_actors > 0 AND estimated_independent_actors <= raw_wallet_count",
            name="ck_convergence_events_independent_actors_range",
        ),
        sa.CheckConstraint("expected_overlap >= 0", name="ck_convergence_events_expected_nonneg"),
        sa.CheckConstraint(
            "empirical_probability > 0 AND empirical_probability <= 1",
            name="ck_convergence_events_probability_range",
        ),
        sa.CheckConstraint("surprisal >= 0", name="ck_convergence_events_surprisal_nonneg"),
        sa.CheckConstraint("sample_size >= 0", name="ck_convergence_events_sample_size_nonneg"),
        sa.CheckConstraint("window_end >= window_start", name="ck_convergence_events_window_order"),
        sa.CheckConstraint(
            "calibration_confidence IN ('INSUFFICIENT_SAMPLE', 'LOW', 'MEDIUM', 'HIGH')",
            name="ck_convergence_events_calibration_confidence",
        ),
        sa.CheckConstraint(
            "length(algorithm_version) > 0", name="ck_convergence_events_algo_version_nonempty"
        ),
        sa.CheckConstraint(
            "length(config_hash) > 0", name="ck_convergence_events_config_hash_nonempty"
        ),
    )
    op.create_index("ix_convergence_events_token", "convergence_events", ["token_id"])
    op.create_index("ix_convergence_events_as_of", "convergence_events", ["as_of"])

    op.create_table(
        "expected_confirmation_events",
        sa.Column(
            "expected_confirmation_event_id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column(
            "directional_edge_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("directional_edges.edge_id"),
            nullable=False,
        ),
        sa.Column(
            "leader_prospective_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prospective_events.prospective_event_id"),
            nullable=False,
        ),
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
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("follower_entered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lag_seconds", sa.Numeric(20, 6), nullable=True),
        sa.Column("expected_window_low_seconds", sa.Numeric(20, 6), nullable=False),
        sa.Column("expected_window_high_seconds", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "convergence_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("convergence_events.convergence_event_id"),
            nullable=True,
        ),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "directional_edge_id",
            "leader_prospective_event_id",
            "as_of",
            "algorithm_version",
            "config_hash",
            name="uq_expected_confirmation_events_identity",
        ),
        sa.CheckConstraint(
            "outcome IN ('ABSENT', 'EARLY', 'LATE', 'STRONG', 'NORMAL')",
            name="ck_expected_confirmation_events_outcome",
        ),
        sa.CheckConstraint(
            "(outcome = 'ABSENT' AND follower_entered_at IS NULL AND lag_seconds IS NULL) OR "
            "(outcome != 'ABSENT' AND follower_entered_at IS NOT NULL AND lag_seconds IS NOT NULL)",
            name="ck_expected_confirmation_events_absent_consistency",
        ),
        sa.CheckConstraint(
            "lag_seconds IS NULL OR lag_seconds > 0",
            name="ck_expected_confirmation_events_lag_positive",
        ),
        sa.CheckConstraint(
            "expected_window_low_seconds >= 0",
            name="ck_expected_confirmation_events_window_low_nonneg",
        ),
        sa.CheckConstraint(
            "expected_window_high_seconds >= expected_window_low_seconds",
            name="ck_expected_confirmation_events_window_order",
        ),
        sa.CheckConstraint(
            "leader_wallet_id != follower_wallet_id",
            name="ck_expected_confirmation_events_distinct_wallets",
        ),
        sa.CheckConstraint(
            "length(algorithm_version) > 0",
            name="ck_expected_confirmation_events_algo_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(config_hash) > 0", name="ck_expected_confirmation_events_config_hash_nonempty"
        ),
    )
    op.create_index(
        "ix_expected_confirmation_events_edge",
        "expected_confirmation_events",
        ["directional_edge_id"],
    )
    op.create_index(
        "ix_expected_confirmation_events_token", "expected_confirmation_events", ["token_id"]
    )
    op.create_index(
        "ix_expected_confirmation_events_as_of", "expected_confirmation_events", ["as_of"]
    )
    op.create_index(
        "ix_expected_confirmation_events_outcome", "expected_confirmation_events", ["outcome"]
    )

    for table in ("convergence_events", "expected_confirmation_events"):
        op.execute(f"GRANT SELECT, INSERT ON {table} TO argus_research;")
        op.execute(f"GRANT SELECT ON {table} TO argus_ingest;")
        op.execute(f"GRANT SELECT ON {table} TO argus_executor;")


def downgrade() -> None:
    for table in ("convergence_events", "expected_confirmation_events"):
        op.execute(f"REVOKE ALL ON {table} FROM argus_research;")
        op.execute(f"REVOKE ALL ON {table} FROM argus_ingest;")
        op.execute(f"REVOKE ALL ON {table} FROM argus_executor;")

    op.drop_index(
        "ix_expected_confirmation_events_outcome", table_name="expected_confirmation_events"
    )
    op.drop_index(
        "ix_expected_confirmation_events_as_of", table_name="expected_confirmation_events"
    )
    op.drop_index(
        "ix_expected_confirmation_events_token", table_name="expected_confirmation_events"
    )
    op.drop_index("ix_expected_confirmation_events_edge", table_name="expected_confirmation_events")
    op.drop_table("expected_confirmation_events")

    op.drop_index("ix_convergence_events_as_of", table_name="convergence_events")
    op.drop_index("ix_convergence_events_token", table_name="convergence_events")
    op.drop_table("convergence_events")

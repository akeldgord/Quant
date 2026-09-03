"""Phase 9: COUNTERFACTUAL ALPHA + SPECIALISTS

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-03

MASTER_SPEC.md PHASE 9 (COUNTERFACTUAL ALPHA + SPECIALISTS). Additive-only:
four new tables built from already-persisted Phase 2 ``token_market_snapshots``,
Phase 3 ``wallet_score_snapshots``, Phase 4 ``prospective_events``, and
Phase 7/8 ``directional_edges``/``expected_confirmation_events`` evidence
-- no existing table, column, or grant is altered; migration ``0026``
(and everything before it) is unmodified.

``counterfactual_alpha_estimates`` is section 55's (COUNTERFACTUAL ALPHA)
required report unit: for each real wallet entry, at each horizon, the
wallet's own forward return minus the mean forward return of a
point-in-time matched control-token set -- ``residual_selection_alpha``.

``wallet_specialist_scores`` is section 62's (ENTRY AND EXIT SPECIALISTS)
required report unit: entry/discovery/validation/exit ability scored
independently per wallet, plus a percentile-rank-based
``dominant_specialty`` classification.

``wallet_predation_scores`` is section 61's (PREDATION DETECTION)
required report unit: follower influx and leader-exit-after-influx rate
per wallet, composed into a disclosed V1 ``predation_score`` heuristic.

``exit_convergence_events`` is section 63's (EXIT ORACLES) required
``EXIT_CONVERGENCE`` report unit -- the same convergence-episode shape
Phase 8 built for entries, reused unchanged against an exit-event
population restricted to wallets classified as exit specialists.

Both follow the same idempotent-identity pattern F5-05 established for
Phase 5 snapshots (``config_hash`` bound into the unique identity so a
changed config always produces a new row, never a silent overwrite).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "counterfactual_alpha_estimates",
        sa.Column("estimate_id", postgresql.UUID(as_uuid=True), primary_key=True),
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
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.token_id"),
            nullable=False,
        ),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_seconds", sa.Integer(), nullable=False),
        sa.Column("wallet_token_forward_return", sa.Numeric(20, 15), nullable=True),
        sa.Column("matched_universe_forward_return", sa.Numeric(20, 15), nullable=True),
        sa.Column("residual_selection_alpha", sa.Numeric(20, 15), nullable=True),
        sa.Column("matched_control_count", sa.Integer(), nullable=False),
        sa.Column("matching_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "prospective_event_id",
            "horizon_seconds",
            "as_of",
            "algorithm_version",
            "config_hash",
            name="uq_counterfactual_alpha_estimates_identity",
        ),
        sa.CheckConstraint(
            "horizon_seconds > 0", name="ck_counterfactual_alpha_estimates_horizon_positive"
        ),
        sa.CheckConstraint(
            "matched_control_count >= 0",
            name="ck_counterfactual_alpha_estimates_control_count_nonneg",
        ),
        sa.CheckConstraint(
            "(wallet_token_forward_return IS NOT NULL AND matched_universe_forward_return IS NOT NULL) "
            "OR residual_selection_alpha IS NULL",
            name="ck_counterfactual_alpha_estimates_residual_consistency",
        ),
        sa.CheckConstraint(
            "length(algorithm_version) > 0",
            name="ck_counterfactual_alpha_estimates_algo_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(config_hash) > 0", name="ck_counterfactual_alpha_estimates_config_hash_nonempty"
        ),
    )
    op.create_index(
        "ix_counterfactual_alpha_estimates_wallet", "counterfactual_alpha_estimates", ["wallet_id"]
    )
    op.create_index(
        "ix_counterfactual_alpha_estimates_token", "counterfactual_alpha_estimates", ["token_id"]
    )
    op.create_index(
        "ix_counterfactual_alpha_estimates_as_of", "counterfactual_alpha_estimates", ["as_of"]
    )

    op.create_table(
        "wallet_specialist_scores",
        sa.Column("score_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=False,
        ),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_specialist_score", sa.Numeric(20, 15), nullable=True),
        sa.Column("entry_specialist_sample_size", sa.Integer(), nullable=False),
        sa.Column("discovery_specialist_score", sa.Numeric(20, 15), nullable=True),
        sa.Column("discovery_specialist_sample_size", sa.Integer(), nullable=False),
        sa.Column("validation_specialist_score", sa.Numeric(20, 15), nullable=True),
        sa.Column("validation_specialist_sample_size", sa.Integer(), nullable=False),
        sa.Column("exit_specialist_score", sa.Numeric(20, 15), nullable=True),
        sa.Column("entry_percentile", sa.Numeric(20, 15), nullable=True),
        sa.Column("discovery_percentile", sa.Numeric(20, 15), nullable=True),
        sa.Column("validation_percentile", sa.Numeric(20, 15), nullable=True),
        sa.Column("exit_percentile", sa.Numeric(20, 15), nullable=True),
        sa.Column("dominant_specialty", sa.String(16), nullable=True),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "wallet_id",
            "as_of",
            "algorithm_version",
            "config_hash",
            name="uq_wallet_specialist_scores_identity",
        ),
        sa.CheckConstraint(
            "dominant_specialty IS NULL OR "
            "dominant_specialty IN ('ENTRY', 'DISCOVERY', 'VALIDATION', 'EXIT')",
            name="ck_wallet_specialist_scores_dominant_specialty",
        ),
        sa.CheckConstraint(
            "entry_percentile IS NULL OR (entry_percentile >= 0 AND entry_percentile <= 1)",
            name="ck_wallet_specialist_scores_entry_percentile_range",
        ),
        sa.CheckConstraint(
            "discovery_percentile IS NULL OR (discovery_percentile >= 0 AND discovery_percentile <= 1)",
            name="ck_wallet_specialist_scores_discovery_percentile_range",
        ),
        sa.CheckConstraint(
            "validation_percentile IS NULL OR (validation_percentile >= 0 AND validation_percentile <= 1)",
            name="ck_wallet_specialist_scores_validation_percentile_range",
        ),
        sa.CheckConstraint(
            "exit_percentile IS NULL OR (exit_percentile >= 0 AND exit_percentile <= 1)",
            name="ck_wallet_specialist_scores_exit_percentile_range",
        ),
        sa.CheckConstraint(
            "length(algorithm_version) > 0",
            name="ck_wallet_specialist_scores_algo_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(config_hash) > 0", name="ck_wallet_specialist_scores_config_hash_nonempty"
        ),
    )
    op.create_index("ix_wallet_specialist_scores_wallet", "wallet_specialist_scores", ["wallet_id"])
    op.create_index("ix_wallet_specialist_scores_as_of", "wallet_specialist_scores", ["as_of"])

    op.create_table(
        "wallet_predation_scores",
        sa.Column("score_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=False,
        ),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_entries_count", sa.Integer(), nullable=False),
        sa.Column("entries_with_influx_count", sa.Integer(), nullable=False),
        sa.Column("follower_influx_mean", sa.Numeric(20, 15), nullable=True),
        sa.Column("exit_after_influx_count", sa.Integer(), nullable=False),
        sa.Column("exit_after_influx_rate", sa.Numeric(20, 15), nullable=True),
        sa.Column("price_impact_mean", sa.Numeric(20, 15), nullable=True),
        sa.Column("predation_score", sa.Numeric(20, 15), nullable=True),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "wallet_id",
            "as_of",
            "algorithm_version",
            "config_hash",
            name="uq_wallet_predation_scores_identity",
        ),
        sa.CheckConstraint(
            "total_entries_count >= 0", name="ck_wallet_predation_scores_total_entries_nonneg"
        ),
        sa.CheckConstraint(
            "entries_with_influx_count >= 0 AND entries_with_influx_count <= total_entries_count",
            name="ck_wallet_predation_scores_influx_count_range",
        ),
        sa.CheckConstraint(
            "exit_after_influx_count >= 0 AND exit_after_influx_count <= entries_with_influx_count",
            name="ck_wallet_predation_scores_exit_after_influx_range",
        ),
        sa.CheckConstraint(
            "predation_score IS NULL OR (predation_score >= 0 AND predation_score <= 1)",
            name="ck_wallet_predation_scores_predation_score_range",
        ),
        sa.CheckConstraint(
            "length(algorithm_version) > 0", name="ck_wallet_predation_scores_algo_version_nonempty"
        ),
        sa.CheckConstraint(
            "length(config_hash) > 0", name="ck_wallet_predation_scores_config_hash_nonempty"
        ),
    )
    op.create_index("ix_wallet_predation_scores_wallet", "wallet_predation_scores", ["wallet_id"])
    op.create_index("ix_wallet_predation_scores_as_of", "wallet_predation_scores", ["as_of"])

    op.create_table(
        "exit_convergence_events",
        sa.Column("exit_convergence_event_id", postgresql.UUID(as_uuid=True), primary_key=True),
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
            name="uq_exit_convergence_events_identity",
        ),
        sa.CheckConstraint(
            "raw_wallet_count >= 1", name="ck_exit_convergence_events_raw_count_positive"
        ),
        sa.CheckConstraint(
            "estimated_independent_actors > 0 AND estimated_independent_actors <= raw_wallet_count",
            name="ck_exit_convergence_events_independent_actors_range",
        ),
        sa.CheckConstraint(
            "expected_overlap >= 0", name="ck_exit_convergence_events_expected_nonneg"
        ),
        sa.CheckConstraint(
            "empirical_probability > 0 AND empirical_probability <= 1",
            name="ck_exit_convergence_events_probability_range",
        ),
        sa.CheckConstraint("surprisal >= 0", name="ck_exit_convergence_events_surprisal_nonneg"),
        sa.CheckConstraint(
            "sample_size >= 0", name="ck_exit_convergence_events_sample_size_nonneg"
        ),
        sa.CheckConstraint(
            "window_end >= window_start", name="ck_exit_convergence_events_window_order"
        ),
        sa.CheckConstraint(
            "calibration_confidence IN ('INSUFFICIENT_SAMPLE', 'LOW', 'MEDIUM', 'HIGH')",
            name="ck_exit_convergence_events_calibration_confidence",
        ),
        sa.CheckConstraint(
            "length(algorithm_version) > 0", name="ck_exit_convergence_events_algo_version_nonempty"
        ),
        sa.CheckConstraint(
            "length(config_hash) > 0", name="ck_exit_convergence_events_config_hash_nonempty"
        ),
    )
    op.create_index("ix_exit_convergence_events_token", "exit_convergence_events", ["token_id"])
    op.create_index("ix_exit_convergence_events_as_of", "exit_convergence_events", ["as_of"])

    for table in (
        "counterfactual_alpha_estimates",
        "wallet_specialist_scores",
        "wallet_predation_scores",
        "exit_convergence_events",
    ):
        op.execute(f"GRANT SELECT, INSERT ON {table} TO argus_research;")
        op.execute(f"GRANT SELECT ON {table} TO argus_ingest;")
        op.execute(f"GRANT SELECT ON {table} TO argus_executor;")


def downgrade() -> None:
    for table in (
        "counterfactual_alpha_estimates",
        "wallet_specialist_scores",
        "wallet_predation_scores",
        "exit_convergence_events",
    ):
        op.execute(f"REVOKE ALL ON {table} FROM argus_research;")
        op.execute(f"REVOKE ALL ON {table} FROM argus_ingest;")
        op.execute(f"REVOKE ALL ON {table} FROM argus_executor;")

    op.drop_index("ix_exit_convergence_events_as_of", table_name="exit_convergence_events")
    op.drop_index("ix_exit_convergence_events_token", table_name="exit_convergence_events")
    op.drop_table("exit_convergence_events")

    op.drop_index("ix_wallet_predation_scores_as_of", table_name="wallet_predation_scores")
    op.drop_index("ix_wallet_predation_scores_wallet", table_name="wallet_predation_scores")
    op.drop_table("wallet_predation_scores")

    op.drop_index("ix_wallet_specialist_scores_as_of", table_name="wallet_specialist_scores")
    op.drop_index("ix_wallet_specialist_scores_wallet", table_name="wallet_specialist_scores")
    op.drop_table("wallet_specialist_scores")

    op.drop_index(
        "ix_counterfactual_alpha_estimates_as_of", table_name="counterfactual_alpha_estimates"
    )
    op.drop_index(
        "ix_counterfactual_alpha_estimates_token", table_name="counterfactual_alpha_estimates"
    )
    op.drop_index(
        "ix_counterfactual_alpha_estimates_wallet", table_name="counterfactual_alpha_estimates"
    )
    op.drop_table("counterfactual_alpha_estimates")

"""Phase 11: PREDICT INFORMED ORDER FLOW

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-03

MASTER_SPEC.md PHASE 11 (PREDICT INFORMED ORDER FLOW). Additive-only: no
existing table, column, or grant is altered; migration `0028` (and
everything before it) is unmodified.

``order_flow_prediction_runs`` is one row per (horizon, model family)
evaluated in a run: MASTER_SPEC's own required targets
(P(elite wallet enters within 5m/15m/30m/1h)), baselines
(random/token-momentum/wallet-history/graph+token-state), and models
(logistic regression, regularized logistic regression, gradient-boosted
trees -- explicitly never a neural network at this stage, section 111's
own "do not build a neural network until simpler models are convincingly
beaten out of sample"). "Only begin with adequate clean prospective
sample" (PHASE 11's own opening instruction): a run with too few
observations is recorded honestly as ``INSUFFICIENT_SAMPLE`` with every
metric ``NULL`` -- never a fabricated result trained on too little data.
Uses strict temporal (never random) train/test validation.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MODEL_FAMILIES_SQL = (
    "('BASELINE_RANDOM', 'BASELINE_TOKEN_MOMENTUM', 'BASELINE_WALLET_HISTORY', "
    "'BASELINE_GRAPH_TOKEN_STATE', 'LOGISTIC_REGRESSION', "
    "'REGULARIZED_LOGISTIC_REGRESSION', 'GRADIENT_BOOSTED_TREES')"
)
_STATUSES_SQL = "('EVALUATED', 'INSUFFICIENT_SAMPLE')"


def upgrade() -> None:
    op.create_table(
        "order_flow_prediction_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("horizon_seconds", sa.Integer(), nullable=False),
        sa.Column("model_family", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("train_sample_size", sa.Integer(), nullable=False),
        sa.Column("test_sample_size", sa.Integer(), nullable=False),
        sa.Column("positive_rate_train", sa.Numeric(20, 15), nullable=True),
        sa.Column("positive_rate_test", sa.Numeric(20, 15), nullable=True),
        sa.Column("auc_roc", sa.Numeric(20, 15), nullable=True),
        sa.Column("log_loss", sa.Numeric(20, 15), nullable=True),
        sa.Column("brier_score", sa.Numeric(20, 15), nullable=True),
        sa.Column("accuracy_at_threshold", sa.Numeric(20, 15), nullable=True),
        sa.Column("feature_set", postgresql.JSONB(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "horizon_seconds",
            "model_family",
            "as_of",
            "algorithm_version",
            "config_hash",
            name="uq_order_flow_prediction_runs_identity",
        ),
        sa.CheckConstraint(
            "horizon_seconds > 0", name="ck_order_flow_prediction_runs_horizon_positive"
        ),
        sa.CheckConstraint(
            f"model_family IN {_MODEL_FAMILIES_SQL}",
            name="ck_order_flow_prediction_runs_model_family",
        ),
        sa.CheckConstraint(
            f"status IN {_STATUSES_SQL}", name="ck_order_flow_prediction_runs_status"
        ),
        sa.CheckConstraint(
            "(status = 'INSUFFICIENT_SAMPLE' AND auc_roc IS NULL AND log_loss IS NULL "
            "AND brier_score IS NULL AND accuracy_at_threshold IS NULL) OR (status != 'INSUFFICIENT_SAMPLE')",
            name="ck_order_flow_prediction_runs_insufficient_sample_consistency",
        ),
        sa.CheckConstraint(
            "train_sample_size >= 0 AND test_sample_size >= 0",
            name="ck_order_flow_prediction_runs_sample_sizes_nonneg",
        ),
        sa.CheckConstraint(
            "auc_roc IS NULL OR (auc_roc >= 0 AND auc_roc <= 1)",
            name="ck_order_flow_prediction_runs_auc_range",
        ),
        sa.CheckConstraint(
            "positive_rate_train IS NULL OR (positive_rate_train >= 0 AND positive_rate_train <= 1)",
            name="ck_order_flow_prediction_runs_pos_rate_train_range",
        ),
        sa.CheckConstraint(
            "positive_rate_test IS NULL OR (positive_rate_test >= 0 AND positive_rate_test <= 1)",
            name="ck_order_flow_prediction_runs_pos_rate_test_range",
        ),
        sa.CheckConstraint(
            "accuracy_at_threshold IS NULL OR (accuracy_at_threshold >= 0 AND accuracy_at_threshold <= 1)",
            name="ck_order_flow_prediction_runs_accuracy_range",
        ),
        sa.CheckConstraint(
            "length(algorithm_version) > 0",
            name="ck_order_flow_prediction_runs_algo_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(config_hash) > 0", name="ck_order_flow_prediction_runs_config_hash_nonempty"
        ),
    )
    op.create_index(
        "ix_order_flow_prediction_runs_horizon", "order_flow_prediction_runs", ["horizon_seconds"]
    )
    op.create_index(
        "ix_order_flow_prediction_runs_model_family", "order_flow_prediction_runs", ["model_family"]
    )
    op.create_index("ix_order_flow_prediction_runs_as_of", "order_flow_prediction_runs", ["as_of"])

    op.execute("GRANT SELECT, INSERT ON order_flow_prediction_runs TO argus_research;")
    op.execute("GRANT SELECT ON order_flow_prediction_runs TO argus_ingest;")
    op.execute("GRANT SELECT ON order_flow_prediction_runs TO argus_executor;")


def downgrade() -> None:
    op.execute("REVOKE ALL ON order_flow_prediction_runs FROM argus_research;")
    op.execute("REVOKE ALL ON order_flow_prediction_runs FROM argus_ingest;")
    op.execute("REVOKE ALL ON order_flow_prediction_runs FROM argus_executor;")

    op.drop_index("ix_order_flow_prediction_runs_as_of", table_name="order_flow_prediction_runs")
    op.drop_index(
        "ix_order_flow_prediction_runs_model_family", table_name="order_flow_prediction_runs"
    )
    op.drop_index("ix_order_flow_prediction_runs_horizon", table_name="order_flow_prediction_runs")
    op.drop_table("order_flow_prediction_runs")

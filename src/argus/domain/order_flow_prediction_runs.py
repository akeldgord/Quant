"""``order_flow_prediction_runs`` — MASTER_SPEC.md Phase 11 (PREDICT
INFORMED ORDER FLOW).

One row per (horizon, model family) evaluated in a run: MASTER_SPEC's
own required targets (P(elite wallet enters within 5m/15m/30m/1h)),
baselines (random/token-momentum/wallet-history/graph+token-state), and
models (logistic regression, regularized logistic regression,
gradient-boosted trees -- never a neural network at this stage). "Only
begin with adequate clean prospective sample" -- a run with too few
observations is recorded honestly as ``INSUFFICIENT_SAMPLE`` with every
metric ``NULL``, never a fabricated result trained on too little data.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

STATUS_EVALUATED = "EVALUATED"
STATUS_INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"

MODEL_BASELINE_RANDOM = "BASELINE_RANDOM"
MODEL_BASELINE_TOKEN_MOMENTUM = "BASELINE_TOKEN_MOMENTUM"
MODEL_BASELINE_WALLET_HISTORY = "BASELINE_WALLET_HISTORY"
MODEL_BASELINE_GRAPH_TOKEN_STATE = "BASELINE_GRAPH_TOKEN_STATE"
MODEL_LOGISTIC_REGRESSION = "LOGISTIC_REGRESSION"
MODEL_REGULARIZED_LOGISTIC_REGRESSION = "REGULARIZED_LOGISTIC_REGRESSION"
MODEL_GRADIENT_BOOSTED_TREES = "GRADIENT_BOOSTED_TREES"

MODEL_FAMILIES: tuple[str, ...] = (
    MODEL_BASELINE_RANDOM,
    MODEL_BASELINE_TOKEN_MOMENTUM,
    MODEL_BASELINE_WALLET_HISTORY,
    MODEL_BASELINE_GRAPH_TOKEN_STATE,
    MODEL_LOGISTIC_REGRESSION,
    MODEL_REGULARIZED_LOGISTIC_REGRESSION,
    MODEL_GRADIENT_BOOSTED_TREES,
)


class OrderFlowPredictionRun(Base):
    __tablename__ = "order_flow_prediction_runs"
    __table_args__ = (
        UniqueConstraint(
            "horizon_seconds",
            "model_family",
            "as_of",
            "algorithm_version",
            "config_hash",
            name="uq_order_flow_prediction_runs_identity",
        ),
        CheckConstraint(
            "horizon_seconds > 0", name="ck_order_flow_prediction_runs_horizon_positive"
        ),
        CheckConstraint(
            "model_family IN ('BASELINE_RANDOM', 'BASELINE_TOKEN_MOMENTUM', "
            "'BASELINE_WALLET_HISTORY', 'BASELINE_GRAPH_TOKEN_STATE', 'LOGISTIC_REGRESSION', "
            "'REGULARIZED_LOGISTIC_REGRESSION', 'GRADIENT_BOOSTED_TREES')",
            name="ck_order_flow_prediction_runs_model_family",
        ),
        CheckConstraint(
            "status IN ('EVALUATED', 'INSUFFICIENT_SAMPLE')",
            name="ck_order_flow_prediction_runs_status",
        ),
        CheckConstraint(
            "(status = 'INSUFFICIENT_SAMPLE' AND auc_roc IS NULL AND log_loss IS NULL "
            "AND brier_score IS NULL AND accuracy_at_threshold IS NULL) "
            "OR (status != 'INSUFFICIENT_SAMPLE')",
            name="ck_order_flow_prediction_runs_insufficient_sample_consistency",
        ),
        CheckConstraint(
            "train_sample_size >= 0 AND test_sample_size >= 0",
            name="ck_order_flow_prediction_runs_sample_sizes_nonneg",
        ),
        CheckConstraint(
            "auc_roc IS NULL OR (auc_roc >= 0 AND auc_roc <= 1)",
            name="ck_order_flow_prediction_runs_auc_range",
        ),
        CheckConstraint(
            "positive_rate_train IS NULL OR (positive_rate_train >= 0 AND positive_rate_train <= 1)",
            name="ck_order_flow_prediction_runs_pos_rate_train_range",
        ),
        CheckConstraint(
            "positive_rate_test IS NULL OR (positive_rate_test >= 0 AND positive_rate_test <= 1)",
            name="ck_order_flow_prediction_runs_pos_rate_test_range",
        ),
        CheckConstraint(
            "accuracy_at_threshold IS NULL OR "
            "(accuracy_at_threshold >= 0 AND accuracy_at_threshold <= 1)",
            name="ck_order_flow_prediction_runs_accuracy_range",
        ),
        CheckConstraint(
            "length(algorithm_version) > 0",
            name="ck_order_flow_prediction_runs_algo_version_nonempty",
        ),
        CheckConstraint(
            "length(config_hash) > 0", name="ck_order_flow_prediction_runs_config_hash_nonempty"
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    horizon_seconds: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    model_family: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    train_sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    test_sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    positive_rate_train: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    positive_rate_test: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    auc_roc: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    log_loss: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    brier_score: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    accuracy_at_threshold: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    # The exact list of feature names actually used, for reproducibility
    # (CORE-004) -- baselines and models use different, disclosed subsets.
    feature_set: Mapped[list] = mapped_column(JSONB, nullable=False)

    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

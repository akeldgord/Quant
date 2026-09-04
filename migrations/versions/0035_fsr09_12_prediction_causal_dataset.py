"""FSR-09/10/11/12: Phase 11 causal dataset rebuild -- split metadata

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-04

ARGUS-INSTRUCTION-ID: argus-final-spec-recovery-001

Additive-only: no existing column, table, or grant is altered or
dropped. FSR-09 (feature-timestamp leakage) and FSR-10 (right-censored
labels) are pure code fixes with no schema change -- the label already
lives only in an in-memory dict, never a persisted "negative" row. FSR-11
replaces the plain chronological split with a deterministic purged +
embargoed split; this migration adds the columns needed to persist that
split's own required metadata (boundary, embargo, purged count, train/test
ranges) on ``order_flow_prediction_runs`` per FSR-12's own "Required
report fields" list. ``purged_count`` is NOT NULL (0 when no split was
ever attempted); the other five are nullable for that same case.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "order_flow_prediction_runs",
        sa.Column("split_boundary", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "order_flow_prediction_runs", sa.Column("embargo_seconds", sa.Integer(), nullable=True)
    )
    op.add_column(
        "order_flow_prediction_runs",
        sa.Column("purged_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("order_flow_prediction_runs", "purged_count", server_default=None)
    op.add_column(
        "order_flow_prediction_runs",
        sa.Column("train_range_start", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "order_flow_prediction_runs",
        sa.Column("train_range_end", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "order_flow_prediction_runs",
        sa.Column("test_range_start", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "order_flow_prediction_runs",
        sa.Column("test_range_end", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_check_constraint(
        "ck_order_flow_prediction_runs_purged_nonneg",
        "order_flow_prediction_runs",
        "purged_count >= 0",
    )
    op.create_check_constraint(
        "ck_order_flow_prediction_runs_embargo_positive",
        "order_flow_prediction_runs",
        "embargo_seconds IS NULL OR embargo_seconds > 0",
    )
    op.create_check_constraint(
        "ck_order_flow_prediction_runs_train_range_consistency",
        "order_flow_prediction_runs",
        "(train_range_start IS NULL) = (train_range_end IS NULL)",
    )
    op.create_check_constraint(
        "ck_order_flow_prediction_runs_test_range_consistency",
        "order_flow_prediction_runs",
        "(test_range_start IS NULL) = (test_range_end IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_order_flow_prediction_runs_test_range_consistency",
        "order_flow_prediction_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_order_flow_prediction_runs_train_range_consistency",
        "order_flow_prediction_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_order_flow_prediction_runs_embargo_positive",
        "order_flow_prediction_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_order_flow_prediction_runs_purged_nonneg", "order_flow_prediction_runs", type_="check"
    )

    op.drop_column("order_flow_prediction_runs", "test_range_end")
    op.drop_column("order_flow_prediction_runs", "test_range_start")
    op.drop_column("order_flow_prediction_runs", "train_range_end")
    op.drop_column("order_flow_prediction_runs", "train_range_start")
    op.drop_column("order_flow_prediction_runs", "purged_count")
    op.drop_column("order_flow_prediction_runs", "embargo_seconds")
    op.drop_column("order_flow_prediction_runs", "split_boundary")

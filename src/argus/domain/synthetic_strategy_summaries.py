"""``synthetic_strategy_summaries`` — MASTER_SPEC.md Phase 10 (SYNTHETIC
SUPER-WALLET), section 64 / PHASE 10's own required comparison list:
executable return, drawdown, win rate, profit factor, capital
utilization, failure rate, computed after realistic costs. "Shadow only
unless later approved" -- purely a backtest-result summary, no
live-execution bearing whatsoever.

One row per strategy per run. A metric that is undefined for a given
run (e.g. ``profit_factor`` with zero losing trades, an infinite ratio)
is persisted as ``NULL`` -- never fabricated as an arbitrary large
number.
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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base


class SyntheticStrategySummary(Base):
    __tablename__ = "synthetic_strategy_summaries"
    __table_args__ = (
        UniqueConstraint(
            "strategy_code",
            "as_of",
            "algorithm_version",
            "config_hash",
            name="uq_synthetic_strategy_summaries_identity",
        ),
        CheckConstraint(
            "strategy_code IN ('A', 'B', 'C', 'D', 'E')",
            name="ck_synthetic_strategy_summaries_code",
        ),
        CheckConstraint("trade_count >= 0", name="ck_synthetic_strategy_summaries_trade_nonneg"),
        CheckConstraint(
            "resolved_count >= 0 AND resolved_count <= trade_count",
            name="ck_synthetic_strategy_summaries_resolved_range",
        ),
        CheckConstraint(
            "failure_count >= 0 AND failure_count <= trade_count",
            name="ck_synthetic_strategy_summaries_failure_range",
        ),
        CheckConstraint(
            "resolved_count + failure_count = trade_count",
            name="ck_synthetic_strategy_summaries_counts_add_up",
        ),
        CheckConstraint(
            "failure_rate IS NULL OR (failure_rate >= 0 AND failure_rate <= 1)",
            name="ck_synthetic_strategy_summaries_failure_rate_range",
        ),
        CheckConstraint(
            "win_rate IS NULL OR (win_rate >= 0 AND win_rate <= 1)",
            name="ck_synthetic_strategy_summaries_win_rate_range",
        ),
        CheckConstraint(
            "capital_utilization IS NULL OR "
            "(capital_utilization >= 0 AND capital_utilization <= 1)",
            name="ck_synthetic_strategy_summaries_capital_utilization_range",
        ),
        CheckConstraint(
            "max_drawdown IS NULL OR max_drawdown >= 0",
            name="ck_synthetic_strategy_summaries_drawdown_nonneg",
        ),
        CheckConstraint(
            "length(algorithm_version) > 0",
            name="ck_synthetic_strategy_summaries_algo_version_nonempty",
        ),
        CheckConstraint(
            "length(config_hash) > 0", name="ck_synthetic_strategy_summaries_config_hash_nonempty"
        ),
    )

    summary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_code: Mapped[str] = mapped_column(String(4), nullable=False, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    trade_count: Mapped[int] = mapped_column(Integer, nullable=False)
    resolved_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failure_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    win_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    profit_factor: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    max_drawdown: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    capital_utilization: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    mean_net_return: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    median_net_return: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)

    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

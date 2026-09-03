"""Phase 10: SYNTHETIC SUPER-WALLET (shadow-only prospective strategy backtest)

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-03

MASTER_SPEC.md PHASE 10 (SYNTHETIC SUPER-WALLET), section 64. "Shadow
only unless later approved" -- this migration adds no live-execution
capability whatsoever; it persists the record of five prospective,
purely-backtested strategies (A-E) built entirely from already-persisted
Phase 4/7/8/9 evidence. Additive-only: no existing table, column, or
grant is altered; migration `0027` (and everything before it) is
unmodified.

``synthetic_strategy_trades`` is one row per simulated one-unit position:
its entry/exit trigger evidence references (CORE-004), real point-in-time
prices, a disclosed realistic-cost haircut, and its resolved/failed
outcome. ``synthetic_strategy_summaries`` is one row per strategy per
run: MASTER_SPEC's own required comparison metrics (executable return,
drawdown, win rate, profit factor, capital utilization, failure rate).
Both follow the same idempotent-identity pattern F5-05 established for
Phase 5 snapshots (``config_hash`` bound into the unique identity).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STRATEGY_CODES_SQL = "('A', 'B', 'C', 'D', 'E')"
_TRADE_OUTCOMES_SQL = (
    "('RESOLVED', 'FAILURE_NO_ENTRY_PRICE', 'FAILURE_NO_EXIT_TRIGGER', 'FAILURE_NO_EXIT_PRICE')"
)


def upgrade() -> None:
    op.create_table(
        "synthetic_strategy_trades",
        sa.Column("trade_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("strategy_code", sa.String(4), nullable=False),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.token_id"),
            nullable=False,
        ),
        sa.Column(
            "entry_wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=True,
        ),
        sa.Column("entry_trigger_reference", postgresql.JSONB(), nullable=False),
        sa.Column("entry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price_usd", sa.Numeric(38, 18), nullable=True),
        sa.Column(
            "exit_wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=True,
        ),
        sa.Column("exit_trigger_reference", postgresql.JSONB(), nullable=True),
        sa.Column("exit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_price_usd", sa.Numeric(38, 18), nullable=True),
        sa.Column("cost_bps_applied", sa.Numeric(10, 4), nullable=False),
        sa.Column("gross_return", sa.Numeric(20, 15), nullable=True),
        sa.Column("net_return", sa.Numeric(20, 15), nullable=True),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "strategy_code",
            "token_id",
            "entry_at",
            "as_of",
            "algorithm_version",
            "config_hash",
            name="uq_synthetic_strategy_trades_identity",
        ),
        sa.CheckConstraint(
            f"strategy_code IN {_STRATEGY_CODES_SQL}", name="ck_synthetic_strategy_trades_code"
        ),
        sa.CheckConstraint(
            f"outcome IN {_TRADE_OUTCOMES_SQL}", name="ck_synthetic_strategy_trades_outcome"
        ),
        sa.CheckConstraint(
            "(outcome = 'RESOLVED' AND exit_at IS NOT NULL AND exit_price_usd IS NOT NULL "
            "AND net_return IS NOT NULL) OR (outcome != 'RESOLVED')",
            name="ck_synthetic_strategy_trades_resolved_consistency",
        ),
        sa.CheckConstraint(
            "(outcome = 'FAILURE_NO_ENTRY_PRICE' AND entry_price_usd IS NULL) "
            "OR (outcome != 'FAILURE_NO_ENTRY_PRICE')",
            name="ck_synthetic_strategy_trades_no_entry_price_consistency",
        ),
        sa.CheckConstraint(
            "cost_bps_applied >= 0", name="ck_synthetic_strategy_trades_cost_nonneg"
        ),
        sa.CheckConstraint(
            "length(algorithm_version) > 0",
            name="ck_synthetic_strategy_trades_algo_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(config_hash) > 0", name="ck_synthetic_strategy_trades_config_hash_nonempty"
        ),
    )
    op.create_index(
        "ix_synthetic_strategy_trades_strategy", "synthetic_strategy_trades", ["strategy_code"]
    )
    op.create_index("ix_synthetic_strategy_trades_token", "synthetic_strategy_trades", ["token_id"])
    op.create_index("ix_synthetic_strategy_trades_as_of", "synthetic_strategy_trades", ["as_of"])

    op.create_table(
        "synthetic_strategy_summaries",
        sa.Column("summary_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("strategy_code", sa.String(4), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column("resolved_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("failure_rate", sa.Numeric(20, 15), nullable=True),
        sa.Column("win_rate", sa.Numeric(20, 15), nullable=True),
        sa.Column("profit_factor", sa.Numeric(20, 15), nullable=True),
        sa.Column("max_drawdown", sa.Numeric(20, 15), nullable=True),
        sa.Column("capital_utilization", sa.Numeric(20, 15), nullable=True),
        sa.Column("mean_net_return", sa.Numeric(20, 15), nullable=True),
        sa.Column("median_net_return", sa.Numeric(20, 15), nullable=True),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "strategy_code",
            "as_of",
            "algorithm_version",
            "config_hash",
            name="uq_synthetic_strategy_summaries_identity",
        ),
        sa.CheckConstraint(
            f"strategy_code IN {_STRATEGY_CODES_SQL}", name="ck_synthetic_strategy_summaries_code"
        ),
        sa.CheckConstraint("trade_count >= 0", name="ck_synthetic_strategy_summaries_trade_nonneg"),
        sa.CheckConstraint(
            "resolved_count >= 0 AND resolved_count <= trade_count",
            name="ck_synthetic_strategy_summaries_resolved_range",
        ),
        sa.CheckConstraint(
            "failure_count >= 0 AND failure_count <= trade_count",
            name="ck_synthetic_strategy_summaries_failure_range",
        ),
        sa.CheckConstraint(
            "resolved_count + failure_count = trade_count",
            name="ck_synthetic_strategy_summaries_counts_add_up",
        ),
        sa.CheckConstraint(
            "failure_rate IS NULL OR (failure_rate >= 0 AND failure_rate <= 1)",
            name="ck_synthetic_strategy_summaries_failure_rate_range",
        ),
        sa.CheckConstraint(
            "win_rate IS NULL OR (win_rate >= 0 AND win_rate <= 1)",
            name="ck_synthetic_strategy_summaries_win_rate_range",
        ),
        sa.CheckConstraint(
            "capital_utilization IS NULL OR (capital_utilization >= 0 AND capital_utilization <= 1)",
            name="ck_synthetic_strategy_summaries_capital_utilization_range",
        ),
        sa.CheckConstraint(
            "max_drawdown IS NULL OR max_drawdown >= 0",
            name="ck_synthetic_strategy_summaries_drawdown_nonneg",
        ),
        sa.CheckConstraint(
            "length(algorithm_version) > 0",
            name="ck_synthetic_strategy_summaries_algo_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(config_hash) > 0", name="ck_synthetic_strategy_summaries_config_hash_nonempty"
        ),
    )
    op.create_index(
        "ix_synthetic_strategy_summaries_strategy",
        "synthetic_strategy_summaries",
        ["strategy_code"],
    )
    op.create_index(
        "ix_synthetic_strategy_summaries_as_of", "synthetic_strategy_summaries", ["as_of"]
    )

    for table in ("synthetic_strategy_trades", "synthetic_strategy_summaries"):
        op.execute(f"GRANT SELECT, INSERT ON {table} TO argus_research;")
        op.execute(f"GRANT SELECT ON {table} TO argus_ingest;")
        op.execute(f"GRANT SELECT ON {table} TO argus_executor;")


def downgrade() -> None:
    for table in ("synthetic_strategy_trades", "synthetic_strategy_summaries"):
        op.execute(f"REVOKE ALL ON {table} FROM argus_research;")
        op.execute(f"REVOKE ALL ON {table} FROM argus_ingest;")
        op.execute(f"REVOKE ALL ON {table} FROM argus_executor;")

    op.drop_index(
        "ix_synthetic_strategy_summaries_as_of", table_name="synthetic_strategy_summaries"
    )
    op.drop_index(
        "ix_synthetic_strategy_summaries_strategy", table_name="synthetic_strategy_summaries"
    )
    op.drop_table("synthetic_strategy_summaries")

    op.drop_index("ix_synthetic_strategy_trades_as_of", table_name="synthetic_strategy_trades")
    op.drop_index("ix_synthetic_strategy_trades_token", table_name="synthetic_strategy_trades")
    op.drop_index("ix_synthetic_strategy_trades_strategy", table_name="synthetic_strategy_trades")
    op.drop_table("synthetic_strategy_trades")

"""FSR-08: Phase 10 executable-return primary result

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-04

ARGUS-INSTRUCTION-ID: argus-final-spec-recovery-001

Additive-only: no existing table or grant is altered, and no column is
dropped; migration `0033` (and everything before it) is unmodified. Two
CHECK constraints are replaced (drop + recreate under the same names is
not possible since their definitions change, so the old constraints are
dropped and new ones added) to loosen/extend rules that referred to the
pre-recovery mark-price-is-primary design -- this changes only what
future writes must satisfy, never any already-persisted row's data.

FSR-08 replaces the fixed-cost-haircut mark-price backtest with the
project's own real Phase 5 executable-return evidence as Phase 10's
primary result. ``entry_price_usd``/``exit_price_usd`` keep their
existing meaning (a descriptive mark price) but are no longer required
for a ``RESOLVED`` outcome; ``gross_return``/``net_return`` become the
PRIMARY executable-return result (from a real reverse-executable quote,
never a mark-price proxy); ``mark_gross_return``/``mark_net_return`` are
new columns preserving the OLD haircut-based mark-return computation as
an explicitly separate, descriptive-only sensitivity metric (FSR-08's
own "preserve it only as a separately labeled descriptive mark/
sensitivity metric if useful"). ``executable_horizon_label``/
``executable_status``/``executable_failure_class`` record which
executable-return evidence (and which real Phase 5 outcome family --
SUCCESS/FAILED/UNAVAILABLE/PENDING, mirroring
``argus.copyability.executable_returns.ExecutableReturnStatus``) backs
a trade's primary result -- an explicit no-route/insufficient-liquidity/
excessive-impact/quote-failure observation is recorded as a genuine
failure outcome, never dropped or silently folded into RESOLVED.
``synthetic_strategy_summaries.insufficient_executable_sample`` records
per-strategy when there is not enough real executable evidence to
report a meaningful result (FSR-08's own "do not silently fall back to
mark prices" rule).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OUTCOMES_SQL = (
    "'RESOLVED', 'FAILURE_NO_ENTRY_PRICE', 'FAILURE_NO_EXIT_TRIGGER', 'FAILURE_NO_EXIT_PRICE', "
    "'FAILURE_NO_EXECUTABLE_EVIDENCE', 'FAILURE_EXECUTABLE_QUOTE_FAILED'"
)


def upgrade() -> None:
    op.add_column(
        "synthetic_strategy_trades",
        sa.Column("executable_horizon_label", sa.String(8), nullable=True),
    )
    op.add_column(
        "synthetic_strategy_trades",
        sa.Column("executable_status", sa.String(16), nullable=True),
    )
    op.add_column(
        "synthetic_strategy_trades",
        sa.Column("executable_failure_class", sa.String(32), nullable=True),
    )
    op.add_column(
        "synthetic_strategy_trades",
        sa.Column("mark_gross_return", sa.Numeric(20, 15), nullable=True),
    )
    op.add_column(
        "synthetic_strategy_trades",
        sa.Column("mark_net_return", sa.Numeric(20, 15), nullable=True),
    )

    op.drop_constraint(
        "ck_synthetic_strategy_trades_outcome", "synthetic_strategy_trades", type_="check"
    )
    op.create_check_constraint(
        "ck_synthetic_strategy_trades_outcome",
        "synthetic_strategy_trades",
        f"outcome IN ({_OUTCOMES_SQL})",
    )

    op.drop_constraint(
        "ck_synthetic_strategy_trades_resolved_consistency",
        "synthetic_strategy_trades",
        type_="check",
    )
    op.create_check_constraint(
        "ck_synthetic_strategy_trades_resolved_consistency",
        "synthetic_strategy_trades",
        "(outcome = 'RESOLVED' AND exit_at IS NOT NULL AND net_return IS NOT NULL) "
        "OR (outcome != 'RESOLVED')",
    )

    op.drop_constraint(
        "ck_synthetic_strategy_trades_no_entry_price_consistency",
        "synthetic_strategy_trades",
        type_="check",
    )

    op.create_check_constraint(
        "ck_synthetic_strategy_trades_executable_status",
        "synthetic_strategy_trades",
        "executable_status IS NULL "
        "OR executable_status IN ('SUCCESS', 'FAILED', 'UNAVAILABLE', 'PENDING')",
    )

    op.add_column(
        "synthetic_strategy_summaries",
        sa.Column(
            "insufficient_executable_sample",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column(
        "synthetic_strategy_summaries", "insufficient_executable_sample", server_default=None
    )


def downgrade() -> None:
    op.drop_column("synthetic_strategy_summaries", "insufficient_executable_sample")

    op.drop_constraint(
        "ck_synthetic_strategy_trades_executable_status",
        "synthetic_strategy_trades",
        type_="check",
    )

    op.create_check_constraint(
        "ck_synthetic_strategy_trades_no_entry_price_consistency",
        "synthetic_strategy_trades",
        "(outcome = 'FAILURE_NO_ENTRY_PRICE' AND entry_price_usd IS NULL) "
        "OR (outcome != 'FAILURE_NO_ENTRY_PRICE')",
    )

    op.drop_constraint(
        "ck_synthetic_strategy_trades_resolved_consistency",
        "synthetic_strategy_trades",
        type_="check",
    )
    op.create_check_constraint(
        "ck_synthetic_strategy_trades_resolved_consistency",
        "synthetic_strategy_trades",
        "(outcome = 'RESOLVED' AND exit_at IS NOT NULL AND exit_price_usd IS NOT NULL "
        "AND net_return IS NOT NULL) OR (outcome != 'RESOLVED')",
    )

    op.drop_constraint(
        "ck_synthetic_strategy_trades_outcome", "synthetic_strategy_trades", type_="check"
    )
    op.create_check_constraint(
        "ck_synthetic_strategy_trades_outcome",
        "synthetic_strategy_trades",
        "outcome IN ('RESOLVED', 'FAILURE_NO_ENTRY_PRICE', 'FAILURE_NO_EXIT_TRIGGER', "
        "'FAILURE_NO_EXIT_PRICE')",
    )

    op.drop_column("synthetic_strategy_trades", "mark_net_return")
    op.drop_column("synthetic_strategy_trades", "mark_gross_return")
    op.drop_column("synthetic_strategy_trades", "executable_failure_class")
    op.drop_column("synthetic_strategy_trades", "executable_status")
    op.drop_column("synthetic_strategy_trades", "executable_horizon_label")

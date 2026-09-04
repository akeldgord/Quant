"""``synthetic_strategy_trades`` — MASTER_SPEC.md Phase 10 (SYNTHETIC
SUPER-WALLET), section 64. "Shadow only unless later approved" -- this
table records the result of a purely-backtested simulated one-unit
position; it has no bearing on and no connection to any live-execution
capability.

One row per simulated trade attempt: its entry/exit trigger evidence
references (CORE-004 "input references"), real point-in-time prices, a
disclosed realistic-cost haircut, and its resolved/failed outcome. A
trade that never found a matching exit trigger, or for which no
sufficiently fresh price was available, is recorded honestly as a
failure -- never silently dropped or fabricated as a win/loss.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

OUTCOME_RESOLVED = "RESOLVED"
OUTCOME_FAILURE_NO_ENTRY_PRICE = "FAILURE_NO_ENTRY_PRICE"
OUTCOME_FAILURE_NO_EXIT_TRIGGER = "FAILURE_NO_EXIT_TRIGGER"
OUTCOME_FAILURE_NO_EXIT_PRICE = "FAILURE_NO_EXIT_PRICE"
# FSR-08: the two primary executable-evidence failure modes -- an
# explicit no-route/insufficient-liquidity/excessive-impact/quote-
# failure observation (QUOTE_FAILED, with ``executable_failure_class``
# populated) is never dropped or folded into RESOLVED; NO_EXECUTABLE_
# EVIDENCE covers no matching Phase 5 opportunity/probe at all, or one
# still PENDING/UNAVAILABLE.
OUTCOME_FAILURE_NO_EXECUTABLE_EVIDENCE = "FAILURE_NO_EXECUTABLE_EVIDENCE"
OUTCOME_FAILURE_EXECUTABLE_QUOTE_FAILED = "FAILURE_EXECUTABLE_QUOTE_FAILED"

TRADE_OUTCOMES: tuple[str, ...] = (
    OUTCOME_RESOLVED,
    OUTCOME_FAILURE_NO_ENTRY_PRICE,
    OUTCOME_FAILURE_NO_EXIT_TRIGGER,
    OUTCOME_FAILURE_NO_EXIT_PRICE,
    OUTCOME_FAILURE_NO_EXECUTABLE_EVIDENCE,
    OUTCOME_FAILURE_EXECUTABLE_QUOTE_FAILED,
)

STRATEGY_CODES: tuple[str, ...] = ("A", "B", "C", "D", "E")


class SyntheticStrategyTrade(Base):
    __tablename__ = "synthetic_strategy_trades"
    __table_args__ = (
        UniqueConstraint(
            "strategy_code",
            "token_id",
            "entry_at",
            "as_of",
            "algorithm_version",
            "config_hash",
            name="uq_synthetic_strategy_trades_identity",
        ),
        CheckConstraint(
            "strategy_code IN ('A', 'B', 'C', 'D', 'E')", name="ck_synthetic_strategy_trades_code"
        ),
        CheckConstraint(
            "outcome IN ('RESOLVED', 'FAILURE_NO_ENTRY_PRICE', 'FAILURE_NO_EXIT_TRIGGER', "
            "'FAILURE_NO_EXIT_PRICE', 'FAILURE_NO_EXECUTABLE_EVIDENCE', "
            "'FAILURE_EXECUTABLE_QUOTE_FAILED')",
            name="ck_synthetic_strategy_trades_outcome",
        ),
        CheckConstraint(
            "(outcome = 'RESOLVED' AND exit_at IS NOT NULL AND net_return IS NOT NULL) "
            "OR (outcome != 'RESOLVED')",
            name="ck_synthetic_strategy_trades_resolved_consistency",
        ),
        CheckConstraint(
            "executable_status IS NULL "
            "OR executable_status IN ('SUCCESS', 'FAILED', 'UNAVAILABLE', 'PENDING')",
            name="ck_synthetic_strategy_trades_executable_status",
        ),
        CheckConstraint("cost_bps_applied >= 0", name="ck_synthetic_strategy_trades_cost_nonneg"),
        CheckConstraint(
            "length(algorithm_version) > 0",
            name="ck_synthetic_strategy_trades_algo_version_nonempty",
        ),
        CheckConstraint(
            "length(config_hash) > 0", name="ck_synthetic_strategy_trades_config_hash_nonempty"
        ),
    )

    trade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_code: Mapped[str] = mapped_column(String(4), nullable=False, index=True)
    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=False, index=True
    )

    entry_wallet_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=True
    )
    # {"type": "prospective_event"|"directional_edge"|"confirmation_event"|
    #  "convergence_event", "id": "..."} -- exactly which evidence row
    # triggered this simulated entry (CORE-004).
    entry_trigger_reference: Mapped[dict] = mapped_column(JSONB, nullable=False)
    entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Descriptive-only mark price (section 47/48) -- never the source of
    # the primary executable-return fields below (FSR-08).
    entry_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)

    exit_wallet_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=True
    )
    exit_trigger_reference: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)

    cost_bps_applied: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    # FSR-08: gross_return/net_return are now the PRIMARY executable-
    # return result, sourced from the entry wallet's own real Phase 5
    # reverse-executable quote at ``executable_horizon_label`` -- never a
    # mark-price-derived proxy. mark_gross_return/mark_net_return
    # preserve the OLD fixed-cost-haircut mark computation as an
    # explicitly separate, descriptive-only sensitivity metric.
    gross_return: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    net_return: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    executable_horizon_label: Mapped[str | None] = mapped_column(String(8), nullable=True)
    executable_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    executable_failure_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mark_gross_return: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    mark_net_return: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)

    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

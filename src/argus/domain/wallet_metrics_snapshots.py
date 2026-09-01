"""``wallet_metrics_snapshots`` — MASTER_SPEC.md section 37 (WALLET
FEATURE FINGERPRINT), section 40 (LOTTERY-DOMINANCE PROTECTION), section
41 (RECENCY AND ALPHA DECAY), Phase 3 (`argus-phase-3-001`).

Every scored wallet gets independent components, never reduced to one
opaque score internally (section 37's own explicit rule) -- the single
qualification number lives on ``wallet_score_snapshots``, derived FROM
these components, not the other way around. One row per
``(wallet_id, as_of, metrics_window)``: section 41 requires maintaining
lifetime, 180-day, 90-day, 30-day, and 7-day metrics where data exists,
so each recency window gets its own immutable, timestamped snapshot row
rather than one row with five parallel column sets -- a later window
addition or recomputation never has to migrate existing rows. (Named
``metrics_window``, not ``window`` -- a reserved SQL keyword that cannot
be used as a bare identifier in a CHECK constraint.)

Historical observations feeding these metrics are never deleted or
rewritten (section 41); a later reconstruction/rescoring appends new
snapshot rows, it never updates one in place.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

WINDOW_LIFETIME = "LIFETIME"
WINDOW_180D = "180D"
WINDOW_90D = "90D"
WINDOW_30D = "30D"
WINDOW_7D = "7D"

RECENCY_WINDOWS: tuple[str, ...] = (
    WINDOW_LIFETIME,
    WINDOW_180D,
    WINDOW_90D,
    WINDOW_30D,
    WINDOW_7D,
)

_WINDOW_LIST_SQL = ", ".join(f"'{w}'" for w in RECENCY_WINDOWS)


class WalletMetricsSnapshot(Base):
    """One point-in-time, one-window feature-fingerprint + lottery/
    recency metrics snapshot for one wallet."""

    __tablename__ = "wallet_metrics_snapshots"
    __table_args__ = (
        CheckConstraint(f"metrics_window IN ({_WINDOW_LIST_SQL})", name="ck_wallet_metrics_window"),
        CheckConstraint(
            "usable_closed_positions_count >= 0", name="ck_wallet_metrics_closed_positions_count"
        ),
        CheckConstraint(
            "distinct_tokens_with_usable_outcomes_count >= 0",
            name="ck_wallet_metrics_distinct_tokens_count",
        ),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )

    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    metrics_window: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    # Section 37 feature fingerprint -- 0-100 normalized, NULL when
    # evidence is insufficient to compute a component at all (never
    # defaulted to a fabricated midpoint).
    selection_skill: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    early_discovery_skill: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    entry_timing_skill: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    exit_skill: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    risk_control_skill: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    consistency: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    copyability: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    # Phase 4 depends on future prospective data this phase does not have;
    # NULL here is the explicit, versioned "not yet computable" status
    # (never fabricated), per this instruction's own explicit requirement.
    forward_information_value: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    recency: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    data_confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    insider_risk: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    cluster_risk: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    # Section 43: absence of proof of common control is NOT proof of
    # independence -- this is an estimate, never a real-world identity
    # claim (see argus.wallets.clustering).
    independence_probability: Mapped[Decimal | None] = mapped_column(Numeric(6, 5), nullable=True)
    predation_risk: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    automation_probability: Mapped[Decimal | None] = mapped_column(Numeric(6, 5), nullable=True)

    # Section 40 lottery-dominance metrics.
    median_return: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    trimmed_mean_return: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    winsorized_return: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    profit_factor: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    hit_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 5), nullable=True)
    largest_trade_contribution_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 5), nullable=True
    )
    top_three_trade_contribution_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 5), nullable=True
    )
    max_drawdown: Mapped[Decimal | None] = mapped_column(Numeric(6, 5), nullable=True)
    distinct_profitable_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lottery_dominated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Section 39 sample-size evidence gate inputs -- persisted directly on
    # the snapshot they informed, not re-derived from scratch elsewhere.
    usable_closed_positions_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    distinct_tokens_with_usable_outcomes_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    git_commit: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

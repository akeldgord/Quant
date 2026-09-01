"""``token_winner_milestones`` — versioned winner-category crossing events
(MASTER_SPEC.md section 32 WINNER DEFINITIONS, Phase 2 build items 9-10).

Winner categories (``MAJOR_WINNER >= 10x``, ``MONSTER >= 20x``,
``EXTREME >= 50x``) are research labels, never trading signals -- nothing
in this table or the code that writes it may create a trade intent, order,
or execution side effect (MASTER_SPEC.md's explicit prohibition, and this
instruction's required-implementation item 6).

Exactly one row may ever exist per ``(token_id, category,
winner_definition_version)`` -- the first genuine crossing under a given
versioned methodology is permanent; a later, weaker, stale, or
out-of-order observation must never rewrite it (idempotent milestone
detection, required test P2-T7). ``baseline_snapshot_id``/
``peak_snapshot_id`` point at the exact ``token_market_snapshots`` evidence
the baseline/peak were computed from, so "was the baseline actually a
reliably tradable state, not an untradeable zero-liquidity launch price"
is independently checkable, not merely asserted by this row.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

WINNER_CATEGORY_MAJOR_WINNER = "MAJOR_WINNER"
WINNER_CATEGORY_MONSTER = "MONSTER"
WINNER_CATEGORY_EXTREME = "EXTREME"

WINNER_CATEGORIES: tuple[str, ...] = (
    WINNER_CATEGORY_MAJOR_WINNER,
    WINNER_CATEGORY_MONSTER,
    WINNER_CATEGORY_EXTREME,
)

# The multiple (peak / baseline) required to cross each category, per
# MASTER_SPEC.md section 32. Kept next to the category constants so the
# watcher (argus.wallets.winner_watcher) and any test/report never
# hardcode these thresholds a second time.
WINNER_CATEGORY_THRESHOLDS: dict[str, Decimal] = {
    WINNER_CATEGORY_MAJOR_WINNER: Decimal("10"),
    WINNER_CATEGORY_MONSTER: Decimal("20"),
    WINNER_CATEGORY_EXTREME: Decimal("50"),
}


class TokenWinnerMilestone(Base):
    """One immutable, idempotent record of a token first crossing one
    versioned winner-category multiple."""

    __tablename__ = "token_winner_milestones"
    __table_args__ = (
        UniqueConstraint(
            "token_id",
            "category",
            "winner_definition_version",
            name="uq_token_winner_milestones_token_category_version",
        ),
        CheckConstraint(
            "category IN ('MAJOR_WINNER', 'MONSTER', 'EXTREME')",
            name="ck_token_winner_milestones_category",
        ),
        CheckConstraint(
            "baseline_price > 0", name="ck_token_winner_milestones_baseline_price_positive"
        ),
        CheckConstraint("peak_price > 0", name="ck_token_winner_milestones_peak_price_positive"),
    )

    milestone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=False, index=True
    )

    category: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    winner_definition_version: Mapped[str] = mapped_column(String(32), nullable=False)

    baseline_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    baseline_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    baseline_liquidity: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    baseline_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("token_market_snapshots.snapshot_id"), nullable=False
    )

    peak_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    peak_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    peak_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("token_market_snapshots.snapshot_id"), nullable=False
    )

    multiple_x: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    crossed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason_codes: Mapped[str | None] = mapped_column(String(256), nullable=True)

    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    build_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

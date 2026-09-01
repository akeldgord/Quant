"""``shadow_mark_outcomes`` — MASTER_SPEC.md section 47 (EXECUTABLE
RETURNS: "MARK RETURN... based on market-price data. Useful
descriptively."), Phase 4 (`argus-phase-4-001`).

Mark outcomes are descriptive only -- the primary outcome for
copyability is the executable return recorded on
``shadow_quote_probes(probe_kind='REVERSE_EXECUTABLE')`` (section 47's
own explicit statement). A position with a strongly positive mark return
and no executable exit route must never be read as having achieved that
return (section 48) -- this table and ``shadow_quote_probes`` are always
consulted together, never one in place of the other.

Same claim-based restart safety as ``shadow_quote_probes`` (section 84).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

# 5m/30m/1h/6h/24h mirror the executable horizons (section 47); 3d/7d are
# the explicitly optional longer mark-only horizons (section 47's own
# "may also be stored").
_HORIZONS_SQL = "'5m', '30m', '1h', '6h', '24h', '3d', '7d'"

OUTCOME_PENDING = "PENDING"
OUTCOME_RECORDED = "RECORDED"
OUTCOME_PRICE_UNAVAILABLE = "PRICE_UNAVAILABLE"
_OUTCOMES_SQL = "'PENDING', 'RECORDED', 'PRICE_UNAVAILABLE'"


class ShadowMarkOutcome(Base):
    """One scheduled (and, once processed, actually-recorded) mark-price
    outcome for one shadow position at one horizon."""

    __tablename__ = "shadow_mark_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "shadow_position_id", "horizon_label", name="uq_shadow_mark_position_horizon"
        ),
        CheckConstraint(f"horizon_label IN ({_HORIZONS_SQL})", name="ck_shadow_mark_horizon"),
        CheckConstraint(f"outcome IN ({_OUTCOMES_SQL})", name="ck_shadow_mark_outcome"),
    )

    shadow_mark_outcome_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    shadow_position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shadow_positions.shadow_position_id"),
        nullable=False,
        index=True,
    )
    horizon_label: Mapped[str] = mapped_column(String(8), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    actual_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mark_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    mark_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)

    outcome: Mapped[str] = mapped_column(String(24), nullable=False, default=OUTCOME_PENDING)

    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

"""``wallet_tier_history`` — MASTER_SPEC.md section 36 (WALLET LIFECYCLE),
Phase 3 (`argus-phase-3-001`).

Every wallet lifecycle-state transition is timestamped and immutable
(section 36's own explicit rule) -- this table is never updated or
deleted, only appended to. ``wallets.current_tier`` (added by this same
migration) is a denormalized cache of the latest row here, mirroring
``tokens.current_lifecycle_stage``'s exact precedent from Phase 2: cheap
reads from the cache, full point-in-time history never overwritten here.

A later score change does not rewrite an earlier tier transition -- it
can only ever produce a NEW transition row justified by a NEW
``wallet_score_snapshots`` row (``source_score_id``, nullable only for the
very first ``DISCOVERED`` transition a wallet gets on creation, before any
score exists yet).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

TIER_DISCOVERED = "DISCOVERED"
TIER_WATCH = "WATCH"
TIER_PROBATION = "PROBATION"
TIER_B = "B"
TIER_A = "A"
TIER_S = "S"
TIER_QUARANTINE = "QUARANTINE"
TIER_DORMANT = "DORMANT"
TIER_RETIRED = "RETIRED"

WALLET_TIERS: tuple[str, ...] = (
    TIER_DISCOVERED,
    TIER_WATCH,
    TIER_PROBATION,
    TIER_B,
    TIER_A,
    TIER_S,
    TIER_QUARANTINE,
    TIER_DORMANT,
    TIER_RETIRED,
)

# Tiers that would otherwise be interpreted as "potentially live eligible"
# (section 36) -- Phase 3 must never imply live authorization from tier
# alone; later live gates still apply on top of this (see this module's
# own docstring and argus.wallets.tier_lifecycle).
LIVE_ELIGIBLE_CANDIDATE_TIERS: frozenset[str] = frozenset({TIER_A, TIER_S})

_TIER_LIST_SQL = ", ".join(f"'{t}'" for t in WALLET_TIERS)


class WalletTierTransition(Base):
    """One immutable, timestamped wallet lifecycle-state transition."""

    __tablename__ = "wallet_tier_history"
    __table_args__ = (
        CheckConstraint(
            f"from_tier IS NULL OR from_tier IN ({_TIER_LIST_SQL})",
            name="ck_wallet_tier_history_from_tier",
        ),
        CheckConstraint(f"to_tier IN ({_TIER_LIST_SQL})", name="ck_wallet_tier_history_to_tier"),
        CheckConstraint("length(reason) > 0", name="ck_wallet_tier_history_reason_nonempty"),
    )

    transition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )
    source_score_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallet_score_snapshots.score_id"), nullable=True
    )

    from_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_tier: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    transitioned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

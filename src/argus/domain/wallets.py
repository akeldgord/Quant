"""``wallets`` — the candidate wallet identity registry (MASTER_SPEC.md
section 27, "Wallet domain").

Phase 2 created candidate wallets only -- no score, tier, cluster, or
live-eligibility computation existed yet (``wallet_metrics_snapshots``/
``wallet_score_snapshots``/``wallet_tier_history``). Phase 3
(`argus-phase-3-001`) adds exactly those, plus this table's own
``current_tier`` column: a denormalized cache of the latest
``wallet_tier_history`` row, mirroring ``tokens.current_lifecycle_stage``'s
identical precedent from Phase 2 -- cheap reads from the cache, the full
point-in-time, immutable, timestamped transition history lives in
``wallet_tier_history`` and is never overwritten here. A row's existence
still means only "ARGUS has identified this address as worth further
study, and possibly since assessed it" -- an ``A``/``S`` tier is
"potentially live eligible" evidence, never live authorization by itself
(MASTER_SPEC.md section 36; later live gates still apply). The reason a
wallet was first identified is recorded separately and permanently in
``wallet_discovery_events`` -- never on this table, and never lost.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base


class Wallet(Base):
    """One candidate Solana wallet address ARGUS has discovered."""

    __tablename__ = "wallets"
    __table_args__ = (UniqueConstraint("wallet_address", name="uq_wallets_wallet_address"),)

    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_address: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    first_discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Denormalized cache of the latest wallet_tier_history row; NULL until
    # Phase 3 records this wallet's first transition (added by migration
    # 0010 -- pre-existing rows from Phase 2 have no tier yet).
    current_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

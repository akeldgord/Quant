"""``wallets`` — the candidate wallet identity registry (MASTER_SPEC.md
section 27, "Wallet domain").

Phase 2 creates candidate wallets only -- no score, tier, cluster, or
live-eligibility computation exists yet (those are ``wallet_metrics_
snapshots``/``wallet_score_snapshots``/``wallet_tier_history``, explicitly
later-phase responsibilities per MASTER_SPEC.md section 27; this
instruction's required-implementation item 5 explicitly says "Do not
implement or claim Phase 3 wallet scoring"). A row here means only "ARGUS
has identified this address as worth further study," never "this wallet
is good." The reason it was identified is recorded separately and
permanently in ``wallet_discovery_events`` -- never on this table, and
never lost.
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

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

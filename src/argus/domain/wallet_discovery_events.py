"""``wallet_discovery_events`` — permanent wallet-discovery provenance
(MASTER_SPEC.md section 28 WALLET DISCOVERY CHANNELS, section 29 WALLET
DISCOVERY PROVENANCE, section 30 CRITICAL ANTI-SURVIVORSHIP RULE).

Records the exact fields section 29 requires: wallet, discovered_at,
discovery_channel, nullable trigger_token/trigger_wallet/trigger_event,
trigger_reason, algorithm_version. "Never lose the reason ARGUS began
studying a wallet" -- this table is never updated or deleted.

Phase 2 implements two of the four discovery channels (``DISC-001``
historical winner archaeology, ``DISC-002`` prospective winner
archaeology); ``DISC-003``/``DISC-004`` (Alpha-Ancestry upstream and
peer/network discovery) require the wallet-relationship graph built in a
later phase and are represented here only as forward-compatible schema
values, never emitted by Phase 2 code.

Section 30's anti-survivorship rule: every row here is, by construction,
exactly the record of a discovery-contaminated (wallet, token) pair --
this wallet's later QUALIFICATION SCORE (a later phase) must exclude
observations tied to ``trigger_token_id`` when computing that wallet's
score. ``exclusion_reason`` is stored literally (always
``'DISCOVERY_CONTAMINATION'`` today) so that exclusion is directly
queryable evidence, not an inference a later phase has to re-derive.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY = "HISTORICAL_WINNER_ARCHAEOLOGY"
DISCOVERY_CHANNEL_PROSPECTIVE_WINNER_ARCHAEOLOGY = "PROSPECTIVE_WINNER_ARCHAEOLOGY"
DISCOVERY_CHANNEL_ALPHA_ANCESTRY_UPSTREAM = "ALPHA_ANCESTRY_UPSTREAM"
DISCOVERY_CHANNEL_PEER_NETWORK = "PEER_NETWORK"

DISCOVERY_CHANNELS: tuple[str, ...] = (
    DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY,
    DISCOVERY_CHANNEL_PROSPECTIVE_WINNER_ARCHAEOLOGY,
    DISCOVERY_CHANNEL_ALPHA_ANCESTRY_UPSTREAM,
    DISCOVERY_CHANNEL_PEER_NETWORK,
)

EXCLUSION_REASON_DISCOVERY_CONTAMINATION = "DISCOVERY_CONTAMINATION"

_DISCOVERY_CHANNEL_LIST_SQL = ", ".join(f"'{c}'" for c in DISCOVERY_CHANNELS)


class WalletDiscoveryEvent(Base):
    """One permanent record of why ARGUS began studying one wallet."""

    __tablename__ = "wallet_discovery_events"
    __table_args__ = (
        UniqueConstraint(
            "wallet_id",
            "discovery_channel",
            "trigger_token_id",
            name="uq_wallet_discovery_events_wallet_channel_token",
        ),
        CheckConstraint(
            f"discovery_channel IN ({_DISCOVERY_CHANNEL_LIST_SQL})",
            name="ck_wallet_discovery_events_channel",
        ),
        CheckConstraint(
            "exclusion_reason = 'DISCOVERY_CONTAMINATION'",
            name="ck_wallet_discovery_events_exclusion_reason",
        ),
    )

    discovery_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )

    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    discovery_channel: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    trigger_token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=True, index=True
    )
    trigger_wallet_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=True
    )
    trigger_event: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trigger_reason: Mapped[str] = mapped_column(String(256), nullable=False)

    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)

    # Permanent per section 30 -- always 'DISCOVERY_CONTAMINATION' today
    # (Phase 2 has no other exclusion reason), enforced by the CHECK
    # constraint above rather than merely defaulted, so this row can never
    # be silently reinterpreted as "not contaminated."
    exclusion_reason: Mapped[str] = mapped_column(
        String(32), nullable=False, default=EXCLUSION_REASON_DISCOVERY_CONTAMINATION
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

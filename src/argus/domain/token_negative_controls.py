"""``token_negative_controls`` — negative-control archaeology schema
support (MASTER_SPEC.md section 31 NEGATIVE-CONTROL ARCHAEOLOGY, Phase 2
build item 13).

Phase 2 acceptance requires schema and a deterministic round-trip, not a
completed negative-control study (the instruction's explicit scope limit,
required test P2-T9): this table only records that a winner token has
been matched against a control token that did NOT become an extreme
winner, along the matching dimensions section 31 names (launch period,
venue, early liquidity, early market cap, early transaction activity), so
a later phase can ask "do the winner's early wallets actually look
different from a similar token's early wallets, or are they just generic
snipers/launchpad regulars/bots?" No score or live-eligibility decision
is derived from a row here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base


class TokenNegativeControl(Base):
    """One matched (winner token, control token) pair for negative-control
    archaeology, with the matching dimensions section 31 requires."""

    __tablename__ = "token_negative_controls"
    __table_args__ = (
        UniqueConstraint(
            "winner_token_id",
            "control_token_id",
            "method_version",
            name="uq_token_negative_controls_winner_control_method",
        ),
        CheckConstraint(
            "winner_token_id <> control_token_id",
            name="ck_token_negative_controls_distinct_tokens",
        ),
    )

    control_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    winner_token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=False, index=True
    )
    control_token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=False, index=True
    )
    method_version: Mapped[str] = mapped_column(String(32), nullable=False)

    launch_period_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    venue_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    early_liquidity_delta_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    early_market_cap_delta_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True
    )
    early_tx_activity_delta_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True
    )

    evidence_reference: Mapped[str | None] = mapped_column(String(256), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

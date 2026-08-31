"""``swaps`` — canonical, deterministically-parsed swap/transfer records.

Schema per MASTER_SPEC.md section 21 (GENERIC TRANSACTION/SWAP PARSER).
Derived from ``chain_events.raw_payload`` by
``argus.parsing.generic_parser``; safe to recompute/re-derive from the
immutable raw evidence under a new ``parser_version`` without losing any
point-in-time truth.

``classification`` is one of the seven canonical values the parser assigns
deterministically (never a per-DEX special case): ``SWAP_SIMPLE``,
``SWAP_COMPLEX``, ``TRANSFER_IN``, ``TRANSFER_OUT``, ``TOKEN_CREATE``,
``LP_ACTION``, ``UNKNOWN``. An ``UNKNOWN``/ambiguous classification is
preserved for research but is mechanically excluded from ever producing a
live-copy signal (enforced by callers, not by this table -- see
``generic_parser.ParsedSwap.is_copy_eligible``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base


class Swap(Base):
    """One deterministically-classified swap/transfer derived from a
    ``chain_events`` row."""

    __tablename__ = "swaps"

    swap_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chain_events.event_id"), nullable=False, index=True
    )

    wallet_address: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    classification: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    input_mint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_amount_raw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    input_amount_ui: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)

    output_mint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_amount_raw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    output_amount_ui: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)

    network_fee_raw: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    slot: Mapped[int] = mapped_column(BigInteger, nullable=False)
    block_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # 0.0-1.0; low confidence combined with classification=UNKNOWN is the
    # mechanical signal that this must never drive a live-copy decision.
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

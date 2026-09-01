"""``early_buyers`` — recovered early net-buyer wallets for a token
(MASTER_SPEC.md section 33 EARLY-BUYER EXTRACTION).

One row per distinct meaningful net buyer per token -- "distinct" and
"net" both matter: a wallet is represented once even if it bought in
several transactions (its first meaningful net-positive balance change is
what ``first_buy_slot``/``first_buy_time`` record), which is what makes
``uq_early_buyers_token_wallet`` a safe, reproducible idempotency key
(required test P2-T5: replaying identical evidence, in any page/delivery
order, must produce the same distinct-buyer set with no duplicate rows).

Tag columns (``possible_deployer``/``possible_insider``/
``possible_bundler``/``possible_funder_related``/``possible_bot``) are
purely informational, never a deletion/exclusion filter applied here --
MASTER_SPEC.md section 33's explicit instruction: "These wallets may
contain information even when prohibited from copy trading." A later
phase may down-weight or exclude a tagged wallet from a live-copy
decision; this table never does that itself.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base
from argus.domain.token_market_snapshots import MARKET_STATE_CONFIDENCE_LEVELS

_MARKET_STATE_CONFIDENCE_LIST_SQL = ", ".join(
    f"'{level}'" for level in MARKET_STATE_CONFIDENCE_LEVELS
)


class EarlyBuyer(Base):
    """One distinct, meaningful net-buyer wallet recovered for one token
    by exactly one ``archaeology_runs`` execution."""

    __tablename__ = "early_buyers"
    __table_args__ = (
        UniqueConstraint("token_id", "wallet_id", name="uq_early_buyers_token_wallet"),
        CheckConstraint(
            f"entry_market_state_confidence IS NULL OR "
            f"entry_market_state_confidence IN ({_MARKET_STATE_CONFIDENCE_LIST_SQL})",
            name="ck_early_buyers_entry_market_state_confidence",
        ),
        CheckConstraint("amount_raw > 0", name="ck_early_buyers_amount_positive"),
        CheckConstraint("sequence_number >= 1", name="ck_early_buyers_sequence_positive"),
    )

    early_buyer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=False, index=True
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )
    source_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("archaeology_runs.run_id"), nullable=False, index=True
    )

    first_buy_slot: Mapped[int] = mapped_column(BigInteger, nullable=False)
    first_buy_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Stable ordering among this token's recovered buyers -- ties broken
    # deterministically (see argus.wallets.early_buyers) so a replay in a
    # different page/delivery order still reproduces the identical sequence.
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    venue: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lifecycle_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)

    entry_price_estimate: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    entry_market_state_confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    token_age_seconds: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    amount_raw: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_decimals: Mapped[int] = mapped_column(Integer, nullable=False)
    usd_estimate: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)

    possible_deployer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    possible_insider: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    possible_bundler: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    possible_funder_related: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    possible_bot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    evidence_reference: Mapped[str] = mapped_column(String(256), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

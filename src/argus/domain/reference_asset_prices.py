"""``reference_asset_prices`` — point-in-time SOL/USD and USDC/USD price
ledger (MASTER_SPEC.md section 25 REFERENCE PRICE LEDGER, Phase 2 build
item 3).

Historical USD calculations must use point-in-time reference prices where
practical, never a single current-day constant -- and, per the spec's
explicit warning, USDC is never permanently assumed to equal exactly
USD 1 (its price is recorded from a real source like everything else,
even though it will typically land very close to 1). Append-only:
``(asset, source, observed_at)`` deduplicates a replayed observation; a
later observation never overwrites an earlier point-in-time belief.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base


class ReferenceAssetPrice(Base):
    """One point-in-time reference price for a non-token asset (SOL, USDC,
    ...) used to convert raw on-chain amounts into USD estimates."""

    __tablename__ = "reference_asset_prices"
    __table_args__ = (
        UniqueConstraint(
            "asset",
            "source",
            "observed_at",
            name="uq_reference_asset_prices_asset_source_observed_at",
        ),
        CheckConstraint("price_usd > 0", name="ck_reference_asset_prices_price_positive"),
    )

    price_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    asset: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    # 0.0-1.0, same scale as swaps.confidence.
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

"""Reference asset price recording (MASTER_SPEC.md section 25 REFERENCE
PRICE LEDGER; Phase 2 build item 3).
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from argus.domain.reference_asset_prices import ReferenceAssetPrice

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclasses.dataclass(frozen=True, slots=True)
class ReferencePriceDraft:
    asset: str
    price_usd: Decimal
    source: str
    observed_at: datetime
    confidence: Decimal


async def record_reference_price(
    session: AsyncSession, draft: ReferencePriceDraft, *, now: datetime
) -> uuid.UUID:
    """Idempotent on ``(asset, source, observed_at)`` -- a replayed
    observation never overwrites an earlier point-in-time price belief."""
    price_id = uuid.uuid4()
    stmt = (
        pg_insert(ReferenceAssetPrice)
        .values(
            price_id=price_id,
            asset=draft.asset,
            price_usd=draft.price_usd,
            source=draft.source,
            observed_at=draft.observed_at,
            confidence=draft.confidence,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["asset", "source", "observed_at"])
        .returning(ReferenceAssetPrice.price_id)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is not None:
        await session.flush()
        return uuid.UUID(str(row))

    existing = (
        await session.execute(
            select(ReferenceAssetPrice.price_id).where(
                ReferenceAssetPrice.asset == draft.asset,
                ReferenceAssetPrice.source == draft.source,
                ReferenceAssetPrice.observed_at == draft.observed_at,
            )
        )
    ).scalar_one()
    return uuid.UUID(str(existing))


async def latest_price_at_or_before(
    session: AsyncSession, *, asset: str, at: datetime
) -> ReferenceAssetPrice | None:
    """The most recent reference price for ``asset`` observed at or
    before ``at`` -- the point-in-time lookup Phase 2's USD estimates
    (early-buyer extraction, market snapshots) must use instead of
    "whatever the latest price is now" (MASTER_SPEC.md section 25:
    "Historical USD calculations should use point-in-time reference
    prices where practical")."""
    return (
        await session.execute(
            select(ReferenceAssetPrice)
            .where(ReferenceAssetPrice.asset == asset, ReferenceAssetPrice.observed_at <= at)
            .order_by(ReferenceAssetPrice.observed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

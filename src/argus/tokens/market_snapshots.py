"""Point-in-time token lifecycle + market-state snapshot recording
(MASTER_SPEC.md section 24 TOKEN LIFECYCLE MODEL, section 26 HISTORICAL
MARKET-STATE RULE; Phase 2 build items 3-4).

``record_snapshot`` is the single write path for
``argus.domain.token_market_snapshots.TokenMarketSnapshot`` -- it never
overwrites an earlier observation (idempotent on ``(token_id, source,
observed_at)``, matching the table's own unique constraint) and never
backfills a numeric field with today's value: every caller must supply
``None`` for anything it cannot honestly support from its own evidence,
which this module passes straight through.
"""

from __future__ import annotations

import dataclasses
import hashlib
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Final

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from argus.domain.token_market_snapshots import TokenMarketSnapshot
from argus.domain.tokens import Token

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

ALGORITHM_VERSION: Final[str] = "token_market_snapshot_v1"
BUILD_HASH: Final[str] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclasses.dataclass(frozen=True, slots=True)
class MarketSnapshotDraft:
    token_id: uuid.UUID
    observed_at: datetime
    lifecycle_stage: str
    source: str
    chain_time: datetime | None = None
    venue: str | None = None
    venue_program: str | None = None
    pool_or_curve_address: str | None = None
    price_usd: Decimal | None = None
    supply_raw: int | None = None
    liquidity_usd: Decimal | None = None
    fdv_usd: Decimal | None = None
    market_cap_usd: Decimal | None = None
    market_state_confidence: str | None = None
    evidence_reference: str | None = None


async def record_snapshot(
    session: AsyncSession, draft: MarketSnapshotDraft, *, now: datetime
) -> uuid.UUID:
    """Inserts one snapshot, or returns the existing snapshot_id
    unchanged if ``(token_id, source, observed_at)`` was already
    recorded -- idempotent replay, never a silent overwrite of an earlier
    point-in-time belief."""
    snapshot_id = uuid.uuid4()
    stmt = (
        pg_insert(TokenMarketSnapshot)
        .values(
            snapshot_id=snapshot_id,
            token_id=draft.token_id,
            observed_at=draft.observed_at,
            chain_time=draft.chain_time,
            lifecycle_stage=draft.lifecycle_stage,
            venue=draft.venue,
            venue_program=draft.venue_program,
            pool_or_curve_address=draft.pool_or_curve_address,
            price_usd=draft.price_usd,
            supply_raw=draft.supply_raw,
            liquidity_usd=draft.liquidity_usd,
            fdv_usd=draft.fdv_usd,
            market_cap_usd=draft.market_cap_usd,
            market_state_confidence=draft.market_state_confidence,
            source=draft.source,
            evidence_reference=draft.evidence_reference,
            algorithm_version=ALGORITHM_VERSION,
            build_hash=BUILD_HASH,
            created_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=["token_id", "source", "observed_at"],
        )
        .returning(TokenMarketSnapshot.snapshot_id)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is not None:
        await session.flush()
        return uuid.UUID(str(row))

    existing = (
        await session.execute(
            select(TokenMarketSnapshot.snapshot_id).where(
                TokenMarketSnapshot.token_id == draft.token_id,
                TokenMarketSnapshot.source == draft.source,
                TokenMarketSnapshot.observed_at == draft.observed_at,
            )
        )
    ).scalar_one()
    return uuid.UUID(str(existing))


async def update_token_lifecycle_cache(
    session: AsyncSession, *, token_id: uuid.UUID, lifecycle_stage: str
) -> None:
    """Refreshes ``tokens.current_lifecycle_stage`` -- a denormalized read
    cache only; the point-in-time history of record lives in
    ``token_market_snapshots`` and is never touched by this function."""
    token = (await session.execute(select(Token).where(Token.token_id == token_id))).scalar_one()
    token.current_lifecycle_stage = lifecycle_stage
    await session.flush()

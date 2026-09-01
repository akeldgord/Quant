"""Mark-outcome execution (MASTER_SPEC.md section 47: "MARK RETURN --
based on market-price data. Useful descriptively."). Same claim-based
restart safety as ``argus.shadow.quote_jobs`` (section 84).

Mark outcomes are explicitly descriptive-only -- never the primary
copyability outcome (that is ``shadow_quote_probes(probe_kind=
'REVERSE_EXECUTABLE')``, section 47's own explicit statement). A missing
or unavailable market price is recorded as ``PRICE_UNAVAILABLE``, never
silently treated as a zero return.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from sqlalchemy import or_, select

from argus.domain.shadow_mark_outcomes import (
    OUTCOME_PRICE_UNAVAILABLE,
    OUTCOME_RECORDED,
    ShadowMarkOutcome,
)
from argus.domain.shadow_positions import ShadowPosition

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from argus.clock import Clock
    from argus.providers import MarketDataProvider

ALGORITHM_VERSION: Final[str] = "shadow_mark_jobs_v1"


class SimulatedWorkerCrash(RuntimeError):
    """Same crash-injection convention as ``argus.shadow.quote_jobs`` --
    only ever raised on an explicit test request."""


async def _claim_due_mark_outcomes(
    session: AsyncSession, *, now: datetime, worker_id: str, stale_after: timedelta, limit: int
) -> list[uuid.UUID]:
    stale_cutoff = now - stale_after
    candidates = (
        (
            await session.execute(
                select(ShadowMarkOutcome)
                .where(
                    ShadowMarkOutcome.due_at <= now,
                    ShadowMarkOutcome.actual_at.is_(None),
                    or_(
                        ShadowMarkOutcome.claimed_at.is_(None),
                        ShadowMarkOutcome.claimed_at < stale_cutoff,
                    ),
                )
                .order_by(ShadowMarkOutcome.due_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    claimed_ids: list[uuid.UUID] = []
    for row in candidates:
        row.claimed_at = now
        row.claimed_by = worker_id
        claimed_ids.append(row.shadow_mark_outcome_id)
    await session.flush()
    return claimed_ids


async def _execute_and_record_mark_outcome(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    outcome_id: uuid.UUID,
    market_provider: MarketDataProvider,
    clock: Clock,
    _simulate_crash_after: str | None = None,
) -> ShadowMarkOutcome:
    async with session_factory() as session:
        row = await session.get(ShadowMarkOutcome, outcome_id)
        assert row is not None
        position = await session.get(ShadowPosition, row.shadow_position_id)
        assert position is not None
        mint = position.output_mint
        entry_price_usd = position.entry_price_usd

    price_usd: Decimal | None = None
    try:
        snapshot = await market_provider.token_snapshot(mint)
        price_usd = snapshot.price_usd
        provider_name = snapshot.provider
    except Exception:  # noqa: BLE001 -- a market-data failure is an honest PRICE_UNAVAILABLE
        provider_name = None
    actual_at = clock.utc_now()

    if _simulate_crash_after == "quote":
        raise SimulatedWorkerCrash(f"simulated crash after price lookup (outcome_id={outcome_id})")

    async with session_factory() as session, session.begin():
        row = await session.get(ShadowMarkOutcome, outcome_id)
        assert row is not None
        if row.actual_at is not None:
            return row  # already recorded -- idempotent no-op (section 84)

        row.actual_at = actual_at
        row.provider = provider_name
        if price_usd is None:
            row.outcome = OUTCOME_PRICE_UNAVAILABLE
            row.mark_price_usd = None
            row.mark_return_pct = None
        else:
            row.outcome = OUTCOME_RECORDED
            row.mark_price_usd = price_usd
            if entry_price_usd is not None and entry_price_usd > 0:
                row.mark_return_pct = (price_usd - entry_price_usd) / entry_price_usd
            else:
                row.mark_return_pct = None
        await session.flush()
        return row


async def run_due_mark_outcomes(
    session_factory: async_sessionmaker[AsyncSession],
    market_provider: MarketDataProvider,
    *,
    clock: Clock,
    now: datetime,
    worker_id: str = "mark-outcome-worker",
    stale_after: timedelta = timedelta(seconds=30),
    limit: int = 50,
    _simulate_crash_after: str | None = None,
) -> list[ShadowMarkOutcome]:
    """Claims and executes every currently-due mark-outcome row -- same
    claim/execute/record restart-safe shape as
    ``argus.shadow.quote_jobs.run_due_entry_probes``."""
    async with session_factory() as session, session.begin():
        claimed_ids = await _claim_due_mark_outcomes(
            session, now=now, worker_id=worker_id, stale_after=stale_after, limit=limit
        )
    if _simulate_crash_after == "claim":
        raise SimulatedWorkerCrash("simulated crash after claim")

    results = []
    for outcome_id in claimed_ids:
        results.append(
            await _execute_and_record_mark_outcome(
                session_factory,
                outcome_id=outcome_id,
                market_provider=market_provider,
                clock=clock,
                _simulate_crash_after=_simulate_crash_after,
            )
        )
    return results

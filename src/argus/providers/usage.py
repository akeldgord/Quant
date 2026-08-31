"""Provider request/streaming usage accounting and reporting.

MASTER_SPEC.md section 14 (PROVIDER COST GUARD). The ``provider_usage``
schema already exists from Phase 0
(:mod:`argus.domain.provider_usage`); this module is the Phase 1 logic
that actually writes rows for every outbound request and streaming tick,
and reports today / month-to-date / 30-day-projected usage against a
configured monthly allowance, with warnings at 70/85/95% (COST-002: never
auto-upgrade -- this module contains no code path that changes a
provider's tier or enables a paid feature; it only reports numbers).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Final, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from argus.clock import Clock
from argus.domain.provider_usage import ProviderUsage

WARNING_THRESHOLDS_PCT: Final[tuple[int, ...]] = (70, 85, 95)


@dataclasses.dataclass(frozen=True, slots=True)
class RequestUsageRecord:
    """One outbound HTTP/RPC request (section 14's required fields)."""

    provider: str
    endpoint: str
    request_class: str
    requested_at: datetime
    status: str
    cache_hit: bool
    response_at: datetime | None = None
    latency_ms: int | None = None
    retry_count: int = 0
    estimated_credits: Decimal | None = None
    bytes_received: int | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class StreamingUsageRecord:
    """One streaming accounting tick (section 14: "must additionally
    record connection, subscription, reconnect, bytes, and
    estimated-credit counters")."""

    provider: str
    endpoint: str
    request_class: str
    requested_at: datetime
    connection_count: int
    subscription_count: int
    reconnect_count: int
    bytes_received: int | None = None
    estimated_streaming_credits: Decimal | None = None


class UsageRecorder(Protocol):
    """What a provider adapter needs to record usage for every real
    outbound call it makes -- satisfied by :class:`SqlUsageRecorder` or an
    in-memory fake for tests."""

    async def record_request(self, record: RequestUsageRecord) -> None: ...
    async def record_streaming(self, record: StreamingUsageRecord) -> None: ...


class SqlUsageRecorder:
    """Writes usage rows via a session factory, not a bound session.

    Phase 1 remediation round 2 (argus-phase-1-remediation-002), finding
    #2's "usage accounting uses a safe independent transaction path":
    every real ingestion adapter call (Helius RPC, WebSocket connect,
    every wallet's subscribe) records usage from whatever task happens to
    be running at the time -- if usage recording shared a session with
    that task's own reconciliation work, a usage-write failure could
    abort reconciliation's pending transaction, and vice versa. Each
    ``record_*`` call here opens, commits, and closes its own session, so
    usage accounting can never corrupt or be corrupted by any other
    concurrent unit of work."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def record_request(self, record: RequestUsageRecord) -> None:
        now = record.response_at or record.requested_at
        async with self._sessionmaker() as session, session.begin():
            session.add(
                ProviderUsage(
                    provider=record.provider,
                    endpoint=record.endpoint,
                    request_class=record.request_class,
                    requested_at=record.requested_at,
                    response_at=record.response_at,
                    latency_ms=record.latency_ms,
                    status=record.status,
                    retry_count=record.retry_count,
                    estimated_credits=record.estimated_credits,
                    bytes_received=record.bytes_received,
                    cache_hit=record.cache_hit,
                    created_at=now,
                )
            )

    async def record_streaming(self, record: StreamingUsageRecord) -> None:
        async with self._sessionmaker() as session, session.begin():
            session.add(
                ProviderUsage(
                    provider=record.provider,
                    endpoint=record.endpoint,
                    request_class=record.request_class,
                    requested_at=record.requested_at,
                    status="streaming",
                    retry_count=0,
                    cache_hit=False,
                    connection_count=record.connection_count,
                    subscription_count=record.subscription_count,
                    reconnect_count=record.reconnect_count,
                    bytes_received=record.bytes_received,
                    estimated_streaming_credits=record.estimated_streaming_credits,
                    created_at=record.requested_at,
                )
            )


@dataclasses.dataclass(frozen=True, slots=True)
class ProviderUsageSummary:
    provider: str
    today_credits: Decimal
    month_to_date_credits: Decimal
    projected_30_day_credits: Decimal
    monthly_allowance: Decimal | None
    projected_pct_of_allowance: Decimal | None
    warning_thresholds_triggered: tuple[int, ...]

    @property
    def any_warning_triggered(self) -> bool:
        return bool(self.warning_thresholds_triggered)


class UsageReporter:
    """Reports today/month-to-date/30-day-projected usage per provider.

    ``now_provider`` defaults to :meth:`Clock.utc_now` but is injectable so
    tests can pin "now" without needing wall-clock-dependent assertions.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        now_provider: Callable[[], datetime] | None = None,
        warning_thresholds_pct: tuple[int, ...] = WARNING_THRESHOLDS_PCT,
    ) -> None:
        self._session = session
        self._now_provider = now_provider or Clock().utc_now
        self._warning_thresholds_pct = warning_thresholds_pct

    async def _sum_credits(self, provider: str, *, since: datetime) -> Decimal:
        result = await self._session.execute(
            select(
                func.coalesce(
                    func.sum(
                        func.coalesce(ProviderUsage.estimated_credits, 0)
                        + func.coalesce(ProviderUsage.estimated_streaming_credits, 0)
                    ),
                    0,
                )
            ).where(ProviderUsage.provider == provider, ProviderUsage.created_at >= since)
        )
        value = result.scalar_one()
        return value if isinstance(value, Decimal) else Decimal(str(value))

    async def summarize(
        self, provider: str, *, monthly_allowance: Decimal | None = None
    ) -> ProviderUsageSummary:
        now = self._now_provider()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = today_start.replace(day=1)

        today_credits = await self._sum_credits(provider, since=today_start)
        month_to_date_credits = await self._sum_credits(provider, since=month_start)

        days_elapsed = max((now - month_start).total_seconds() / 86400.0, 1.0 / 86400.0)
        projected_30_day = (month_to_date_credits / Decimal(str(days_elapsed))) * Decimal(30)

        pct: Decimal | None = None
        triggered: tuple[int, ...] = ()
        if monthly_allowance is not None and monthly_allowance > 0:
            pct = (projected_30_day / monthly_allowance) * Decimal(100)
            triggered = tuple(t for t in self._warning_thresholds_pct if pct >= t)

        return ProviderUsageSummary(
            provider=provider,
            today_credits=today_credits,
            month_to_date_credits=month_to_date_credits,
            projected_30_day_credits=projected_30_day,
            monthly_allowance=monthly_allowance,
            projected_pct_of_allowance=pct,
            warning_thresholds_triggered=triggered,
        )

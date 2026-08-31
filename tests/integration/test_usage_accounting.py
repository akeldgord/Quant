from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from argus.config import load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.providers.usage import (
    RequestUsageRecord,
    SqlUsageRecorder,
    StreamingUsageRecord,
    UsageReporter,
)

pytestmark = pytest.mark.asyncio

PROVIDER = "usage-test-helius"
FIXED_NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


async def test_usage_summary_today_mtd_projection_and_warnings(admin_engine) -> None:
    config = load_config()
    ingest_info = connection_for_role(config, DbRole.INGEST)
    ingest_engine = create_async_engine(ingest_info.as_asyncpg_url())
    research_info = connection_for_role(config, DbRole.RESEARCH)
    research_engine = create_async_engine(research_info.as_asyncpg_url())

    try:
        ingest_sessionmaker = async_sessionmaker(ingest_engine, expire_on_commit=False)
        async with ingest_sessionmaker() as session:
            recorder = SqlUsageRecorder(session)

            # Today: an ordinary request (10 credits).
            await recorder.record_request(
                RequestUsageRecord(
                    provider=PROVIDER,
                    endpoint="/getTransaction",
                    request_class="P6_background_research",
                    requested_at=datetime(2026, 8, 15, 8, 0, 0, tzinfo=UTC),
                    status="ok",
                    cache_hit=False,
                    estimated_credits=Decimal("10"),
                )
            )
            # Today: a streaming tick (3 credits).
            await recorder.record_streaming(
                StreamingUsageRecord(
                    provider=PROVIDER,
                    endpoint="wss://stream",
                    request_class="P6_background_research",
                    requested_at=datetime(2026, 8, 15, 9, 0, 0, tzinfo=UTC),
                    connection_count=1,
                    subscription_count=1,
                    reconnect_count=0,
                    estimated_streaming_credits=Decimal("3"),
                )
            )
            # Earlier this month, not today (5 credits) -- counts toward MTD only.
            await recorder.record_request(
                RequestUsageRecord(
                    provider=PROVIDER,
                    endpoint="/getTransaction",
                    request_class="P6_background_research",
                    requested_at=datetime(2026, 8, 5, 10, 0, 0, tzinfo=UTC),
                    status="ok",
                    cache_hit=False,
                    estimated_credits=Decimal("5"),
                )
            )
            # Last month -- must not count toward today or MTD at all.
            await recorder.record_request(
                RequestUsageRecord(
                    provider=PROVIDER,
                    endpoint="/getTransaction",
                    request_class="P6_background_research",
                    requested_at=datetime(2026, 7, 20, 10, 0, 0, tzinfo=UTC),
                    status="ok",
                    cache_hit=False,
                    estimated_credits=Decimal("100"),
                )
            )
            # A different provider entirely -- must never leak into this provider's summary.
            await recorder.record_request(
                RequestUsageRecord(
                    provider="some-other-provider",
                    endpoint="/x",
                    request_class="P6_background_research",
                    requested_at=datetime(2026, 8, 15, 8, 0, 0, tzinfo=UTC),
                    status="ok",
                    cache_hit=False,
                    estimated_credits=Decimal("9999"),
                )
            )
            await session.commit()

        research_sessionmaker = async_sessionmaker(research_engine, expire_on_commit=False)
        async with research_sessionmaker() as session:
            reporter = UsageReporter(session, now_provider=lambda: FIXED_NOW)

            summary = await reporter.summarize(PROVIDER, monthly_allowance=Decimal("50"))
            assert summary.today_credits == Decimal("13")  # 10 + 3
            assert summary.month_to_date_credits == Decimal("18")  # 10 + 3 + 5

            # 18 credits over 14.5 elapsed days, projected to 30 days.
            expected_projected = (Decimal("18") / Decimal("14.5")) * Decimal(30)
            assert abs(summary.projected_30_day_credits - expected_projected) < Decimal("0.0001")

            expected_pct = (expected_projected / Decimal("50")) * Decimal(100)
            assert summary.projected_pct_of_allowance is not None
            assert abs(summary.projected_pct_of_allowance - expected_pct) < Decimal("0.001")
            assert summary.warning_thresholds_triggered == (70,)
            assert summary.any_warning_triggered is True

            summary_high_allowance = await reporter.summarize(
                PROVIDER, monthly_allowance=Decimal("10000")
            )
            assert summary_high_allowance.warning_thresholds_triggered == ()
            assert summary_high_allowance.any_warning_triggered is False

            summary_no_allowance = await reporter.summarize(PROVIDER, monthly_allowance=None)
            assert summary_no_allowance.projected_pct_of_allowance is None
            assert summary_no_allowance.warning_thresholds_triggered == ()

            other_summary = await reporter.summarize("some-other-provider")
            assert other_summary.today_credits == Decimal("9999")
    finally:
        async with admin_engine.connect() as conn:
            await conn.execute(
                text("DELETE FROM provider_usage WHERE provider IN (:p1, :p2)"),
                {"p1": PROVIDER, "p2": "some-other-provider"},
            )
            await conn.commit()
        await ingest_engine.dispose()
        await research_engine.dispose()

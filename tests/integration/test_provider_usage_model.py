from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from argus.config import load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.provider_usage import ProviderUsage

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("isolated_database")]


async def _engine_for(role: DbRole):
    config = load_config()
    info = connection_for_role(config, role)
    return create_async_engine(info.as_asyncpg_url())


async def test_ingest_role_can_insert_and_research_role_can_read(admin_engine) -> None:
    ingest_engine = await _engine_for(DbRole.INGEST)
    research_engine = await _engine_for(DbRole.RESEARCH)
    try:
        row_id = uuid.uuid4()
        now = datetime.now(UTC)
        ingest_sessionmaker = async_sessionmaker(ingest_engine, expire_on_commit=False)
        async with ingest_sessionmaker() as session:
            session.add(
                ProviderUsage(
                    id=row_id,
                    provider="test_provider",
                    endpoint="/test",
                    request_class="P6_background_research",
                    requested_at=now,
                    status="ok",
                    cache_hit=False,
                    created_at=now,
                )
            )
            await session.commit()

        research_sessionmaker = async_sessionmaker(research_engine, expire_on_commit=False)
        async with research_sessionmaker() as session:
            result = await session.execute(select(ProviderUsage).where(ProviderUsage.id == row_id))
            row = result.scalar_one()
            assert row.provider == "test_provider"

        # research role must not be able to write provider_usage (section 72).
        async with research_sessionmaker() as session:
            session.add(
                ProviderUsage(
                    id=uuid.uuid4(),
                    provider="should_be_denied",
                    endpoint="/test",
                    request_class="P6_background_research",
                    requested_at=now,
                    status="ok",
                    cache_hit=False,
                    created_at=now,
                )
            )
            with pytest.raises(DBAPIError):
                await session.commit()
    finally:
        # cleanup with admin privileges
        from sqlalchemy import text

        async with admin_engine.connect() as conn:
            await conn.execute(
                text(
                    "DELETE FROM provider_usage WHERE provider IN "
                    "('test_provider', 'should_be_denied')"
                )
            )
            await conn.commit()
        await ingest_engine.dispose()
        await research_engine.dispose()

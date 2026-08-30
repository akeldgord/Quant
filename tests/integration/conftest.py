from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from argus.config import load_config
from argus.db.connection import connection_for_admin


@pytest_asyncio.fixture
async def admin_engine() -> AsyncIterator[AsyncEngine]:
    """An async engine using admin credentials, for schema/role assertions.

    Skips the test (rather than failing) if Postgres isn't reachable, so
    `pytest` still runs cleanly on a machine without Docker — the real
    Phase 0 acceptance check (`make up && make test`) always exercises this
    for real.
    """
    config = load_config()
    info = connection_for_admin(config)
    engine = create_async_engine(info.as_asyncpg_url())
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover
        await engine.dispose()
        pytest.skip(f"Postgres not reachable for integration tests: {exc}")
    yield engine
    await engine.dispose()

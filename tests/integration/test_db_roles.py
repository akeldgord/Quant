from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.asyncio


async def test_least_privilege_roles_exist(admin_engine: AsyncEngine) -> None:
    async with admin_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT rolname FROM pg_roles WHERE rolname IN "
                "('argus_ingest', 'argus_research', 'argus_executor') ORDER BY rolname"
            )
        )
        roles = {row[0] for row in result}

    assert roles == {"argus_ingest", "argus_research", "argus_executor"}


async def test_provider_usage_table_exists(admin_engine: AsyncEngine) -> None:
    async with admin_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'provider_usage' ORDER BY column_name"
            )
        )
        columns = {row[0] for row in result}

    expected = {
        "id",
        "provider",
        "endpoint",
        "request_class",
        "requested_at",
        "response_at",
        "latency_ms",
        "status",
        "retry_count",
        "estimated_credits",
        "bytes_received",
        "cache_hit",
        "connection_count",
        "subscription_count",
        "reconnect_count",
        "estimated_streaming_credits",
        "created_at",
    }
    assert expected.issubset(columns)


async def test_ingest_role_can_write_provider_usage_research_cannot(
    admin_engine: AsyncEngine,
) -> None:
    async with admin_engine.connect() as conn:
        ingest_grants = await conn.execute(
            text(
                "SELECT privilege_type FROM information_schema.role_table_grants "
                "WHERE table_name = 'provider_usage' AND grantee = 'argus_ingest'"
            )
        )
        ingest_privs = {row[0] for row in ingest_grants}

        research_grants = await conn.execute(
            text(
                "SELECT privilege_type FROM information_schema.role_table_grants "
                "WHERE table_name = 'provider_usage' AND grantee = 'argus_research'"
            )
        )
        research_privs = {row[0] for row in research_grants}

    assert {"SELECT", "INSERT", "UPDATE"}.issubset(ingest_privs)
    assert research_privs == {"SELECT"}
    assert "INSERT" not in research_privs
    assert "UPDATE" not in research_privs
    assert "DELETE" not in research_privs

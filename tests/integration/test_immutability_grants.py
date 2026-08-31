"""Phase 1 remediation round 2 (argus-phase-1-remediation-002), finding
#6: ``argus_ingest`` previously held ``UPDATE`` on ``chain_events`` and
``commitment_observations`` despite both being stated append-only raw-
evidence tables -- migration 0004 revokes it. These tests prove the
restriction is real and functional (an actual ``UPDATE``/``DELETE``
attempt using the ingest role's own connection fails at the database),
not just a grants-table entry that happens to be absent, plus that the
two new append-only tables (``commitment_observation_rejections``,
``parse_attempts``) never had ``UPDATE``/``DELETE`` granted at all.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from argus.config import load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.chain_events import ChainEvent

pytestmark = pytest.mark.asyncio

_IMMUTABLE_TABLES = (
    "chain_events",
    "commitment_observations",
    "commitment_observation_rejections",
    "parse_attempts",
)


async def _engine_for(role: DbRole):
    config = load_config()
    info = connection_for_role(config, role)
    return create_async_engine(info.as_asyncpg_url())


@pytest.mark.parametrize("table", _IMMUTABLE_TABLES)
async def test_ingest_role_grants_exclude_update_and_delete(admin_engine, table: str) -> None:
    async with admin_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT privilege_type FROM information_schema.role_table_grants "
                "WHERE table_name = :t AND grantee = 'argus_ingest'"
            ),
            {"t": table},
        )
        privileges = {row[0] for row in result}
    assert {"SELECT", "INSERT"}.issubset(privileges)
    assert "UPDATE" not in privileges
    assert "DELETE" not in privileges


async def test_ingest_role_cannot_update_chain_events(admin_engine) -> None:
    """A real ``UPDATE`` attempt against ``chain_events``, using the
    ingest role's own database connection (not the admin/test-setup
    connection) -- the database itself must refuse it, not merely the
    absence of application code that would attempt one."""
    ingest_engine = await _engine_for(DbRole.INGEST)
    now = datetime.now(UTC)
    signature = f"immutability-test-{uuid.uuid4()}"
    try:
        sessionmaker = async_sessionmaker(ingest_engine, expire_on_commit=False)
        async with sessionmaker() as session:
            session.add(
                ChainEvent(
                    event_id=uuid.uuid4(),
                    chain="solana",
                    slot=1,
                    first_seen_at=now,
                    provider="helius",
                    provider_received_at=now,
                    transaction_signature=signature,
                    event_type="TRANSACTION_OBSERVED",
                    wallet_address="WalletImmutable",
                    raw_payload={"x": 1},
                    payload_hash="abc123",
                    parser_version="v1",
                    created_at=now,
                )
            )
            await session.commit()

        async with sessionmaker() as session:
            with pytest.raises(DBAPIError, match="permission denied"):
                await session.execute(
                    text("UPDATE chain_events SET slot = 999 WHERE transaction_signature = :s"),
                    {"s": signature},
                )
                await session.commit()

        async with sessionmaker() as session:
            with pytest.raises(DBAPIError, match="permission denied"):
                await session.execute(
                    text("DELETE FROM chain_events WHERE transaction_signature = :s"),
                    {"s": signature},
                )
                await session.commit()
    finally:
        async with admin_engine.connect() as conn:
            await conn.execute(
                text("DELETE FROM chain_events WHERE transaction_signature = :s"),
                {"s": signature},
            )
            await conn.commit()
        await ingest_engine.dispose()


async def test_ingest_role_can_still_update_wallet_watermarks(admin_engine) -> None:
    """The one deliberate exception: ``wallet_stream_state`` holds mutable
    derived state (the current watermark), and must remain updatable --
    finding #6 only removes ``UPDATE`` from raw-evidence/audit tables,
    never from genuinely mutable state."""
    async with admin_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT privilege_type FROM information_schema.role_table_grants "
                "WHERE table_name = 'wallet_stream_state' AND grantee = 'argus_ingest'"
            )
        )
        privileges = {row[0] for row in result}
    assert {"SELECT", "INSERT", "UPDATE"}.issubset(privileges)

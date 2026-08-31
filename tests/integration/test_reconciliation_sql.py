"""End-to-end integration test: ReconciliationEngine wired to the real
SqlEventRecorder/SqlWatermarkStore against a real Postgres database (not
fakes) -- proves the dedup unique-constraint and watermark persistence
actually work together, not just the abstract in-memory logic covered in
tests/unit/test_reconciliation.py.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from argus.clock import Clock
from argus.config import load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.chain_events import ChainEvent
from argus.ingestion.event_repository import SqlEventRecorder
from argus.ingestion.reconciliation import ReconciliationEngine, ReconciliationTrigger
from argus.ingestion.watermark_repository import SqlWatermarkStore
from argus.providers import SignatureInfo, StreamNotification

pytestmark = pytest.mark.asyncio


class _FakeChainProvider:
    def __init__(self) -> None:
        self._history: list[SignatureInfo] = []
        self._transactions: dict[str, dict[str, Any]] = {}

    def add_transaction(self, signature: str, *, slot: int, raw_payload: dict[str, Any]) -> None:
        self._history.append(
            SignatureInfo(signature=signature, slot=slot, block_time=None, err=None)
        )
        self._transactions[signature] = raw_payload

    async def get_signatures_for_address(
        self, wallet_address: str, *, until_signature: str | None = None, limit: int = 1000
    ) -> list[SignatureInfo]:
        newest_first = list(reversed(self._history))
        if until_signature is None:
            return newest_first[:limit]
        result = []
        for entry in newest_first:
            if entry.signature == until_signature:
                break
            result.append(entry)
        return result[:limit]

    async def get_transaction(self, signature: str) -> dict[str, Any]:
        return self._transactions[signature]

    async def get_balance(self, wallet_address: str) -> int:
        return 0

    async def get_token_accounts(self, wallet_address: str) -> list[dict[str, Any]]:
        return []

    async def get_slot(self) -> int:
        return len(self._history)


async def test_reconciliation_engine_with_real_sql_repositories(admin_engine) -> None:
    config = load_config()
    ingest_info = connection_for_role(config, DbRole.INGEST)
    ingest_engine = create_async_engine(ingest_info.as_asyncpg_url())
    sessionmaker = async_sessionmaker(ingest_engine, expire_on_commit=False)

    wallet = f"sql-recon-{uuid.uuid4()}"
    provider = _FakeChainProvider()
    provider.add_transaction("sql-sig-A", slot=1, raw_payload={"tx": "A"})

    try:
        async with sessionmaker() as session:
            recorder = SqlEventRecorder(session)
            store = SqlWatermarkStore(session)
            engine = ReconciliationEngine(
                chain_provider=provider,
                watermark_store=store,
                event_recorder=recorder,
                clock=Clock(),
                provider_name="fake_provider",
                parser_version="test_v1",
            )

            fast_added = await engine.observe_stream_event(
                StreamNotification(wallet_address=wallet, signature="sql-sig-A", slot=1),
                raw_payload={"tx": "A"},
            )
            assert fast_added is True
            await session.commit()

        provider.add_transaction("sql-sig-B", slot=2, raw_payload={"tx": "B"})

        async with sessionmaker() as session:
            recorder = SqlEventRecorder(session)
            store = SqlWatermarkStore(session)
            engine = ReconciliationEngine(
                chain_provider=provider,
                watermark_store=store,
                event_recorder=recorder,
                clock=Clock(),
                provider_name="fake_provider",
                parser_version="test_v1",
            )
            result = await engine.reconcile(wallet, ReconciliationTrigger.RECONNECT)
            assert result.ok is True
            assert result.new_events == 1  # A already recorded; only B is new
            await session.commit()

        async with sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(ChainEvent).where(ChainEvent.wallet_address == wallet)
                    )
                )
                .scalars()
                .all()
            )
            signatures = sorted(r.transaction_signature for r in rows)
            assert signatures == ["sql-sig-A", "sql-sig-B"]
    finally:
        async with admin_engine.connect() as conn:
            await conn.execute(
                text("DELETE FROM chain_events WHERE wallet_address = :w"), {"w": wallet}
            )
            await conn.execute(
                text("DELETE FROM wallet_stream_state WHERE wallet_address = :w"), {"w": wallet}
            )
            await conn.commit()
        await ingest_engine.dispose()

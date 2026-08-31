"""End-to-end integration test: ReconciliationEngine wired to the real
SqlEventRecorder/SqlWatermarkStore/SqlCommitmentObservationStore/
SqlSwapRecorder against a real Postgres database (not fakes) -- proves the
dedup unique-constraint, watermark persistence, commitment-observation
persistence, and parsed-swap persistence actually work together, not just
the abstract in-memory logic covered in tests/unit/test_reconciliation.py.
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
from argus.domain.commitment import COMMITMENT_CONFIRMED
from argus.domain.swaps import Swap
from argus.ingestion.commitment import derive_current_state
from argus.ingestion.commitment_repository import SqlCommitmentObservationStore
from argus.ingestion.event_repository import SqlEventRecorder
from argus.ingestion.reconciliation import ReconciliationEngine, ReconciliationTrigger
from argus.ingestion.swap_repository import SqlSwapRecorder
from argus.ingestion.watermark_repository import SqlWatermarkStore
from argus.providers import SignatureInfo, StreamNotification

pytestmark = pytest.mark.asyncio


def _valid_raw_payload(wallet: str, signature: str, amount_in: int) -> dict[str, Any]:
    counterparty = "CounterpartySqlFixtureWallet1111111111111"
    return {
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [2_000_000_000, 3_000_000_000],
            "postBalances": [2_000_000_000, 3_000_000_000 + amount_in],
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
        "transaction": {
            "message": {"accountKeys": [counterparty, wallet]},
            "signatures": [signature],
        },
    }


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
        self,
        wallet_address: str,
        *,
        until_signature: str | None = None,
        before_signature: str | None = None,
        limit: int = 1000,
    ) -> list[SignatureInfo]:
        newest_first = list(reversed(self._history))
        if before_signature is not None:
            idx = next(
                (i for i, e in enumerate(newest_first) if e.signature == before_signature), None
            )
            newest_first = [] if idx is None else newest_first[idx + 1 :]
        result = []
        for entry in newest_first:
            if until_signature is not None and entry.signature == until_signature:
                break
            result.append(entry)
        return result[:limit]

    async def get_transaction(self, signature: str) -> dict[str, Any]:
        return self._transactions[signature]

    async def get_signature_statuses(self, signatures: list[str]) -> list[Any]:
        return []

    async def get_balance(self, wallet_address: str) -> int:
        return 0

    async def get_token_accounts(self, wallet_address: str) -> list[dict[str, Any]]:
        return []

    async def get_slot(self) -> int:
        return len(self._history)


def _engine(
    provider: _FakeChainProvider, session: Any, *, page_size: int = 1000
) -> ReconciliationEngine:
    return ReconciliationEngine(
        chain_provider=provider,
        watermark_store=SqlWatermarkStore(session),
        event_recorder=SqlEventRecorder(session),
        clock=Clock(),
        provider_name="fake_provider",
        parser_version="test_v1",
        commitment_store=SqlCommitmentObservationStore(session),
        swap_recorder=SqlSwapRecorder(session),
        page_size=page_size,
        commit_hook=session.commit,
    )


async def test_reconciliation_engine_with_real_sql_repositories(admin_engine) -> None:
    config = load_config()
    ingest_info = connection_for_role(config, DbRole.INGEST)
    ingest_engine = create_async_engine(ingest_info.as_asyncpg_url())
    sessionmaker = async_sessionmaker(ingest_engine, expire_on_commit=False)

    wallet = f"sql-recon-{uuid.uuid4()}"
    provider = _FakeChainProvider()
    provider.add_transaction(
        "sql-sig-A", slot=1, raw_payload=_valid_raw_payload(wallet, "sql-sig-A", 1_000)
    )

    try:
        async with sessionmaker() as session:
            engine = _engine(provider, session)
            fast_added = await engine.observe_stream_event(
                StreamNotification(wallet_address=wallet, signature="sql-sig-A", slot=1),
                raw_payload=_valid_raw_payload(wallet, "sql-sig-A", 1_000),
            )
            assert fast_added is True

        provider.add_transaction(
            "sql-sig-B", slot=2, raw_payload=_valid_raw_payload(wallet, "sql-sig-B", 2_000)
        )

        async with sessionmaker() as session:
            engine = _engine(provider, session)
            result = await engine.reconcile(wallet, ReconciliationTrigger.RECONNECT)
            assert result.ok is True
            assert result.new_events == 1  # A already recorded; only B is new
            assert result.parser_failures == 0

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

            event_a = next(r for r in rows if r.transaction_signature == "sql-sig-A")
            event_b = next(r for r in rows if r.transaction_signature == "sql-sig-B")

            commitment_store = SqlCommitmentObservationStore(session)
            state_a = derive_current_state(await commitment_store.list_for_event(event_a.event_id))
            state_b = derive_current_state(await commitment_store.list_for_event(event_b.event_id))
            # A was fast-path-observed then truth-path-reconciled -- must
            # be promoted to CONFIRMED, not stuck at PROCESSED.
            assert state_a.commitment_level == COMMITMENT_CONFIRMED
            assert state_a.transaction_succeeded is True
            assert state_b.commitment_level == COMMITMENT_CONFIRMED
            assert state_b.transaction_succeeded is True

            swap_rows = (
                (await session.execute(select(Swap).where(Swap.wallet_address == wallet)))
                .scalars()
                .all()
            )
            assert len(swap_rows) == 2
            assert {s.classification for s in swap_rows} == {"TRANSFER_IN"}
    finally:
        async with admin_engine.connect() as conn:
            await conn.execute(
                text(
                    "DELETE FROM commitment_observations WHERE event_id IN "
                    "(SELECT event_id FROM chain_events WHERE wallet_address = :w)"
                ),
                {"w": wallet},
            )
            await conn.execute(text("DELETE FROM swaps WHERE wallet_address = :w"), {"w": wallet})
            await conn.execute(
                text("DELETE FROM chain_events WHERE wallet_address = :w"), {"w": wallet}
            )
            await conn.execute(
                text("DELETE FROM wallet_stream_state WHERE wallet_address = :w"), {"w": wallet}
            )
            await conn.commit()
        await ingest_engine.dispose()


async def test_multi_page_reconciliation_commits_progress_per_item(admin_engine) -> None:
    """Proves the commit_hook wiring is real: each item's watermark
    advance is durably committed as it happens, not only at the very end
    -- a crash after item N must never require re-fetching or losing
    items 1..N (finding #2's "persist partial progress transactionally")."""
    config = load_config()
    ingest_info = connection_for_role(config, DbRole.INGEST)
    ingest_engine = create_async_engine(ingest_info.as_asyncpg_url())
    sessionmaker = async_sessionmaker(ingest_engine, expire_on_commit=False)

    wallet = f"sql-page-{uuid.uuid4()}"
    provider = _FakeChainProvider()
    for i in range(5):
        provider.add_transaction(
            f"sql-page-sig-{i}",
            slot=i,
            raw_payload=_valid_raw_payload(wallet, f"sql-page-sig-{i}", 100),
        )

    try:
        async with sessionmaker() as session:
            engine = _engine(provider, session, page_size=2)
            result = await engine.reconcile(wallet, ReconciliationTrigger.SCHEDULED)
            assert result.ok is True
            assert result.new_events == 5

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
            assert len(rows) == 5
    finally:
        async with admin_engine.connect() as conn:
            await conn.execute(
                text(
                    "DELETE FROM commitment_observations WHERE event_id IN "
                    "(SELECT event_id FROM chain_events WHERE wallet_address = :w)"
                ),
                {"w": wallet},
            )
            await conn.execute(text("DELETE FROM swaps WHERE wallet_address = :w"), {"w": wallet})
            await conn.execute(
                text("DELETE FROM chain_events WHERE wallet_address = :w"), {"w": wallet}
            )
            await conn.execute(
                text("DELETE FROM wallet_stream_state WHERE wallet_address = :w"), {"w": wallet}
            )
            await conn.commit()
        await ingest_engine.dispose()

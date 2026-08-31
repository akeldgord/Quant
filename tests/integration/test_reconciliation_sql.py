"""End-to-end integration test: ReconciliationEngine wired to the real
SqlEventRecorder/SqlWatermarkStore/SqlCommitmentObservationStore/
SqlSwapRecorder/SqlParseAttemptRecorder against a real Postgres database
(not fakes) -- proves the dedup unique-constraint, watermark persistence,
commitment-observation persistence, and parsed-swap persistence actually
work together, not just the abstract in-memory logic covered in
tests/unit/test_reconciliation.py.

Phase 1 remediation round 2 (argus-phase-1-remediation-002), finding #2:
the engine now takes a :class:`~argus.ingestion.unit_of_work.SqlReconciliationUnitOfWork`
(a session factory), not a single bound session -- every call below
constructs the engine once per test against a sessionmaker and lets the
engine open/commit/close its own sessions per atomic operation
internally; tests no longer manage a session lifecycle themselves.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from argus.clock import Clock
from argus.config import load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.chain_events import ChainEvent
from argus.domain.commitment import COMMITMENT_CONFIRMED, COMMITMENT_FINALIZED
from argus.domain.parse_attempts import PARSE_OUTCOME_SUCCESS, ParseAttempt
from argus.domain.swaps import Swap
from argus.ingestion.commitment import derive_current_state
from argus.ingestion.commitment_repository import SqlCommitmentObservationStore
from argus.ingestion.parse_ledger import ParseAttemptIdentity
from argus.ingestion.reconciliation import ReconciliationEngine, ReconciliationTrigger
from argus.ingestion.unit_of_work import SqlReconciliationUnitOfWork
from argus.providers import SignatureInfo, StreamNotification

pytestmark = pytest.mark.asyncio

# Phase 1 remediation round 3, finding #5: ReconciliationEngine now
# requires an explicit ParseAttemptIdentity -- a real, non-empty
# placeholder here since this test exercises the real
# SqlParseAttemptRecorder against a live database whose ``parse_attempts``
# columns are NOT NULL with a length > 0 CHECK constraint.
_TEST_PARSE_IDENTITY = ParseAttemptIdentity(
    build_hash="sql-test-build-hash",
    config_hash="sql-test-config-hash",
    master_spec_hash="sql-test-master-spec-hash",
    git_commit="sql-test-git-commit",
)


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
    provider: _FakeChainProvider,
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    page_size: int = 1000,
) -> ReconciliationEngine:
    return ReconciliationEngine(
        chain_provider=provider,
        unit_of_work=SqlReconciliationUnitOfWork(sessionmaker),
        clock=Clock(),
        provider_name="fake_provider",
        parser_version="test_v1",
        parse_identity=_TEST_PARSE_IDENTITY,
        page_size=page_size,
    )


async def _cleanup(admin_engine: Any, wallet: str) -> None:
    async with admin_engine.connect() as conn:
        await conn.execute(
            text(
                "DELETE FROM parse_attempts WHERE event_id IN "
                "(SELECT event_id FROM chain_events WHERE wallet_address = :w)"
            ),
            {"w": wallet},
        )
        await conn.execute(
            text(
                "DELETE FROM commitment_observation_rejections WHERE event_id IN "
                "(SELECT event_id FROM chain_events WHERE wallet_address = :w)"
            ),
            {"w": wallet},
        )
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
        engine = _engine(provider, sessionmaker)
        fast_added = await engine.observe_stream_event(
            StreamNotification(wallet_address=wallet, signature="sql-sig-A", slot=1),
            raw_payload=_valid_raw_payload(wallet, "sql-sig-A", 1_000),
        )
        assert fast_added is True

        provider.add_transaction(
            "sql-sig-B", slot=2, raw_payload=_valid_raw_payload(wallet, "sql-sig-B", 2_000)
        )

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

            # Finding #9: every parse attempt is durably recorded, in the
            # same transaction as the item's watermark advance. Both A
            # (re-fetched via truth path, already a duplicate chain_event)
            # and B (newly recorded) go through reconcile()'s per-item
            # path, so both get a parse attempt row -- parsing runs
            # unconditionally per fetched item, independent of whether
            # the chain_event insert itself was new or a dedup no-op.
            attempt_rows = (
                (
                    await session.execute(
                        select(ParseAttempt).where(
                            ParseAttempt.event_id.in_([event_a.event_id, event_b.event_id])
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(attempt_rows) == 2
            assert all(row.outcome == PARSE_OUTCOME_SUCCESS for row in attempt_rows)

            # Finding #5: every durable parse attempt also round-trips the
            # exact build/config/MASTER_SPEC/git identity the engine was
            # constructed with -- through a real Postgres write/read, not
            # just the in-memory dataclass.
            assert all(row.build_hash == _TEST_PARSE_IDENTITY.build_hash for row in attempt_rows)
            assert all(row.config_hash == _TEST_PARSE_IDENTITY.config_hash for row in attempt_rows)
            assert all(
                row.master_spec_hash == _TEST_PARSE_IDENTITY.master_spec_hash
                for row in attempt_rows
            )
            assert all(row.git_commit == _TEST_PARSE_IDENTITY.git_commit for row in attempt_rows)
    finally:
        await _cleanup(admin_engine, wallet)
        await ingest_engine.dispose()


async def test_multi_page_reconciliation_commits_progress_per_item(admin_engine) -> None:
    """Proves each item is its own atomic unit of work (finding #2): the
    watermark advance, chain event, commitment observation, and parse
    attempt for item N are all durably committed together as they
    happen, not only at the very end -- a crash after item N must never
    require re-fetching or losing items 1..N ("persist partial progress
    transactionally")."""
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
        engine = _engine(provider, sessionmaker, page_size=2)
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
        await _cleanup(admin_engine, wallet)
        await ingest_engine.dispose()


async def test_concurrent_wallets_use_independent_sessions_no_cross_commit(admin_engine) -> None:
    """Finding #2's core mandatory acceptance criterion: multi-wallet
    concurrency uses no shared AsyncSession and has no cross-commit/
    cross-rollback. Two wallets reconcile concurrently via `asyncio.gather`
    against the SAME engine instance (same unit-of-work factory); one
    wallet's provider is made to fail on its second transaction fetch.
    The failed wallet's already-processed first item must remain
    committed and the healthy wallet's items must be entirely unaffected
    -- proving no session is shared across the two concurrent calls."""
    import asyncio

    config = load_config()
    ingest_info = connection_for_role(config, DbRole.INGEST)
    ingest_engine = create_async_engine(ingest_info.as_asyncpg_url())
    sessionmaker = async_sessionmaker(ingest_engine, expire_on_commit=False)

    wallet_ok = f"sql-concurrent-ok-{uuid.uuid4()}"
    wallet_fail = f"sql-concurrent-fail-{uuid.uuid4()}"

    class _PartiallyFailingProvider(_FakeChainProvider):
        def __init__(self, *, fail_signature: str) -> None:
            super().__init__()
            self._fail_signature = fail_signature

        async def get_transaction(self, signature: str) -> dict[str, Any]:
            if signature == self._fail_signature:
                raise ConnectionError("simulated mid-reconciliation failure")
            return await super().get_transaction(signature)

    provider_ok = _FakeChainProvider()
    for i in range(3):
        provider_ok.add_transaction(
            f"sql-ok-sig-{i}",
            slot=i,
            raw_payload=_valid_raw_payload(wallet_ok, f"sql-ok-sig-{i}", 100),
        )

    provider_fail = _PartiallyFailingProvider(fail_signature="sql-fail-sig-1")
    provider_fail.add_transaction(
        "sql-fail-sig-0", slot=0, raw_payload=_valid_raw_payload(wallet_fail, "sql-fail-sig-0", 100)
    )
    provider_fail.add_transaction(
        "sql-fail-sig-1", slot=1, raw_payload=_valid_raw_payload(wallet_fail, "sql-fail-sig-1", 100)
    )

    engine_ok = _engine(provider_ok, sessionmaker)
    engine_fail = _engine(provider_fail, sessionmaker)

    try:
        result_ok, result_fail = await asyncio.gather(
            engine_ok.reconcile(wallet_ok, ReconciliationTrigger.SCHEDULED),
            engine_fail.reconcile(wallet_fail, ReconciliationTrigger.SCHEDULED),
        )

        assert result_ok.ok is True
        assert result_ok.new_events == 3  # entirely unaffected by the other wallet's failure

        assert result_fail.ok is False
        assert result_fail.new_events == 1  # sql-fail-sig-0 committed before the failure

        async with sessionmaker() as session:
            ok_rows = (
                (
                    await session.execute(
                        select(ChainEvent).where(ChainEvent.wallet_address == wallet_ok)
                    )
                )
                .scalars()
                .all()
            )
            assert len(ok_rows) == 3

            fail_rows = (
                (
                    await session.execute(
                        select(ChainEvent).where(ChainEvent.wallet_address == wallet_fail)
                    )
                )
                .scalars()
                .all()
            )
            assert len(fail_rows) == 1
            assert fail_rows[0].transaction_signature == "sql-fail-sig-0"
    finally:
        await _cleanup(admin_engine, wallet_ok)
        await _cleanup(admin_engine, wallet_fail)
        await ingest_engine.dispose()


async def test_concurrent_commitment_writes_serialize_via_real_advisory_lock(admin_engine) -> None:
    """Finding #5's atomicity mechanism (`pg_advisory_xact_lock`, via
    `SqlCommitmentObservationStore.lock()`) against genuine concurrent
    Postgres sessions/transactions -- not the in-memory asyncio.Lock
    version already covered by
    `tests/unit/test_commitment.py::test_concurrent_conflicting_writes_serialize_and_only_one_is_appended`.
    Two independent sessions each try to append a FINALIZED observation
    for the SAME event with opposite `transaction_succeeded` values,
    concurrently (FINALIZED specifically because reconcile() itself
    never writes at that level -- only up through CONFIRMED -- so
    neither racer starts from a pre-existing same-level observation).
    Exactly one must be APPENDED and the other REJECTED (never two
    conflicting same-level rows, never a corrupted read racing ahead of
    the lock)."""
    import asyncio

    from argus.ingestion.commitment import CommitmentAppendOutcome, CommitmentTracker

    config = load_config()
    ingest_info = connection_for_role(config, DbRole.INGEST)
    ingest_engine = create_async_engine(ingest_info.as_asyncpg_url())
    sessionmaker = async_sessionmaker(ingest_engine, expire_on_commit=False)

    wallet = f"sql-commitment-race-{uuid.uuid4()}"
    provider = _FakeChainProvider()
    provider.add_transaction(
        "sql-commitment-race-sig",
        slot=1,
        raw_payload=_valid_raw_payload(wallet, "sql-commitment-race-sig", 100),
    )

    try:
        engine = _engine(provider, sessionmaker)
        result = await engine.reconcile(wallet, ReconciliationTrigger.SCHEDULED)
        assert result.ok is True
        async with sessionmaker() as session:
            row = (
                await session.execute(select(ChainEvent).where(ChainEvent.wallet_address == wallet))
            ).scalar_one()
            event_id = row.event_id

        now = Clock().utc_now()

        async def _record(*, transaction_succeeded: bool) -> CommitmentAppendOutcome:
            async with sessionmaker() as session, session.begin():
                tracker = CommitmentTracker(SqlCommitmentObservationStore(session))
                result = await tracker.record(
                    event_id=event_id,
                    commitment_level=COMMITMENT_FINALIZED,
                    transaction_succeeded=transaction_succeeded,
                    observed_at=now,
                    provider="sql-race-test",
                    provider_received_at=now,
                    created_at=now,
                )
                return result.outcome

        outcomes = await asyncio.gather(
            _record(transaction_succeeded=True), _record(transaction_succeeded=False)
        )

        assert sorted(o.value for o in outcomes) == sorted(
            [CommitmentAppendOutcome.APPENDED.value, CommitmentAppendOutcome.REJECTED.value]
        )

        async with sessionmaker() as session:
            observations = await SqlCommitmentObservationStore(session).list_for_event(event_id)
            finalized = [o for o in observations if o.commitment_level == COMMITMENT_FINALIZED]
            assert len(finalized) == 1  # never two conflicting same-level rows

            rejection_rows = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM commitment_observation_rejections WHERE event_id = :e"
                    ),
                    {"e": event_id},
                )
            ).scalar_one()
            assert rejection_rows == 1  # the losing write is durably audited, not silently dropped
    finally:
        await _cleanup(admin_engine, wallet)
        await ingest_engine.dispose()

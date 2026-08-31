"""Replay tests (Phase 1 remediation round 1, finding #9: `tests/replay/`
collected zero tests despite the instruction requiring the command to
collect and pass real coverage).

Covers, against a real local Postgres database (not fakes): immutable raw
evidence across replay, deterministic parser output, duplicate-delivery
idempotency, recovery from a persisted restart boundary, deterministic
commitment-progression derivation across repeated queries, and safe
re-parsing under a new parser version without disturbing a prior
point-in-time result.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from argus.clock import Clock
from argus.config import load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.chain_events import ChainEvent
from argus.domain.commitment import COMMITMENT_CONFIRMED, COMMITMENT_FINALIZED, COMMITMENT_PROCESSED
from argus.domain.swaps import Swap
from argus.ingestion.commitment import CommitmentTracker, derive_current_state
from argus.ingestion.commitment_repository import SqlCommitmentObservationStore
from argus.ingestion.event_repository import SqlEventRecorder
from argus.ingestion.reconciliation import (
    ChainEventDraft,
    ReconciliationEngine,
    ReconciliationTrigger,
)
from argus.ingestion.swap_repository import SqlSwapRecorder
from argus.ingestion.unit_of_work import SqlReconciliationUnitOfWork
from argus.parsing.generic_parser import PARSER_VERSION, parse_transaction
from argus.providers import SignatureInfo, StreamNotification

WALLET = "ReplayTestWallet1111111111111111111111111"
COUNTERPARTY = "ReplayCounterpartyWallet22222222222222222"


def _payload_hash(raw_payload: dict[str, Any]) -> str:
    import hashlib
    import json

    canonical = json.dumps(raw_payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _valid_raw_payload(*, signature: str, amount_in: int, wallet: str = WALLET) -> dict[str, Any]:
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
            "message": {"accountKeys": [COUNTERPARTY, wallet]},
            "signatures": [signature],
        },
    }


class _FakeChainProvider:
    """Minimal in-memory provider history, used only to drive
    ReconciliationEngine in the restart-recovery replay test -- the
    persistence layer under test (events/commitments/swaps/watermarks) is
    entirely real SQL."""

    def __init__(self) -> None:
        self._history: list[SignatureInfo] = []
        self._transactions: dict[str, dict[str, Any]] = {}

    def add_transaction(self, signature: str, *, slot: int, raw_payload: dict[str, Any]) -> None:
        self._history.append(
            SignatureInfo(signature=signature, slot=slot, block_time=None, err=None)
        )
        self._transactions[signature] = raw_payload

    async def get_signatures_for_address(
        self, wallet_address: str, *, until_signature=None, before_signature=None, limit=1000
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


async def _cleanup(admin_engine, wallet: str) -> None:
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


async def test_raw_evidence_is_immutable_and_unmutated_across_replay(admin_engine) -> None:
    config = load_config()
    ingest_info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(ingest_info.as_asyncpg_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    wallet = f"{WALLET}-{uuid.uuid4().hex[:8]}"
    raw_payload = _valid_raw_payload(signature="replay-sig-immutable", amount_in=1000)
    now = datetime(2026, 1, 1, tzinfo=UTC)

    try:
        draft = ChainEventDraft(
            event_id=uuid.uuid4(),
            chain="solana",
            slot=1,
            block_time=None,
            first_seen_at=now,
            provider="replay-test",
            provider_received_at=now,
            transaction_signature="replay-sig-immutable",
            event_type="TRANSACTION_OBSERVED",
            wallet_address=wallet,
            mint=None,
            raw_payload=raw_payload,
            payload_hash=_payload_hash(raw_payload),
            parser_version=PARSER_VERSION,
            created_at=now,
        )
        async with sessionmaker() as session:
            recorder = SqlEventRecorder(session)
            outcome = await recorder.record(draft)
            assert outcome.is_new is True
            await session.commit()

        # "Replay" == read the raw evidence back independently, twice, in
        # two fresh sessions -- it must be byte-identical both times, and
        # the hash must still validate against the stored payload.
        for _ in range(2):
            async with sessionmaker() as session:
                row = (
                    await session.execute(
                        select(ChainEvent).where(ChainEvent.event_id == draft.event_id)
                    )
                ).scalar_one()
                assert row.raw_payload == raw_payload
                assert row.payload_hash == _payload_hash(row.raw_payload)
                assert row.payload_hash == draft.payload_hash

        # Replaying (re-recording) the same observation -- a fresh
        # `event_id` (exactly how the real engine always calls `record()`:
        # every draft gets a newly generated id, never a reused one) but
        # the identical natural key (signature, wallet, event_type) --
        # must resolve to the original row, never create a second one.
        replay_draft = dataclasses.replace(draft, event_id=uuid.uuid4())
        async with sessionmaker() as session:
            recorder = SqlEventRecorder(session)
            replay_outcome = await recorder.record(replay_draft)
            assert replay_outcome.is_new is False
            assert (
                replay_outcome.event_id == draft.event_id
            )  # the real, original row -- not a new one

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
            assert len(rows) == 1
    finally:
        await _cleanup(admin_engine, wallet)
        await engine.dispose()


def test_deterministic_parser_output_across_replay() -> None:
    raw_payload = _valid_raw_payload(signature="replay-sig-deterministic", amount_in=2_500_000)
    results = [
        parse_transaction(raw_payload, wallet_address=WALLET, slot=1, block_time=None)
        for _ in range(5)
    ]
    first = results[0]
    for other in results[1:]:
        assert other == first  # every field, including Decimal confidence/amounts, byte-identical
    assert first.classification == "TRANSFER_IN"


async def test_duplicate_delivery_replay_is_idempotent(admin_engine) -> None:
    config = load_config()
    ingest_info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(ingest_info.as_asyncpg_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    wallet = f"{WALLET}-{uuid.uuid4().hex[:8]}"
    raw_payload = _valid_raw_payload(signature="replay-sig-dup", amount_in=500, wallet=wallet)

    try:
        recon_engine = ReconciliationEngine(
            chain_provider=_FakeChainProvider(),
            unit_of_work=SqlReconciliationUnitOfWork(sessionmaker),
            clock=Clock(),
            provider_name="replay-test",
            parser_version=PARSER_VERSION,
        )
        for _ in range(3):  # "replaying" the identical fast-path delivery 3 times
            await recon_engine.observe_stream_event(
                StreamNotification(wallet_address=wallet, signature="replay-sig-dup", slot=1),
                raw_payload=raw_payload,
            )

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
            assert len(rows) == 1
            swap_rows = (
                (await session.execute(select(Swap).where(Swap.wallet_address == wallet)))
                .scalars()
                .all()
            )
            # observe_stream_event (fast path) never parses/persists a swap
            # -- only truth-path reconcile() does (finding #4) -- so
            # replaying fast-path deliveries must leave swaps untouched.
            assert len(swap_rows) == 0
    finally:
        await _cleanup(admin_engine, wallet)
        await engine.dispose()


async def test_process_restart_replay_recovers_missed_events_from_persisted_boundary(
    admin_engine,
) -> None:
    config = load_config()
    ingest_info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(ingest_info.as_asyncpg_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    wallet = f"{WALLET}-{uuid.uuid4().hex[:8]}"

    provider = _FakeChainProvider()
    provider.add_transaction(
        "replay-sig-A",
        slot=1,
        raw_payload=_valid_raw_payload(signature="replay-sig-A", amount_in=100),
    )

    try:
        recon_engine = ReconciliationEngine(
            chain_provider=provider,
            unit_of_work=SqlReconciliationUnitOfWork(sessionmaker),
            clock=Clock(),
            provider_name="replay-test",
            parser_version=PARSER_VERSION,
        )
        result = await recon_engine.reconcile(wallet, ReconciliationTrigger.SCHEDULED)
        assert result.new_events == 1

        # Event B occurs after this "process" has already persisted its
        # watermark and gone away.
        provider.add_transaction(
            "replay-sig-B",
            slot=2,
            raw_payload=_valid_raw_payload(signature="replay-sig-B", amount_in=200),
        )

        # "Restart": a brand-new engine instance (fresh in-process state;
        # a real process restart has none either) replays forward from
        # exactly the persisted watermark boundary -- via the same
        # sessionmaker, since a real database does survive a restart --
        # recovering only what's new: not re-processing A, not missing B.
        restarted_engine = ReconciliationEngine(
            chain_provider=provider,
            unit_of_work=SqlReconciliationUnitOfWork(sessionmaker),
            clock=Clock(),
            provider_name="replay-test",
            parser_version=PARSER_VERSION,
        )
        restart_result = await restarted_engine.reconcile(
            wallet, ReconciliationTrigger.PROCESS_RESTART
        )
        assert restart_result.new_events == 1

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
            assert sorted(r.transaction_signature for r in rows) == ["replay-sig-A", "replay-sig-B"]
    finally:
        await _cleanup(admin_engine, wallet)
        await engine.dispose()


async def test_commitment_progression_replay_is_deterministic_across_repeated_queries(
    admin_engine,
) -> None:
    config = load_config()
    ingest_info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(ingest_info.as_asyncpg_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    wallet = f"{WALLET}-{uuid.uuid4().hex[:8]}"
    now = datetime(2026, 1, 1, tzinfo=UTC)

    try:
        async with sessionmaker() as session:
            draft = ChainEventDraft(
                event_id=uuid.uuid4(),
                chain="solana",
                slot=1,
                block_time=None,
                first_seen_at=now,
                provider="replay-test",
                provider_received_at=now,
                transaction_signature="replay-sig-commitment",
                event_type="TRANSACTION_OBSERVED",
                wallet_address=wallet,
                mint=None,
                raw_payload={"tx": "commitment-progression"},
                payload_hash="deadbeef",
                parser_version=PARSER_VERSION,
                created_at=now,
            )
            outcome = await SqlEventRecorder(session).record(draft)
            tracker = CommitmentTracker(SqlCommitmentObservationStore(session))
            for level, succeeded in (
                (COMMITMENT_PROCESSED, None),
                (COMMITMENT_CONFIRMED, True),
                (COMMITMENT_FINALIZED, True),
            ):
                result = await tracker.record(
                    event_id=outcome.event_id,
                    commitment_level=level,
                    transaction_succeeded=succeeded,
                    observed_at=now,
                    provider="replay-test",
                    provider_received_at=now,
                    created_at=now,
                )
                assert result.accepted is True
            await session.commit()
            event_id = outcome.event_id

        # "Replay" this event's commitment log via independent, freshly
        # constructed stores/sessions several times -- the derived current
        # state must be identical every time, not dependent on in-process
        # cache/object identity.
        derived_states = []
        for _ in range(3):
            async with sessionmaker() as session:
                store = SqlCommitmentObservationStore(session)
                observations = await store.list_for_event(event_id)
                derived_states.append(derive_current_state(observations))

        assert all(s == derived_states[0] for s in derived_states)
        assert derived_states[0].commitment_level == COMMITMENT_FINALIZED
        assert derived_states[0].transaction_succeeded is True
    finally:
        await _cleanup(admin_engine, wallet)
        await engine.dispose()


async def test_reparse_under_new_parser_version_preserves_prior_result(admin_engine) -> None:
    config = load_config()
    ingest_info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(ingest_info.as_asyncpg_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    wallet = f"{WALLET}-{uuid.uuid4().hex[:8]}"
    now = datetime(2026, 1, 1, tzinfo=UTC)
    raw_payload = _valid_raw_payload(signature="replay-sig-reparse", amount_in=750, wallet=wallet)

    try:
        async with sessionmaker() as session:
            draft = ChainEventDraft(
                event_id=uuid.uuid4(),
                chain="solana",
                slot=1,
                block_time=None,
                first_seen_at=now,
                provider="replay-test",
                provider_received_at=now,
                transaction_signature="replay-sig-reparse",
                event_type="TRANSACTION_OBSERVED",
                wallet_address=wallet,
                mint=None,
                raw_payload=raw_payload,
                payload_hash=_payload_hash(raw_payload),
                parser_version=PARSER_VERSION,
                created_at=now,
            )
            outcome = await SqlEventRecorder(session).record(draft)
            event_id = outcome.event_id

            parsed_v1 = parse_transaction(
                raw_payload, wallet_address=wallet, slot=1, block_time=None
            )
            swap_recorder = SqlSwapRecorder(session)
            added_v1 = await swap_recorder.record(
                event_id=event_id, wallet_address=wallet, parsed=parsed_v1, created_at=now
            )
            assert added_v1 is True
            await session.commit()

        # Re-parse the *same* raw evidence under a hypothetical new parser
        # version (never touching or re-fetching the raw payload from a
        # provider -- it's read straight from the immutable chain_events
        # row) and persist that as an *additional*, independent result.
        async with sessionmaker() as session:
            stored_row = (
                await session.execute(select(ChainEvent).where(ChainEvent.event_id == event_id))
            ).scalar_one()
            parsed_v2 = dataclasses.replace(
                parse_transaction(
                    stored_row.raw_payload, wallet_address=wallet, slot=1, block_time=None
                ),
                parser_version="generic_balance_delta_v2",
            )
            swap_recorder = SqlSwapRecorder(session)
            added_v2 = await swap_recorder.record(
                event_id=event_id, wallet_address=wallet, parsed=parsed_v2, created_at=now
            )
            assert added_v2 is True
            await session.commit()

        async with sessionmaker() as session:
            rows = (
                (await session.execute(select(Swap).where(Swap.event_id == event_id)))
                .scalars()
                .all()
            )
            versions = {r.parser_version for r in rows}
            assert versions == {PARSER_VERSION, "generic_balance_delta_v2"}
            assert len(rows) == 2  # the v1 result was never overwritten or removed

            # Re-running the *same* version again is still idempotent even
            # after the v2 addition -- no interference between versions.
            async with sessionmaker() as inner_session:
                repeat_recorder = SqlSwapRecorder(inner_session)
                repeat_added = await repeat_recorder.record(
                    event_id=event_id, wallet_address=wallet, parsed=parsed_v1, created_at=now
                )
                assert repeat_added is False
    finally:
        await _cleanup(admin_engine, wallet)
        await engine.dispose()

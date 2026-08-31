"""Tests for argus.ingestion.reconciliation, including the mandatory
deterministic disconnect/reconnect scenario from MASTER_SPEC.md section 19:

    stream connects -> event A observed -> disconnect -> event B occurs
    while disconnected -> reconnect -> reconciliation discovers B

with the final canonical ledger containing A exactly once and B exactly
once -- repeated here across process restart and duplicate-delivery
variants, using fakes for the chain provider, event ledger, and watermark
store (no real network or database required; the ledger/watermark fakes
are deliberately structured so a "process restart" test has to reload from
a plain snapshot, not from in-process object identity).

Phase 1 remediation round 1 (argus-phase-1-remediation-001) adds: full
pagination beyond one page (finding #2), commitment-observation
persistence (finding #3), and parser-to-persistence wiring (finding #4).
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime
from typing import Any

import pytest

from argus.clock import Clock
from argus.domain.commitment import COMMITMENT_CONFIRMED, COMMITMENT_FINALIZED, COMMITMENT_PROCESSED
from argus.ingestion.commitment import CommitmentObservationDraft, derive_current_state
from argus.ingestion.reconciliation import (
    ChainEventDraft,
    ReconciliationEngine,
    ReconciliationTrigger,
    RecordOutcome,
    WalletWatermark,
)
from argus.parsing.generic_parser import ParsedTransaction
from argus.providers import SignatureInfo, SignatureStatusInfo, StreamNotification

WALLET = "TestWallet1111111111111111111111111111111"
COUNTERPARTY = "CounterpartyWallet22222222222222222222222"


def _valid_raw_payload(
    *, wallet: str = WALLET, signature: str = "sig-valid", amount_in: int = 1_000_000_000
) -> dict[str, Any]:
    """A structurally well-formed Solana ``getTransaction`` shape (a plain
    SOL transfer-in) -- real enough for `generic_parser.parse_transaction`
    to succeed, unlike the minimal `{"tx": "A"}` placeholders used
    elsewhere in this file for tests that don't care about parsing."""
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


class FakeChainProvider:
    """In-memory chain history: signatures are appended in causal (oldest
    first) order; `get_signatures_for_address` returns newest-first,
    honoring `before_signature` (cursor, exclusive) and `until_signature`
    (fixed boundary, exclusive) exactly like real Solana pagination."""

    def __init__(self) -> None:
        self._history: list[SignatureInfo] = []
        self._transactions: dict[str, dict[str, Any]] = {}
        self.raise_on_list: Exception | None = None
        self.raise_on_fetch: dict[str, Exception] = {}
        self.signature_statuses: dict[str, SignatureStatusInfo] = {}
        self.list_calls: list[tuple[str | None, str | None, int]] = []

    def add_transaction(
        self,
        signature: str,
        *,
        slot: int,
        raw_payload: dict[str, Any],
        block_time: datetime | None = None,
        err: Any | None = None,
    ) -> None:
        self._history.append(
            SignatureInfo(signature=signature, slot=slot, block_time=block_time, err=err)
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
        self.list_calls.append((until_signature, before_signature, limit))
        if self.raise_on_list is not None:
            raise self.raise_on_list
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
        if signature in self.raise_on_fetch:
            raise self.raise_on_fetch[signature]
        return self._transactions[signature]

    async def get_signature_statuses(self, signatures: list[str]) -> list[SignatureStatusInfo]:
        return [
            self.signature_statuses.get(
                sig,
                SignatureStatusInfo(signature=sig, confirmation_status=None, err=None, slot=None),
            )
            for sig in signatures
        ]

    async def get_balance(self, wallet_address: str) -> int:
        return 0

    async def get_token_accounts(self, wallet_address: str) -> list[dict[str, Any]]:
        return []

    async def get_slot(self) -> int:
        return len(self._history)


class FakeEventLedger:
    """Simulates the DB unique-constraint dedup: keyed on
    (signature, wallet, event_type). Persists independently of the engine
    so it can stand in for "the database survived a process restart"."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str | None, str], ChainEventDraft] = {}

    async def record(self, draft: ChainEventDraft) -> RecordOutcome:
        key = (draft.transaction_signature, draft.wallet_address, draft.event_type)
        existing = self.rows.get(key)
        if existing is not None:
            return RecordOutcome(event_id=existing.event_id, is_new=False)
        self.rows[key] = draft
        return RecordOutcome(event_id=draft.event_id, is_new=True)


class FakeWatermarkStore:
    """A real implementation backs onto `wallet_stream_state`; this fake
    is constructible from a plain snapshot dict to simulate reloading
    persisted state after a process restart (never sharing Python object
    identity with a "previous process")."""

    def __init__(self, snapshot: dict[str, WalletWatermark] | None = None) -> None:
        self._rows: dict[str, WalletWatermark] = dict(snapshot or {})

    async def get(self, wallet_address: str) -> WalletWatermark | None:
        return self._rows.get(wallet_address)

    async def save(self, watermark: WalletWatermark) -> None:
        self._rows[watermark.wallet_address] = watermark

    def snapshot(self) -> dict[str, WalletWatermark]:
        return dict(self._rows)


class FakeCommitmentStore:
    def __init__(self, snapshot: list[CommitmentObservationDraft] | None = None) -> None:
        self.rows: list[CommitmentObservationDraft] = list(snapshot or [])

    async def list_for_event(self, event_id: uuid.UUID) -> list[CommitmentObservationDraft]:
        return [r for r in self.rows if r.event_id == event_id]

    async def append(self, observation: CommitmentObservationDraft) -> None:
        self.rows.append(observation)

    def snapshot(self) -> list[CommitmentObservationDraft]:
        return list(self.rows)


class FakeSwapRecorder:
    def __init__(self) -> None:
        self.rows: dict[tuple[uuid.UUID, str], ParsedTransaction] = {}

    async def record(
        self,
        *,
        event_id: uuid.UUID,
        wallet_address: str,
        parsed: ParsedTransaction,
        created_at: datetime,
    ) -> bool:
        key = (event_id, parsed.parser_version)
        if key in self.rows:
            return False
        self.rows[key] = parsed
        return True


class FakeRecentEventSource:
    def __init__(self, pairs: list[tuple[uuid.UUID, str]] | None = None) -> None:
        self.pairs = pairs or []

    async def recent_signatures(
        self, wallet_address: str, *, limit: int
    ) -> list[tuple[uuid.UUID, str]]:
        return self.pairs[:limit]


def _engine(
    provider: FakeChainProvider,
    ledger: FakeEventLedger,
    store: FakeWatermarkStore,
    *,
    commitment_store: FakeCommitmentStore | None = None,
    swap_recorder: FakeSwapRecorder | None = None,
    clock_monitor: Any | None = None,
    recent_event_source: Any | None = None,
    page_size: int = 1000,
    max_pages: int = 50,
) -> ReconciliationEngine:
    return ReconciliationEngine(
        chain_provider=provider,
        watermark_store=store,
        event_recorder=ledger,
        clock=Clock(),
        provider_name="fake_provider",
        parser_version="test_v1",
        commitment_store=commitment_store or FakeCommitmentStore(),
        swap_recorder=swap_recorder or FakeSwapRecorder(),
        clock_monitor=clock_monitor,
        recent_event_source=recent_event_source,
        page_size=page_size,
        max_pages=max_pages,
    )


@pytest.mark.asyncio
async def test_mandatory_disconnect_reconnect_scenario_canonicalizes_a_and_b_exactly_once() -> None:
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    engine = _engine(provider, ledger, store)

    # 1. stream connects, 2. event A is observed (fast path).
    provider.add_transaction("sig-A", slot=1, raw_payload={"tx": "A"})
    added_a_fast = await engine.observe_stream_event(
        StreamNotification(wallet_address=WALLET, signature="sig-A", slot=1),
        raw_payload={"tx": "A"},
    )
    assert added_a_fast is True

    # 3. disconnect occurs (no explicit action needed -- we just stop
    #    calling observe_stream_event for the wallet).
    # 4. event B occurs while disconnected: it reaches the provider's real
    #    history but is never seen by the fast path.
    provider.add_transaction("sig-B", slot=2, raw_payload={"tx": "B"})

    # 5. reconnect occurs, 6. reconciliation discovers B (and re-observes A
    #    via the truth path too -- must dedup to the same single row).
    result = await engine.reconcile(WALLET, ReconciliationTrigger.RECONNECT)

    assert result.ok is True
    assert result.new_events == 1  # only B is new; A was already recorded by the fast path

    a_rows = [d for (sig, w, _), d in ledger.rows.items() if sig == "sig-A" and w == WALLET]
    b_rows = [d for (sig, w, _), d in ledger.rows.items() if sig == "sig-B" and w == WALLET]
    assert len(a_rows) == 1
    assert len(b_rows) == 1

    watermark = await store.get(WALLET)
    assert watermark is not None
    assert watermark.last_reconciled_signature == "sig-B"
    assert watermark.wallet_live_state == "OK"
    assert watermark.stream_health == "OK"


@pytest.mark.asyncio
async def test_scenario_survives_process_restart() -> None:
    """Same scenario, but reconciliation happens in a freshly-constructed
    engine/watermark-store pair (simulating a process restart) that only
    knows what was persisted -- the ledger fake stands in for "the
    database", which does survive a restart."""
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    engine = _engine(provider, ledger, store)

    provider.add_transaction("sig-A", slot=1, raw_payload={"tx": "A"})
    await engine.observe_stream_event(
        StreamNotification(wallet_address=WALLET, signature="sig-A", slot=1),
        raw_payload={"tx": "A"},
    )
    provider.add_transaction("sig-B", slot=2, raw_payload={"tx": "B"})

    # "Process restart": brand-new engine + watermark store reloaded from
    # a persisted snapshot; the same ledger fake (standing in for the DB)
    # is reused since a real database does survive a restart.
    restarted_store = FakeWatermarkStore(snapshot=store.snapshot())
    restarted_engine = _engine(provider, ledger, restarted_store)

    result = await restarted_engine.reconcile(WALLET, ReconciliationTrigger.PROCESS_RESTART)

    assert result.ok is True
    assert result.new_events == 1  # B, discovered fresh after "restart"

    a_rows = [d for (sig, w, _), d in ledger.rows.items() if sig == "sig-A" and w == WALLET]
    b_rows = [d for (sig, w, _), d in ledger.rows.items() if sig == "sig-B" and w == WALLET]
    assert len(a_rows) == 1
    assert len(b_rows) == 1

    # A second reconciliation after "restart" (e.g. a scheduled tick) must
    # find nothing new -- the persisted watermark prevents replay.
    result2 = await restarted_engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)
    assert result2.new_events == 0


@pytest.mark.asyncio
async def test_duplicate_stream_delivery_is_idempotent() -> None:
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    engine = _engine(provider, ledger, store)

    provider.add_transaction("sig-A", slot=1, raw_payload={"tx": "A"})
    notification = StreamNotification(wallet_address=WALLET, signature="sig-A", slot=1)

    first = await engine.observe_stream_event(notification, raw_payload={"tx": "A"})
    second = await engine.observe_stream_event(
        notification, raw_payload={"tx": "A"}
    )  # duplicate delivery

    assert first is True
    assert second is False
    a_rows = [d for (sig, w, _), d in ledger.rows.items() if sig == "sig-A" and w == WALLET]
    assert len(a_rows) == 1

    # A subsequent reconciliation must also not double-count the duplicate.
    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)
    assert result.new_events == 0
    a_rows_after = [d for (sig, w, _), d in ledger.rows.items() if sig == "sig-A" and w == WALLET]
    assert len(a_rows_after) == 1


@pytest.mark.asyncio
async def test_duplicate_truth_path_delivery_across_two_reconciliations_is_idempotent() -> None:
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    engine = _engine(provider, ledger, store)

    provider.add_transaction("sig-A", slot=1, raw_payload={"tx": "A"})
    result1 = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)
    assert result1.new_events == 1

    # A second reconciliation before any new activity must not re-count A
    # (the watermark already advanced past it).
    result2 = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)
    assert result2.new_events == 0
    a_rows = [d for (sig, w, _), d in ledger.rows.items() if sig == "sig-A" and w == WALLET]
    assert len(a_rows) == 1


@pytest.mark.asyncio
async def test_unresolved_reconciliation_marks_wallet_degraded() -> None:
    provider = FakeChainProvider()
    provider.raise_on_list = ConnectionError("provider unreachable")
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    engine = _engine(provider, ledger, store)

    result = await engine.reconcile(WALLET, ReconciliationTrigger.TIMEOUT)

    assert result.ok is False
    assert "ConnectionError" in result.reason
    watermark = await store.get(WALLET)
    assert watermark is not None
    assert watermark.wallet_live_state == "DEGRADED"
    assert watermark.stream_health == "DEGRADED"
    assert watermark.is_live_entry_eligible() is False


@pytest.mark.asyncio
async def test_transaction_fetch_failure_mid_reconciliation_marks_degraded_but_keeps_progress() -> (
    None
):
    provider = FakeChainProvider()
    provider.add_transaction("sig-A", slot=1, raw_payload={"tx": "A"})
    provider.add_transaction("sig-B", slot=2, raw_payload={"tx": "B"})
    provider.raise_on_fetch["sig-B"] = TimeoutError("fetch timed out")
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    engine = _engine(provider, ledger, store)

    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)

    assert result.ok is False
    assert result.new_events == 1  # A succeeded before B's fetch failed
    watermark = await store.get(WALLET)
    assert watermark is not None
    assert watermark.wallet_live_state == "DEGRADED"
    assert watermark.last_reconciled_signature == "sig-A"  # progress up to the failure is preserved

    # Restart/retry: a fresh reconcile() call resumes at exactly the safe
    # boundary rather than re-fetching A or permanently losing B.
    del provider.raise_on_fetch["sig-B"]
    result2 = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)
    assert result2.ok is True
    assert result2.new_events == 1  # only B, this time
    watermark2 = await store.get(WALLET)
    assert watermark2 is not None
    assert watermark2.last_reconciled_signature == "sig-B"


@pytest.mark.asyncio
async def test_degraded_wallet_is_never_live_entry_eligible() -> None:
    degraded = WalletWatermark(wallet_address=WALLET, wallet_live_state="DEGRADED")
    ok = WalletWatermark(wallet_address=WALLET, wallet_live_state="OK")
    assert degraded.is_live_entry_eligible() is False
    assert ok.is_live_entry_eligible() is True


def test_watermark_is_immutable_dataclass() -> None:
    wm = WalletWatermark(wallet_address=WALLET)
    with pytest.raises(dataclasses.FrozenInstanceError):
        wm.wallet_live_state = "DEGRADED"  # type: ignore[misc]


class _FakeClockMonitor:
    """Minimal duck-typed stand-in: ReconciliationEngine only reads
    ``.anomaly_detected``, so a real PersistentClockMonitor is unnecessary
    to exercise the gating logic in isolation."""

    def __init__(self, *, anomaly_detected: bool) -> None:
        self.anomaly_detected = anomaly_detected


@pytest.mark.asyncio
async def test_unresolved_clock_anomaly_forces_degraded_even_on_successful_reconciliation() -> None:
    """Section 17: provider reconnection + chain reconciliation + clock
    health recovery are three independent conditions -- an outstanding
    clock anomaly must keep the wallet DEGRADED even though this
    reconciliation itself succeeded cleanly."""
    provider = FakeChainProvider()
    provider.add_transaction("sig-A", slot=1, raw_payload={"tx": "A"})
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    engine = _engine(
        provider, ledger, store, clock_monitor=_FakeClockMonitor(anomaly_detected=True)
    )

    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)

    assert result.ok is True  # reconciliation mechanically succeeded
    assert result.new_events == 1
    assert "clock anomaly" in result.reason
    watermark = await store.get(WALLET)
    assert watermark is not None
    assert watermark.wallet_live_state == "DEGRADED"
    assert watermark.is_live_entry_eligible() is False


@pytest.mark.asyncio
async def test_healthy_clock_allows_normal_ok_resolution() -> None:
    provider = FakeChainProvider()
    provider.add_transaction("sig-A", slot=1, raw_payload={"tx": "A"})
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    engine = _engine(
        provider, ledger, store, clock_monitor=_FakeClockMonitor(anomaly_detected=False)
    )

    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)

    assert result.ok is True
    assert result.reason == ""
    watermark = await store.get(WALLET)
    assert watermark is not None
    assert watermark.wallet_live_state == "OK"
    assert watermark.is_live_entry_eligible() is True


# --- Finding #2: pagination -------------------------------------------


@pytest.mark.asyncio
async def test_gap_larger_than_one_page_is_fully_paginated_with_no_loss() -> None:
    provider = FakeChainProvider()
    for i in range(5):
        provider.add_transaction(f"sig-{i}", slot=i, raw_payload={"tx": str(i)})
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    engine = _engine(provider, ledger, store, page_size=2)  # forces 3 pages for 5 events

    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)

    assert result.ok is True
    assert result.new_events == 5
    assert len(provider.list_calls) == 3  # 2 + 2 + 1
    watermark = await store.get(WALLET)
    assert watermark is not None
    assert watermark.last_reconciled_signature == "sig-4"
    for i in range(5):
        assert (f"sig-{i}", WALLET, "TRANSACTION_OBSERVED") in ledger.rows


@pytest.mark.asyncio
async def test_boundary_present_pagination_respects_until_across_pages() -> None:
    """Two reconcile() calls, each fully paginated: the second must only
    pick up the new gap after the first call's watermark boundary, not
    re-walk everything from the start."""
    provider = FakeChainProvider()
    for i in range(5):
        provider.add_transaction(f"sig-{i}", slot=i, raw_payload={"tx": str(i)})
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    engine = _engine(provider, ledger, store, page_size=2)

    result1 = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)
    assert result1.new_events == 5

    provider.add_transaction("sig-5", slot=5, raw_payload={"tx": "5"})
    provider.add_transaction("sig-6", slot=6, raw_payload={"tx": "6"})

    result2 = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)
    assert result2.new_events == 2  # only the boundary-respecting new gap
    watermark = await store.get(WALLET)
    assert watermark is not None
    assert watermark.last_reconciled_signature == "sig-6"


@pytest.mark.asyncio
async def test_empty_page_stops_pagination_cleanly() -> None:
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    engine = _engine(provider, ledger, store, page_size=10)

    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)
    assert result.ok is True
    assert result.new_events == 0


@pytest.mark.asyncio
async def test_non_progressing_cursor_fails_degraded_without_losing_prior_pages() -> None:
    class _StuckProvider(FakeChainProvider):
        async def get_signatures_for_address(
            self, wallet_address, *, until_signature=None, before_signature=None, limit=1000
        ):
            # Always returns the same single (non-empty, non-shrinking)
            # page regardless of the cursor -- a buggy/malformed provider
            # that never actually advances.
            return [SignatureInfo(signature="sig-stuck", slot=1, block_time=None, err=None)]

    provider = _StuckProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    engine = _engine(provider, ledger, store, page_size=1)

    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)

    assert result.ok is False
    assert "non-progressing" in result.reason
    assert result.new_events == 0  # nothing was ever processed/persisted
    watermark = await store.get(WALLET)
    assert watermark is not None
    assert watermark.wallet_live_state == "DEGRADED"
    assert len(ledger.rows) == 0


@pytest.mark.asyncio
async def test_safety_ceiling_exceeded_fails_degraded() -> None:
    provider = FakeChainProvider()
    for i in range(10):
        provider.add_transaction(f"sig-{i}", slot=i, raw_payload={"tx": str(i)})
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    engine = _engine(provider, ledger, store, page_size=2, max_pages=2)  # only 4 of 10 fit

    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)

    assert result.ok is False
    assert "safety ceiling" in result.reason
    assert result.new_events == 0  # listing-phase failure; nothing processed yet
    watermark = await store.get(WALLET)
    assert watermark is not None
    assert watermark.wallet_live_state == "DEGRADED"


def test_page_size_and_max_pages_must_be_positive() -> None:
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    with pytest.raises(ValueError, match="page_size"):
        _engine(provider, ledger, store, page_size=0)
    with pytest.raises(ValueError, match="max_pages"):
        _engine(provider, ledger, store, max_pages=0)


# --- Finding #3: commitment progression --------------------------------


@pytest.mark.asyncio
async def test_fast_path_first_seen_time_survives_confirmed_progression() -> None:
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    commitment_store = FakeCommitmentStore()
    engine = _engine(provider, ledger, store, commitment_store=commitment_store)

    provider.add_transaction("sig-A", slot=1, raw_payload={"tx": "A"})
    await engine.observe_stream_event(
        StreamNotification(wallet_address=WALLET, signature="sig-A", slot=1),
        raw_payload={"tx": "A"},
    )
    event_id = ledger.rows[("sig-A", WALLET, "TRANSACTION_OBSERVED")].event_id
    first_seen_state = derive_current_state(await commitment_store.list_for_event(event_id))
    assert first_seen_state.commitment_level == COMMITMENT_PROCESSED

    await engine.reconcile(WALLET, ReconciliationTrigger.RECONNECT)

    observations = await commitment_store.list_for_event(event_id)
    levels = {o.commitment_level for o in observations}
    assert levels == {
        COMMITMENT_PROCESSED,
        COMMITMENT_CONFIRMED,
    }  # PROCESSED preserved, not overwritten
    current = derive_current_state(observations)
    assert current.commitment_level == COMMITMENT_CONFIRMED
    assert current.transaction_succeeded is True


@pytest.mark.asyncio
async def test_failed_onchain_transaction_is_confirmed_but_execution_failed() -> None:
    """sig_info.err is transaction execution success, not commitment
    status -- a failed transaction must still be recorded as CONFIRMED,
    just with transaction_succeeded=False (finding #3)."""
    provider = FakeChainProvider()
    provider.add_transaction(
        "sig-fail", slot=1, raw_payload={"tx": "fail"}, err={"InstructionError": [0, "Custom"]}
    )
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    commitment_store = FakeCommitmentStore()
    engine = _engine(provider, ledger, store, commitment_store=commitment_store)

    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)
    assert result.new_events == 1

    event_id = ledger.rows[("sig-fail", WALLET, "TRANSACTION_OBSERVED")].event_id
    state = derive_current_state(await commitment_store.list_for_event(event_id))
    assert state.commitment_level == COMMITMENT_CONFIRMED
    assert state.transaction_succeeded is False


@pytest.mark.asyncio
async def test_sweep_finalization_promotes_confirmed_events() -> None:
    provider = FakeChainProvider()
    provider.add_transaction("sig-A", slot=1, raw_payload={"tx": "A"})
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    commitment_store = FakeCommitmentStore()
    engine_no_source = _engine(provider, ledger, store, commitment_store=commitment_store)
    await engine_no_source.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)
    event_id = ledger.rows[("sig-A", WALLET, "TRANSACTION_OBSERVED")].event_id

    # Without a RecentEventSource, sweep_finalization is a safe no-op.
    promoted_none = await engine_no_source.sweep_finalization(WALLET)
    assert promoted_none == 0

    provider.signature_statuses["sig-A"] = SignatureStatusInfo(
        signature="sig-A", confirmation_status="finalized", err=None, slot=1
    )
    engine_with_source = _engine(
        provider,
        ledger,
        store,
        commitment_store=commitment_store,
        recent_event_source=FakeRecentEventSource([(event_id, "sig-A")]),
    )
    promoted = await engine_with_source.sweep_finalization(WALLET)
    assert promoted == 1
    state = derive_current_state(await commitment_store.list_for_event(event_id))
    assert state.commitment_level == COMMITMENT_FINALIZED


@pytest.mark.asyncio
async def test_commitment_regression_and_conflict_are_rejected_and_audited() -> None:
    provider = FakeChainProvider()
    provider.add_transaction("sig-A", slot=1, raw_payload={"tx": "A"})
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    commitment_store = FakeCommitmentStore()
    engine = _engine(provider, ledger, store, commitment_store=commitment_store)
    await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)
    event_id = ledger.rows[("sig-A", WALLET, "TRANSACTION_OBSERVED")].event_id

    from argus.ingestion.commitment import CommitmentTracker

    tracker = CommitmentTracker(commitment_store)
    now = Clock().utc_now()

    regression = await tracker.record(
        event_id=event_id,
        commitment_level=COMMITMENT_PROCESSED,
        transaction_succeeded=None,
        observed_at=now,
        provider="test",
        provider_received_at=now,
        created_at=now,
    )
    assert regression.accepted is False
    assert "regression" in regression.reason

    conflict = await tracker.record(
        event_id=event_id,
        commitment_level=COMMITMENT_CONFIRMED,
        transaction_succeeded=False,  # existing was True
        observed_at=now,
        provider="test",
        provider_received_at=now,
        created_at=now,
    )
    assert conflict.accepted is False
    assert "conflicting" in conflict.reason

    # Neither rejected write altered the durable state.
    state = derive_current_state(await commitment_store.list_for_event(event_id))
    assert state.commitment_level == COMMITMENT_CONFIRMED
    assert state.transaction_succeeded is True


# --- Finding #4: parser wired to persistence ---------------------------


@pytest.mark.asyncio
async def test_reconciliation_persists_versioned_parser_output() -> None:
    provider = FakeChainProvider()
    provider.add_transaction("sig-valid", slot=1, raw_payload=_valid_raw_payload())
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    swap_recorder = FakeSwapRecorder()
    engine = _engine(provider, ledger, store, swap_recorder=swap_recorder)

    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)

    assert result.ok is True
    assert result.new_events == 1
    assert result.parser_failures == 0
    event_id = ledger.rows[("sig-valid", WALLET, "TRANSACTION_OBSERVED")].event_id
    assert (event_id, "generic_balance_delta_v1") in swap_recorder.rows
    parsed = swap_recorder.rows[(event_id, "generic_balance_delta_v1")]
    assert parsed.classification == "TRANSFER_IN"


@pytest.mark.asyncio
async def test_malformed_raw_payload_records_parser_failure_without_losing_raw_evidence() -> None:
    provider = FakeChainProvider()
    provider.add_transaction("sig-broken", slot=1, raw_payload={"not": "a real transaction"})
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    swap_recorder = FakeSwapRecorder()
    engine = _engine(provider, ledger, store, swap_recorder=swap_recorder)

    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)

    assert result.ok is True
    assert result.new_events == 1  # raw evidence still recorded
    assert result.parser_failures == 1
    assert len(swap_recorder.rows) == 0
    assert ("sig-broken", WALLET, "TRANSACTION_OBSERVED") in ledger.rows


@pytest.mark.asyncio
async def test_reparse_under_same_parser_version_is_idempotent() -> None:
    provider = FakeChainProvider()
    provider.add_transaction("sig-valid", slot=1, raw_payload=_valid_raw_payload())
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    swap_recorder = FakeSwapRecorder()
    engine = _engine(provider, ledger, store, swap_recorder=swap_recorder)
    await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)
    assert len(swap_recorder.rows) == 1

    event_id = ledger.rows[("sig-valid", WALLET, "TRANSACTION_OBSERVED")].event_id
    parsed_again = list(swap_recorder.rows.values())[0]
    added_again = await swap_recorder.record(
        event_id=event_id, wallet_address=WALLET, parsed=parsed_again, created_at=Clock().utc_now()
    )
    assert added_again is False  # same (event_id, parser_version) -- no duplicate
    assert len(swap_recorder.rows) == 1

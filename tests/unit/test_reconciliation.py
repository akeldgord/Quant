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

import asyncio
import contextlib
import dataclasses
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import pytest

from argus.clock import Clock
from argus.domain.commitment import COMMITMENT_CONFIRMED, COMMITMENT_FINALIZED, COMMITMENT_PROCESSED
from argus.ingestion.commitment import (
    InMemoryCommitmentObservationStore,
    derive_current_state,
)
from argus.ingestion.parse_ledger import InMemoryParseAttemptRecorder, ParseAttemptIdentity
from argus.ingestion.reconciliation import (
    ChainEventDraft,
    ReconciliationEngine,
    ReconciliationRepos,
    ReconciliationTrigger,
    RecordOutcome,
    WalletWatermark,
)
from argus.parsing.generic_parser import ParsedTransaction
from argus.providers import SignatureInfo, SignatureStatusInfo, StreamNotification

# Phase 1 remediation round 2 (finding #5): the shared reference fake --
# same lock()/append_rejection()/sequence-stamping contract the real SQL
# store has. Kept under this name since tests/unit/test_ingestion_manager.py
# imports it from here.
FakeCommitmentStore = InMemoryCommitmentObservationStore

WALLET = "TestWallet1111111111111111111111111111111"
COUNTERPARTY = "CounterpartyWallet22222222222222222222222"

# Phase 1 remediation round 3, finding #5: every ReconciliationEngine now
# requires an explicit ParseAttemptIdentity (no default -- see its
# docstring), so every test constructing one needs a real, non-empty
# placeholder identity. Shared here since tests/unit/test_ingestion_manager.py
# and others import fakes/constants from this module already.
TEST_PARSE_IDENTITY = ParseAttemptIdentity(
    build_hash="test-build-hash",
    config_hash="test-config-hash",
    master_spec_hash="test-master-spec-hash",
    git_commit="test-git-commit",
)


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
        self.raise_on_statuses: BaseException | None = None
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
        if self.raise_on_statuses is not None:
            raise self.raise_on_statuses
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


class FakeSwapRecorder:
    def __init__(self) -> None:
        self.rows: dict[tuple[uuid.UUID, str, str], ParsedTransaction] = {}

    async def record(
        self,
        *,
        event_id: uuid.UUID,
        wallet_address: str,
        parsed: ParsedTransaction,
        build_hash: str,
        created_at: datetime,
    ) -> bool:
        key = (event_id, parsed.parser_version, build_hash)
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


class _FakeUnitOfWork:
    """Phase 1 remediation round 2, finding #2: the real engine now takes
    a unit-of-work factory, not individually bound repos. For these
    in-memory fakes -- which have no real transaction/session to scope
    per operation -- every call yields the same fixed bundle; the fakes
    themselves are what a test inspects afterward, exactly as before."""

    def __init__(self, repos: ReconciliationRepos) -> None:
        self._repos = repos

    @contextlib.asynccontextmanager
    async def __call__(self) -> AsyncIterator[ReconciliationRepos]:
        yield self._repos


def _engine(
    provider: FakeChainProvider,
    ledger: FakeEventLedger,
    store: FakeWatermarkStore,
    *,
    commitment_store: FakeCommitmentStore | None = None,
    swap_recorder: FakeSwapRecorder | None = None,
    parse_attempt_recorder: InMemoryParseAttemptRecorder | None = None,
    clock_monitor: Any | None = None,
    recent_event_source: Any | None = None,
    page_size: int = 1000,
    max_pages: int = 50,
) -> ReconciliationEngine:
    repos = ReconciliationRepos(
        watermark_store=store,
        event_recorder=ledger,
        commitment_store=commitment_store or FakeCommitmentStore(),
        swap_recorder=swap_recorder or FakeSwapRecorder(),
        parse_attempt_recorder=parse_attempt_recorder or InMemoryParseAttemptRecorder(),
        recent_event_source=recent_event_source,
    )
    return ReconciliationEngine(
        chain_provider=provider,
        unit_of_work=_FakeUnitOfWork(repos),
        clock=Clock(),
        provider_name="fake_provider",
        parser_version="test_v1",
        parse_identity=TEST_PARSE_IDENTITY,
        clock_monitor=clock_monitor,
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

    # 5. reconnect occurs (mark_stream_ready is what the real ingestion
    #    manager calls immediately after a genuine reconnect+ack, per
    #    finding #1 -- reconcile() alone can never set wallet_live_state
    #    OK without it), 6. reconciliation discovers B (and re-observes A
    #    via the truth path too -- must dedup to the same single row).
    await engine.mark_stream_ready(WALLET)
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
    # Finding #1: a truth-path-only failure never touches stream_health --
    # that dimension is owned exclusively by the ingestion manager (via
    # mark_stream_ready/mark_degraded), never by reconcile(). Since this
    # test never calls either, stream_health stays at its untouched
    # default.
    assert watermark.stream_health == "UNKNOWN"
    assert watermark.reconciliation_ok is False
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

    # Finding #1: wallet_live_state can only become OK once the stream
    # dimension is also ready -- mark_stream_ready is what the real
    # ingestion manager calls right after a genuine connect+ack.
    await engine.mark_stream_ready(WALLET)
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
async def test_boundary_present_pagination_directly_observes_boundary_across_pages() -> None:
    """Two reconcile() calls, each fully paginated: the second must only
    pick up the new gap after the first call's watermark boundary, not
    re-walk everything from the start. Round 3, finding #2: this is
    proven by directly observing the boundary signature reappear in the
    provider's own address-history sequence (no `until_signature` is
    passed to the provider at all any more), not by trusting an
    empty/short page as an indirect signal."""
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
    # No call ever passes until_signature -- the boundary is confirmed by
    # direct observation in the returned sequence, not provider-side
    # truncation (finding #2).
    assert all(until is None for until, _before, _limit in provider.list_calls)


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
    # Finding #10 generalized cross-page validation: the exact same
    # signature reappearing on the next page is caught by the (more
    # specific, and now earlier-firing) duplicate-signature check before
    # the cursor-equality check ever runs -- a non-progressing cursor is
    # unreachable without also being a duplicate signature, since the
    # cursor's value always came from a previously-seen item.
    assert "duplicate signature" in result.reason or "non-progressing" in result.reason
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


# --- Phase 1 remediation round 2, finding #10: pagination continuity ---


@pytest.mark.asyncio
async def test_multi_step_cursor_cycle_fails_degraded() -> None:
    """A -> B -> A cycle spanning more than one step: the original check
    (repeated-*immediately*) would miss this. Because the next page's
    ``before`` cursor is always exactly the previous page's last item's
    signature, a cycle at *any* distance is definitionally the same
    signature reappearing -- which the duplicate-signature check catches
    per-item as soon as it happens, at whichever page that is. (A cycle
    that reintroduces a slot *lower* than one already seen also happens
    to trip the independent ordering check first here -- either detector
    firing is correct: both are real pagination-continuity faults for a
    provider that revisits already-seen data.)"""

    class _CyclingProvider(FakeChainProvider):
        _pages = {
            None: [SignatureInfo(signature="sig-B", slot=2, block_time=None, err=None)],
            "sig-B": [SignatureInfo(signature="sig-A", slot=1, block_time=None, err=None)],
            "sig-A": [SignatureInfo(signature="sig-B", slot=2, block_time=None, err=None)],
        }

        async def get_signatures_for_address(
            self, wallet_address, *, until_signature=None, before_signature=None, limit=1000
        ):
            return self._pages[before_signature]

    provider = _CyclingProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    engine = _engine(provider, ledger, store, page_size=1)

    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)

    assert result.ok is False
    assert "duplicate signature" in result.reason or "ordering fault" in result.reason
    watermark = await store.get(WALLET)
    assert watermark is not None
    assert watermark.wallet_live_state == "DEGRADED"
    assert len(ledger.rows) == 0  # nothing was ever durably processed


@pytest.mark.asyncio
async def test_out_of_order_slot_within_a_page_fails_degraded() -> None:
    class _OutOfOrderProvider(FakeChainProvider):
        async def get_signatures_for_address(
            self, wallet_address, *, until_signature=None, before_signature=None, limit=1000
        ):
            # Violates newest-first ordering: slot 1 appears before slot 5.
            return [
                SignatureInfo(signature="sig-newer-looking", slot=1, block_time=None, err=None),
                SignatureInfo(signature="sig-actually-newest", slot=5, block_time=None, err=None),
            ]

    provider = _OutOfOrderProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    engine = _engine(provider, ledger, store)

    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)

    assert result.ok is False
    assert "ordering fault" in result.reason
    watermark = await store.get(WALLET)
    assert watermark is not None
    assert watermark.wallet_live_state == "DEGRADED"


@pytest.mark.asyncio
async def test_exact_full_final_page_is_not_mistaken_for_an_unresolved_gap() -> None:
    """A last legitimate page that happens to be exactly `page_size` long
    must not be misread as "more data might remain" -- pagination
    continues one more round and correctly terminates on the natural
    empty page that follows."""
    provider = FakeChainProvider()
    for i in range(4):
        provider.add_transaction(f"sig-{i}", slot=i, raw_payload={"tx": str(i)})
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    engine = _engine(provider, ledger, store, page_size=2, max_pages=50)  # exactly 2 full pages

    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)

    assert result.ok is True
    assert result.new_events == 4
    assert len(provider.list_calls) == 3  # 2 full pages + 1 empty page confirming the end
    watermark = await store.get(WALLET)
    assert watermark is not None
    assert watermark.last_reconciled_signature == "sig-3"


# --- Phase 1 remediation round 3, finding #2: evidence-bearing boundary ---


@pytest.mark.asyncio
async def test_no_new_events_with_boundary_as_the_newest_signature() -> None:
    """The boundary is the very first item the provider returns -- zero
    new events, and the boundary is observed on the very first page."""
    provider = FakeChainProvider()
    provider.add_transaction("sig-boundary", slot=0, raw_payload={"tx": "boundary"})
    ledger = FakeEventLedger()
    store = FakeWatermarkStore(
        {WALLET: WalletWatermark(wallet_address=WALLET, last_reconciled_signature="sig-boundary")}
    )
    engine = _engine(provider, ledger, store, page_size=10)

    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)

    assert result.ok is True
    assert result.new_events == 0
    assert len(provider.list_calls) == 1  # boundary found on the very first page


@pytest.mark.asyncio
async def test_multiple_new_pages_before_the_boundary_is_observed() -> None:
    """The boundary sits several pages back -- every intervening page is
    collected as new, and the boundary is directly observed (not
    inferred) once reached."""
    provider = FakeChainProvider()
    provider.add_transaction("sig-boundary", slot=0, raw_payload={"tx": "boundary"})
    for i in range(1, 6):
        provider.add_transaction(f"sig-{i}", slot=i, raw_payload={"tx": str(i)})
    ledger = FakeEventLedger()
    store = FakeWatermarkStore(
        {WALLET: WalletWatermark(wallet_address=WALLET, last_reconciled_signature="sig-boundary")}
    )
    engine = _engine(provider, ledger, store, page_size=2)  # forces 3 pages to reach the boundary

    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)

    assert result.ok is True
    assert result.new_events == 5
    assert len(provider.list_calls) == 3
    for i in range(1, 6):
        assert (f"sig-{i}", WALLET, "TRANSACTION_OBSERVED") in ledger.rows
    assert ("sig-boundary", WALLET, "TRANSACTION_OBSERVED") not in ledger.rows


@pytest.mark.asyncio
async def test_boundary_exactly_at_a_page_edge() -> None:
    """The boundary is the very last item of a page (not the first item
    of the next one) -- must still be directly observed and excluded."""
    provider = FakeChainProvider()
    provider.add_transaction("sig-boundary", slot=0, raw_payload={"tx": "boundary"})
    provider.add_transaction("sig-1", slot=1, raw_payload={"tx": "1"})
    ledger = FakeEventLedger()
    store = FakeWatermarkStore(
        {WALLET: WalletWatermark(wallet_address=WALLET, last_reconciled_signature="sig-boundary")}
    )
    # page_size=2 means page 1 is exactly [sig-1, sig-boundary] -- the
    # boundary lands on the last slot of the first page.
    engine = _engine(provider, ledger, store, page_size=2)

    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)

    assert result.ok is True
    assert result.new_events == 1
    assert len(provider.list_calls) == 1
    watermark = await store.get(WALLET)
    assert watermark is not None
    assert watermark.last_reconciled_signature == "sig-1"


@pytest.mark.asyncio
async def test_empty_page_before_boundary_observed_fails_degraded_as_pruned() -> None:
    """A watermark boundary that no longer exists anywhere in the
    provider's retained history (simulating pruning/retention limits)
    must fail DEGRADED with an explicit reason -- never silently succeed
    just because the page came back empty."""
    provider = FakeChainProvider()  # no history at all -- the boundary is gone
    ledger = FakeEventLedger()
    store = FakeWatermarkStore(
        {WALLET: WalletWatermark(wallet_address=WALLET, last_reconciled_signature="sig-long-gone")}
    )
    engine = _engine(provider, ledger, store, page_size=10)

    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)

    assert result.ok is False
    assert "boundary not observed" in result.reason
    assert "sig-long-gone" in result.reason
    assert result.new_events == 0
    watermark = await store.get(WALLET)
    assert watermark is not None
    # The watermark itself is untouched -- still points at the same
    # boundary, so the next reconcile() call safely retries.
    assert watermark.last_reconciled_signature == "sig-long-gone"
    assert watermark.wallet_live_state == "DEGRADED"


@pytest.mark.asyncio
async def test_short_page_before_boundary_observed_fails_degraded_as_pruned() -> None:
    """A page shorter than page_size that still never contains the
    boundary is the same pruned-history failure as an empty page -- the
    old code would have wrongly treated "short page" alone as success."""
    provider = FakeChainProvider()
    for i in range(3):  # fewer than page_size=10 -- a "short" page
        provider.add_transaction(f"sig-{i}", slot=i, raw_payload={"tx": str(i)})
    ledger = FakeEventLedger()
    store = FakeWatermarkStore(
        {WALLET: WalletWatermark(wallet_address=WALLET, last_reconciled_signature="sig-long-gone")}
    )
    engine = _engine(provider, ledger, store, page_size=10)

    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)

    assert result.ok is False
    assert "boundary not observed" in result.reason
    assert result.new_events == 0
    # Nothing from the short, unverified page was durably recorded --
    # a partially-collected gap must never be treated as complete.
    assert len(ledger.rows) == 0


@pytest.mark.asyncio
async def test_safety_ceiling_with_a_pending_boundary_names_the_boundary() -> None:
    """The ceiling-exceeded message must be distinguishable from the
    bootstrap (no-boundary) case and must name the specific boundary
    signature that was never confirmed."""
    provider = FakeChainProvider()
    for i in range(10):
        provider.add_transaction(f"sig-{i}", slot=i, raw_payload={"tx": str(i)})
    # "sig-never-reached" never actually appears in provider history --
    # equivalent to a boundary the ceiling is hit before ever finding.
    ledger = FakeEventLedger()
    store = FakeWatermarkStore(
        {
            WALLET: WalletWatermark(
                wallet_address=WALLET, last_reconciled_signature="sig-never-reached"
            )
        }
    )
    engine = _engine(provider, ledger, store, page_size=2, max_pages=2)  # only 4 of 10 fit

    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)

    assert result.ok is False
    assert "safety ceiling" in result.reason
    assert "observing" in result.reason
    assert "sig-never-reached" in result.reason
    watermark = await store.get(WALLET)
    assert watermark is not None
    assert watermark.last_reconciled_signature == "sig-never-reached"  # untouched


# --- Phase 1 remediation round 2, finding #1: independent recovery dimensions


@pytest.mark.asyncio
async def test_mark_stream_ready_alone_never_restores_ok() -> None:
    """The stream dimension becoming ready is necessary but not
    sufficient -- a wallet that has never had a successful reconciliation
    must stay DEGRADED even immediately after mark_stream_ready()."""
    store = FakeWatermarkStore()
    engine = _engine(FakeChainProvider(), FakeEventLedger(), store)

    await engine.mark_stream_ready(WALLET)

    watermark = await store.get(WALLET)
    assert watermark is not None
    assert watermark.stream_health == "OK"
    assert watermark.reconciliation_ok is False
    assert watermark.wallet_live_state == "DEGRADED"
    assert watermark.is_live_entry_eligible() is False


@pytest.mark.asyncio
async def test_reconcile_alone_never_restores_ok_without_stream_ready() -> None:
    """The converse: a successful reconciliation alone, without the
    stream ever having been marked ready, must also stay DEGRADED --
    this is the literal fix for finding #1 (a successful reconcile() call
    previously reported OK regardless of whether any socket existed)."""
    provider = FakeChainProvider()
    provider.add_transaction("sig-A", slot=1, raw_payload={"tx": "A"})
    store = FakeWatermarkStore()
    engine = _engine(provider, FakeEventLedger(), store)

    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)

    assert result.ok is True
    watermark = await store.get(WALLET)
    assert watermark is not None
    assert watermark.reconciliation_ok is True
    assert watermark.stream_health == "UNKNOWN"  # never touched by reconcile()
    assert watermark.wallet_live_state == "DEGRADED"
    assert watermark.is_live_entry_eligible() is False


@pytest.mark.asyncio
async def test_stream_ready_then_reconcile_both_required_and_sufficient() -> None:
    """Only once both dimensions are independently satisfied does the
    wallet become OK -- the exact three-independent-conditions design
    finding #1 requires (the third, clock health, is covered by the
    existing clock-anomaly tests above)."""
    provider = FakeChainProvider()
    provider.add_transaction("sig-A", slot=1, raw_payload={"tx": "A"})
    store = FakeWatermarkStore()
    engine = _engine(provider, FakeEventLedger(), store)

    await engine.mark_stream_ready(WALLET)
    result = await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)

    assert result.ok is True
    watermark = await store.get(WALLET)
    assert watermark is not None
    assert watermark.wallet_live_state == "OK"
    assert watermark.is_live_entry_eligible() is True


@pytest.mark.asyncio
async def test_mark_degraded_clears_stream_dimension_without_touching_reconciliation_ok() -> None:
    """A disruptive stream transition (mark_degraded, the manager's own
    entry point) must clear the stream dimension -- but a prior
    successful reconciliation's own outcome is not retroactively
    fabricated as failed; it simply no longer matters until the stream
    (and thus the derived overall state) recovers too."""
    provider = FakeChainProvider()
    provider.add_transaction("sig-A", slot=1, raw_payload={"tx": "A"})
    store = FakeWatermarkStore()
    engine = _engine(provider, FakeEventLedger(), store)

    await engine.mark_stream_ready(WALLET)
    await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)
    watermark_ok = await store.get(WALLET)
    assert watermark_ok is not None
    assert watermark_ok.wallet_live_state == "OK"

    await engine.mark_degraded(WALLET, reason="stream disconnected")

    watermark_degraded = await store.get(WALLET)
    assert watermark_degraded is not None
    assert watermark_degraded.stream_health == "DEGRADED"
    assert watermark_degraded.reconciliation_ok is True  # not fabricated as failed
    assert watermark_degraded.wallet_live_state == "DEGRADED"  # still correctly DEGRADED overall


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

    # Without a RecentEventSource, sweep_finalization is a misconfiguration
    # (finding #8, round 4) -- ok=False with an explicit reason, never a
    # clean zero-result sweep that could hide dead finalization wiring.
    result_none = await engine_no_source.sweep_finalization(WALLET)
    assert result_none.ok is False
    assert result_none.promoted == 0
    assert "no RecentEventSource" in result_none.reason

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
    result = await engine_with_source.sweep_finalization(WALLET)
    assert result.ok is True
    assert result.promoted == 1
    state = derive_current_state(await commitment_store.list_for_event(event_id))
    assert state.commitment_level == COMMITMENT_FINALIZED


# --- R3 finding #6: typed sweep_finalization outcome distinguishing ----
# --- failure from a genuine zero-promotion sweep -----------------------


async def _wallet_ready_for_sweep(
    provider: FakeChainProvider, ledger: FakeEventLedger, store: FakeWatermarkStore
) -> uuid.UUID:
    """Shared setup: a real reconciled transaction, so
    ``last_reconciled_signature`` is non-None and sweep_finalization's own
    bootstrap guard doesn't short-circuit before reaching the provider
    call under test."""
    provider.add_transaction("sig-ready", slot=1, raw_payload={"tx": "ready"})
    engine = _engine(provider, ledger, store)
    await engine.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)
    return ledger.rows[("sig-ready", WALLET, "TRANSACTION_OBSERVED")].event_id


@pytest.mark.asyncio
async def test_sweep_finalization_provider_failure_is_typed_not_a_zero_result() -> None:
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    event_id = await _wallet_ready_for_sweep(provider, ledger, store)
    provider.raise_on_statuses = RuntimeError("provider is down")

    engine = _engine(
        provider,
        ledger,
        store,
        recent_event_source=FakeRecentEventSource([(event_id, "sig-ready")]),
    )
    result = await engine.sweep_finalization(WALLET)
    assert result.ok is False
    assert result.promoted == 0
    assert "provider is down" in result.reason


@pytest.mark.asyncio
async def test_sweep_finalization_malformed_status_cardinality_is_typed_failure() -> None:
    """The provider returning a different number of statuses than
    signatures requested is a malformed response -- must be reported as a
    typed failure, never crash via an uncaught ``zip(strict=True)``
    ``ValueError`` and never be silently treated as zero promotions."""

    class _WrongCardinalityProvider(FakeChainProvider):
        async def get_signature_statuses(self, signatures: list[str]) -> list[Any]:
            return []  # always empty, regardless of how many were requested

    provider = _WrongCardinalityProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    event_id = await _wallet_ready_for_sweep(provider, ledger, store)

    engine = _engine(
        provider,
        ledger,
        store,
        recent_event_source=FakeRecentEventSource([(event_id, "sig-ready")]),
    )
    result = await engine.sweep_finalization(WALLET)
    assert result.ok is False
    assert result.promoted == 0
    assert "malformed status response" in result.reason


@pytest.mark.asyncio
async def test_sweep_finalization_cancellation_propagates_uncaught() -> None:
    """Cancellation (a BaseException, not an Exception) must never be
    swallowed into a typed failure result -- exactly like
    argus.providers.http.send_with_usage, no terminal outcome actually
    happened, so propagating it untouched is correct; converting it to
    ``ok=False`` would fabricate a result for work that never finished."""
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    event_id = await _wallet_ready_for_sweep(provider, ledger, store)
    provider.raise_on_statuses = asyncio.CancelledError()

    engine = _engine(
        provider,
        ledger,
        store,
        recent_event_source=FakeRecentEventSource([(event_id, "sig-ready")]),
    )
    with pytest.raises(asyncio.CancelledError):
        await engine.sweep_finalization(WALLET)


@pytest.mark.asyncio
async def test_sweep_finalization_restart_retries_cleanly_after_a_failed_sweep() -> None:
    """A failed sweep must never leave behind state that blocks the next
    attempt -- a fresh engine instance (simulating a process restart)
    against the same already-persisted watermark/commitment state must
    retry cleanly and succeed once the provider recovers."""
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    commitment_store = FakeCommitmentStore()
    event_id = await _wallet_ready_for_sweep(provider, ledger, store)
    provider.raise_on_statuses = RuntimeError("transient provider outage")

    failing_engine = _engine(
        provider,
        ledger,
        store,
        commitment_store=commitment_store,
        recent_event_source=FakeRecentEventSource([(event_id, "sig-ready")]),
    )
    failed_result = await failing_engine.sweep_finalization(WALLET)
    assert failed_result.ok is False

    # "Restart": a brand-new engine instance, the provider recovered.
    provider.raise_on_statuses = None
    provider.signature_statuses["sig-ready"] = SignatureStatusInfo(
        signature="sig-ready", confirmation_status="finalized", err=None, slot=1
    )
    restarted_engine = _engine(
        provider,
        ledger,
        store,
        commitment_store=commitment_store,
        recent_event_source=FakeRecentEventSource([(event_id, "sig-ready")]),
    )
    recovered_result = await restarted_engine.sweep_finalization(WALLET)
    assert recovered_result.ok is True
    assert recovered_result.promoted == 1


@pytest.mark.asyncio
async def test_sweep_finalization_duplicate_observation_not_double_counted() -> None:
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    commitment_store = FakeCommitmentStore()
    event_id = await _wallet_ready_for_sweep(provider, ledger, store)
    provider.signature_statuses["sig-ready"] = SignatureStatusInfo(
        signature="sig-ready", confirmation_status="finalized", err=None, slot=1
    )
    engine = _engine(
        provider,
        ledger,
        store,
        commitment_store=commitment_store,
        recent_event_source=FakeRecentEventSource([(event_id, "sig-ready")]),
    )

    first = await engine.sweep_finalization(WALLET)
    assert first.ok is True
    assert first.promoted == 1

    second = await engine.sweep_finalization(WALLET)
    assert second.ok is True
    assert second.promoted == 0  # DUPLICATE_NOOP -- a clean, genuine zero, not a failure


@pytest.mark.asyncio
async def test_sweep_finalization_clean_zero_when_nothing_is_finalized_yet() -> None:
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    event_id = await _wallet_ready_for_sweep(provider, ledger, store)
    # No entry in provider.signature_statuses -- get_signature_statuses
    # returns the default (confirmation_status=None), i.e. genuinely not
    # yet finalized on-chain.
    engine = _engine(
        provider,
        ledger,
        store,
        recent_event_source=FakeRecentEventSource([(event_id, "sig-ready")]),
    )
    result = await engine.sweep_finalization(WALLET)
    assert result.ok is True
    assert result.promoted == 0
    assert result.reason == ""


class _AppendFailingCommitmentStore:
    """Wraps a real in-memory commitment store but raises from
    ``append()`` for one configured event, simulating a genuine DB
    failure mid-sweep (as distinct from CommitmentTracker's own typed
    FAILED/DUPLICATE_NOOP business-rule outcomes, which never raise)."""

    def __init__(self, inner: Any, *, fail_for: uuid.UUID) -> None:
        self._inner = inner
        self._fail_for = fail_for

    async def list_for_event(self, event_id: uuid.UUID) -> list[Any]:
        return await self._inner.list_for_event(event_id)

    async def append(self, observation: Any) -> None:
        if observation.event_id == self._fail_for:
            raise RuntimeError("simulated commitment DB failure")
        await self._inner.append(observation)

    async def append_rejection(self, **kwargs: Any) -> None:
        await self._inner.append_rejection(**kwargs)

    def lock(self, event_id: uuid.UUID) -> Any:
        return self._inner.lock(event_id)


@pytest.mark.asyncio
async def test_sweep_finalization_per_event_append_failure_is_typed_and_keeps_other_promotions() -> (
    None
):
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    event_id_1 = await _wallet_ready_for_sweep(provider, ledger, store)
    provider.add_transaction("sig-ready-2", slot=2, raw_payload={"tx": "ready-2"})
    engine_seed = _engine(provider, ledger, store)
    await engine_seed.reconcile(WALLET, ReconciliationTrigger.SCHEDULED)
    event_id_2 = ledger.rows[("sig-ready-2", WALLET, "TRANSACTION_OBSERVED")].event_id

    for sig in ("sig-ready", "sig-ready-2"):
        provider.signature_statuses[sig] = SignatureStatusInfo(
            signature=sig, confirmation_status="finalized", err=None, slot=1
        )

    failing_store = _AppendFailingCommitmentStore(FakeCommitmentStore(), fail_for=event_id_1)
    engine = _engine(
        provider,
        ledger,
        store,
        commitment_store=failing_store,
        recent_event_source=FakeRecentEventSource(
            [(event_id_1, "sig-ready"), (event_id_2, "sig-ready-2")]
        ),
    )
    result = await engine.sweep_finalization(WALLET)
    assert result.ok is False
    assert result.promoted == 1  # event_id_2 still succeeded despite event_id_1's failure
    assert "1 of 2" in result.reason


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
    key = (event_id, "generic_balance_delta_v1", TEST_PARSE_IDENTITY.build_hash)
    assert key in swap_recorder.rows
    parsed = swap_recorder.rows[key]
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
        event_id=event_id,
        wallet_address=WALLET,
        parsed=parsed_again,
        build_hash=TEST_PARSE_IDENTITY.build_hash,
        created_at=Clock().utc_now(),
    )
    # same (event_id, parser_version, build_hash) -- no duplicate
    assert added_again is False
    assert len(swap_recorder.rows) == 1

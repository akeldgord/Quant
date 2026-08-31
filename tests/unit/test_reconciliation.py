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
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any

import pytest

from argus.clock import Clock
from argus.ingestion.reconciliation import (
    ChainEventDraft,
    ReconciliationEngine,
    ReconciliationTrigger,
    WalletWatermark,
)
from argus.providers import SignatureInfo, StreamNotification

WALLET = "TestWallet1111111111111111111111111111111"


class FakeChainProvider:
    """In-memory chain history: signatures are appended in causal (oldest
    first) order; `get_signatures_for_address` returns newest-first and
    stops at (exclusive of) `until_signature`, matching real RPC
    semantics."""

    def __init__(self) -> None:
        self._history: list[SignatureInfo] = []
        self._transactions: dict[str, dict[str, Any]] = {}
        self.raise_on_list: Exception | None = None
        self.raise_on_fetch: dict[str, Exception] = {}

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
        self, wallet_address: str, *, until_signature: str | None = None, limit: int = 1000
    ) -> list[SignatureInfo]:
        if self.raise_on_list is not None:
            raise self.raise_on_list
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
        if signature in self.raise_on_fetch:
            raise self.raise_on_fetch[signature]
        return self._transactions[signature]

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

    async def record(self, draft: ChainEventDraft) -> bool:
        key = (draft.transaction_signature, draft.wallet_address, draft.event_type)
        if key in self.rows:
            return False
        self.rows[key] = draft
        return True


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


def _engine(
    provider: FakeChainProvider,
    ledger: FakeEventLedger,
    store: FakeWatermarkStore,
    *,
    clock_monitor: Any | None = None,
) -> ReconciliationEngine:
    return ReconciliationEngine(
        chain_provider=provider,
        watermark_store=store,
        event_recorder=ledger,
        clock=Clock(),
        provider_name="fake_provider",
        parser_version="test_v1",
        clock_monitor=clock_monitor,
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

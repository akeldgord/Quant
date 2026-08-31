"""Tests for `argus.ingestion.manager.IngestionManager` -- Phase 1
remediation round 1, finding #1: the end-to-end orchestration loop tying
the WebSocket stream, truth-path reconciliation, and clock-health
monitoring into live, restart-safe, per-wallet ingestion.

Everything here runs against fakes (`FakeLiveStream`, the same
`FakeChainProvider`/`FakeEventLedger`/`FakeWatermarkStore`/
`FakeCommitmentStore`/`FakeSwapRecorder` used in
`tests/unit/test_reconciliation.py`) -- no credential, no real network,
no live provider. A fake connector proves the manager's own orchestration
logic; it is never claimed to be live-provider validation.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from argus.clock import Clock
from argus.ingestion.clock_monitor import InMemoryClockHealthRecorder, PersistentClockMonitor
from argus.ingestion.manager import (
    IngestionManager,
    IngestionManagerConfig,
    StaticWalletSource,
)
from argus.ingestion.parse_ledger import InMemoryParseAttemptRecorder
from argus.ingestion.reconciliation import ReconciliationEngine, ReconciliationRepos
from argus.providers import StreamNotification
from argus.providers.usage import RequestUsageRecord, StreamingUsageRecord
from tests.unit.test_reconciliation import (
    FakeChainProvider,
    FakeCommitmentStore,
    FakeEventLedger,
    FakeSwapRecorder,
    FakeWatermarkStore,
    _FakeUnitOfWork,
    _valid_raw_payload,
)


class FakeLiveStream:
    """A scripted sequence of subscription "sessions" per wallet. Each
    session is a list of items: a `StreamNotification` is yielded; a
    `BaseException` instance is raised (simulating disconnect/malformed-
    message/subscription-failure -- whatever the exception type implies).
    Once a wallet's scripted sessions are exhausted, the next subscribe
    call hangs indefinitely (an idle-but-healthy connection) until
    cancelled, so a test can deterministically decide when to stop."""

    def __init__(self) -> None:
        self._sessions: dict[str, list[list[Any]]] = {}
        self.subscribe_calls: list[str] = []

    def script(self, wallet: str, *sessions: list[Any]) -> None:
        self._sessions[wallet] = list(sessions)

    async def subscribe_wallet(self, wallet_address: str) -> AsyncIterator[StreamNotification]:
        self.subscribe_calls.append(wallet_address)
        call_index = sum(1 for c in self.subscribe_calls if c == wallet_address) - 1
        sessions = self._sessions.get(wallet_address, [])
        if call_index >= len(sessions):
            await asyncio.Event().wait()  # idle forever; cancelled by the test when done
            return
        for item in sessions[call_index]:
            if isinstance(item, BaseException):
                raise item
            yield item

    async def unsubscribe_wallet(self, wallet_address: str) -> None:
        return None


class FakeUsageRecorder:
    def __init__(self) -> None:
        self.requests: list[RequestUsageRecord] = []
        self.streaming: list[StreamingUsageRecord] = []

    async def record_request(self, record: RequestUsageRecord) -> None:
        self.requests.append(record)

    async def record_streaming(self, record: StreamingUsageRecord) -> None:
        self.streaming.append(record)


WALLET_A = "ManagerWalletA1111111111111111111111111111"
WALLET_B = "ManagerWalletB2222222222222222222222222222"

FAST_CONFIG = IngestionManagerConfig(
    reconnect_base_delay_seconds=0.001,
    reconnect_max_delay_seconds=0.005,
    stream_receive_timeout_seconds=0.05,
    periodic_reconciliation_interval_seconds=3600,
    clock_heartbeat_interval_seconds=3600,
)


def _manager(
    provider: FakeChainProvider,
    stream: FakeLiveStream,
    ledger: FakeEventLedger,
    store: FakeWatermarkStore,
    wallets: tuple[str, ...],
    *,
    commitment_store: FakeCommitmentStore | None = None,
    swap_recorder: FakeSwapRecorder | None = None,
    clock_monitor: PersistentClockMonitor | None = None,
    streaming_usage_recorder: FakeUsageRecorder | None = None,
    config: IngestionManagerConfig = FAST_CONFIG,
) -> IngestionManager:
    repos = ReconciliationRepos(
        watermark_store=store,
        event_recorder=ledger,
        commitment_store=commitment_store or FakeCommitmentStore(),
        swap_recorder=swap_recorder or FakeSwapRecorder(),
        parse_attempt_recorder=InMemoryParseAttemptRecorder(),
        recent_event_source=None,
    )
    engine = ReconciliationEngine(
        chain_provider=provider,
        unit_of_work=_FakeUnitOfWork(repos),
        clock=Clock(),
        provider_name="fake_provider",
        parser_version="test_v1",
        clock_monitor=clock_monitor,
    )
    return IngestionManager(
        wallet_source=StaticWalletSource(wallets),
        stream=stream,
        chain_provider=provider,
        reconciliation_engine=engine,
        provider_name="fake_provider",
        clock=Clock(),
        clock_monitor=clock_monitor,
        streaming_usage_recorder=streaming_usage_recorder,
        config=config,
    )


async def _run_until(
    stop_event: asyncio.Event, manager: IngestionManager, predicate, *, timeout: float = 2.0
) -> None:
    run_task = asyncio.ensure_future(manager.run(stop_event=stop_event))
    try:
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(0)
    finally:
        stop_event.set()
        await run_task


def test_ingestion_manager_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="reconnect_base_delay_seconds"):
        IngestionManagerConfig(reconnect_base_delay_seconds=0)
    with pytest.raises(ValueError, match="reconnect_max_delay_seconds"):
        IngestionManagerConfig(reconnect_base_delay_seconds=10, reconnect_max_delay_seconds=1)
    with pytest.raises(ValueError, match="stream_receive_timeout_seconds"):
        IngestionManagerConfig(stream_receive_timeout_seconds=0)
    with pytest.raises(ValueError, match="periodic_reconciliation_interval_seconds"):
        IngestionManagerConfig(periodic_reconciliation_interval_seconds=0)
    with pytest.raises(ValueError, match="clock_heartbeat_interval_seconds"):
        IngestionManagerConfig(clock_heartbeat_interval_seconds=0)


# --- Mandatory acceptance test 1: connect -> A -> disconnect -> B missed -> reconnect -> A/B exactly once


async def test_end_to_end_disconnect_reconnect_canonicalizes_a_and_b_exactly_once() -> None:
    provider = FakeChainProvider()
    provider.add_transaction("sig-A", slot=1, raw_payload={"tx": "A"})
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    stream = FakeLiveStream()
    stream.script(
        WALLET_A,
        [
            StreamNotification(wallet_address=WALLET_A, signature="sig-A", slot=1),
            ConnectionError("dropped"),
        ],
    )
    manager = _manager(provider, stream, ledger, store, (WALLET_A,))

    # "B occurs while disconnected" -- added exactly once, gated on A
    # already being fast-path-recorded, not unconditionally on every
    # predicate poll. Phase 1 remediation round 2's pagination-continuity
    # validation (finding #10) now correctly DEGRADEs a reconciliation
    # that ever sees the same signature twice in fetched history, so
    # repeatedly re-adding "sig-B" here would itself make the fake
    # provider malformed.
    b_added = False

    def a_and_b_recorded() -> bool:
        nonlocal b_added
        if not b_added and ("sig-A", WALLET_A, "TRANSACTION_OBSERVED") in ledger.rows:
            provider.add_transaction("sig-B", slot=2, raw_payload={"tx": "B"})
            b_added = True
        return (
            b_added
            and (
                "sig-B",
                WALLET_A,
                "TRANSACTION_OBSERVED",
            )
            in ledger.rows
        )

    stop_event = asyncio.Event()
    await _run_until(stop_event, manager, a_and_b_recorded)

    assert len(ledger.rows) == 2
    watermark = await store.get(WALLET_A)
    assert watermark is not None
    assert watermark.last_reconciled_signature == "sig-B"


# --- Mandatory acceptance test 2: same scenario across manager restart + duplicate delivery


async def test_scenario_survives_manager_restart_and_duplicate_delivery() -> None:
    provider = FakeChainProvider()
    provider.add_transaction("sig-A", slot=1, raw_payload={"tx": "A"})
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    stream = FakeLiveStream()
    # Duplicate delivery: sig-A observed twice on the fast path before disconnecting.
    stream.script(
        WALLET_A,
        [
            StreamNotification(wallet_address=WALLET_A, signature="sig-A", slot=1),
            StreamNotification(wallet_address=WALLET_A, signature="sig-A", slot=1),
            ConnectionError("dropped"),
        ],
    )
    manager = _manager(provider, stream, ledger, store, (WALLET_A,))

    stop_event = asyncio.Event()
    await _run_until(
        stop_event, manager, lambda: ("sig-A", WALLET_A, "TRANSACTION_OBSERVED") in ledger.rows
    )
    assert len(ledger.rows) == 1  # duplicate fast-path delivery did not double-record

    # "Manager restart": brand-new manager/engine, watermark store reloaded
    # from a persisted snapshot; the ledger fake stands in for the DB,
    # which does survive a restart.
    provider.add_transaction("sig-B", slot=2, raw_payload={"tx": "B"})
    restarted_store = FakeWatermarkStore(snapshot=store.snapshot())
    restarted_stream = FakeLiveStream()
    restarted_stream.script(
        WALLET_A, [ConnectionError("immediate disconnect to force a quick reconcile-only cycle")]
    )
    restarted_manager = _manager(provider, restarted_stream, ledger, restarted_store, (WALLET_A,))

    stop_event2 = asyncio.Event()
    await _run_until(
        stop_event2,
        restarted_manager,
        lambda: ("sig-B", WALLET_A, "TRANSACTION_OBSERVED") in ledger.rows,
    )
    assert len(ledger.rows) == 2


# --- Mandatory acceptance test 3: multiple wallets remain isolated under concurrent subscriptions


async def test_multiple_wallets_remain_isolated_under_concurrent_subscriptions() -> None:
    """Wallet A's single-notification session ends naturally (its script
    has nothing after the one yield) -- a real stream-exhausted transition,
    which correctly and transiently marks it DEGRADED before its own
    reconnect (to the fallback "idle forever" session) settles it back to
    OK. Wallet B disconnects with a real error and never recovers (its
    fallback session also idles, but starting from DEGRADED). The
    predicate below waits until wallet A has demonstrably completed its
    own reconnect cycle (subscribe called for A at least twice) before
    checking its final state, so it isn't caught mid-transition -- and
    proves throughout that wallet B's failure never touches wallet A's
    watermark or vice versa."""
    provider = FakeChainProvider()
    provider.add_transaction("sig-A1", slot=1, raw_payload={"tx": "A1"})
    provider2 = provider  # same fake provider instance serves both wallets' histories
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    stream = FakeLiveStream()
    stream.script(
        WALLET_A, [StreamNotification(wallet_address=WALLET_A, signature="sig-A1", slot=1)]
    )
    stream.script(WALLET_B, [ConnectionError("wallet B disconnects, wallet A must be unaffected")])
    # A long receive-timeout here specifically: once wallet A reconnects to
    # its fallback "idle forever" session, nothing will ever arrive on it
    # again -- with FAST_CONFIG's short timeout that would itself keep
    # re-triggering (correct, but irrelevant to what this test is proving,
    # and it would make the stopping predicate flaky).
    manager = _manager(
        provider2,
        stream,
        ledger,
        store,
        (WALLET_A, WALLET_B),
        config=IngestionManagerConfig(
            reconnect_base_delay_seconds=0.001,
            reconnect_max_delay_seconds=0.005,
            stream_receive_timeout_seconds=3600,
            periodic_reconciliation_interval_seconds=3600,
            clock_heartbeat_interval_seconds=3600,
        ),
    )

    # Snapshot into this closure the instant the condition is true, rather
    # than re-reading watermark state after shutdown: stopping the manager
    # cancels wallet A's still-idling receive loop, and cancellation is
    # itself a disruptive transition this manager must (and does) mark
    # DEGRADED before propagating -- correct shutdown behavior, but not
    # what this test is about, so it must not be what's asserted on.
    observed: dict[str, Any] = {}

    def wallet_a_recovered_and_b_degraded() -> bool:
        calls_for_a = sum(1 for c in stream.subscribe_calls if c == WALLET_A)
        wm_a = store._rows.get(WALLET_A)  # noqa: SLF001 - direct fake introspection in tests
        wm_b = store._rows.get(WALLET_B)  # noqa: SLF001
        ok = (
            calls_for_a >= 2
            and wm_a is not None
            and wm_a.wallet_live_state == "OK"
            and wm_b is not None
            and wm_b.wallet_live_state == "DEGRADED"
        )
        if ok:
            observed["wm_a"] = wm_a
            observed["wm_b"] = wm_b
        return ok

    stop_event = asyncio.Event()
    await _run_until(stop_event, manager, wallet_a_recovered_and_b_degraded)

    assert observed["wm_a"].is_live_entry_eligible() is True
    assert observed["wm_b"].is_live_entry_eligible() is False
    assert ("sig-A1", WALLET_A, "TRANSACTION_OBSERVED") in ledger.rows


# --- Mandatory acceptance test 4: every disruptive transition fails DEGRADED


async def test_timeout_fails_degraded() -> None:
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    stream = FakeLiveStream()  # no scripted sessions -> subscribe hangs -> receive-timeout fires
    manager = _manager(
        provider,
        stream,
        ledger,
        store,
        (WALLET_A,),
        config=IngestionManagerConfig(
            reconnect_base_delay_seconds=0.001,
            reconnect_max_delay_seconds=0.005,
            stream_receive_timeout_seconds=0.01,
            periodic_reconciliation_interval_seconds=3600,
            clock_heartbeat_interval_seconds=3600,
        ),
    )

    def degraded_at_least_once() -> bool:
        wm = store._rows.get(WALLET_A)  # noqa: SLF001
        return wm is not None and wm.wallet_live_state == "DEGRADED"

    stop_event = asyncio.Event()
    await _run_until(stop_event, manager, degraded_at_least_once, timeout=3.0)


async def test_malformed_message_and_subscription_failure_fail_degraded() -> None:
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    stream = FakeLiveStream()
    from argus.providers.helius.client import HeliusRpcError

    stream.script(WALLET_A, [HeliusRpcError("malformed logsNotification")])
    manager = _manager(provider, stream, ledger, store, (WALLET_A,))

    def degraded() -> bool:
        wm = store._rows.get(WALLET_A)  # noqa: SLF001
        return wm is not None and wm.wallet_live_state == "DEGRADED"

    stop_event = asyncio.Event()
    await _run_until(stop_event, manager, degraded)


async def test_exhausted_iterator_fails_degraded_not_treated_as_clean_stop() -> None:
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    stream = FakeLiveStream()
    stream.script(WALLET_A, [])  # generator ends immediately -- StopAsyncIteration, not an error
    manager = _manager(provider, stream, ledger, store, (WALLET_A,))

    def degraded() -> bool:
        wm = store._rows.get(WALLET_A)  # noqa: SLF001
        return wm is not None and wm.wallet_live_state == "DEGRADED"

    stop_event = asyncio.Event()
    await _run_until(stop_event, manager, degraded)


async def test_clock_anomaly_fails_all_tracked_wallets_degraded() -> None:
    from datetime import UTC, datetime, timedelta

    from argus.clock import ClockSample

    class _AnomalousClock(Clock):
        def __init__(self) -> None:
            super().__init__(max_drift_seconds=1.0)
            t0 = datetime(2026, 1, 1, tzinfo=UTC)
            self._samples = iter(
                [ClockSample(t0, 100.0), ClockSample(t0 + timedelta(hours=1), 101.0)]
            )

        def sample(self) -> ClockSample:
            return next(self._samples)

    provider = FakeChainProvider()
    provider.add_transaction("sig-A", slot=1, raw_payload={"tx": "A"})
    provider.add_transaction("sig-B", slot=1, raw_payload={"tx": "B"})
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    stream = FakeLiveStream()  # both wallets just idle -- no stream-level disconnects at all
    monitor = PersistentClockMonitor(
        clock=_AnomalousClock(), recorder=InMemoryClockHealthRecorder()
    )
    manager = _manager(
        provider,
        stream,
        ledger,
        store,
        (WALLET_A, WALLET_B),
        clock_monitor=monitor,
        config=IngestionManagerConfig(
            reconnect_base_delay_seconds=0.001,
            reconnect_max_delay_seconds=0.005,
            stream_receive_timeout_seconds=3600,
            periodic_reconciliation_interval_seconds=3600,
            clock_heartbeat_interval_seconds=0.01,
        ),
    )

    def both_degraded() -> bool:
        wm_a = store._rows.get(WALLET_A)  # noqa: SLF001
        wm_b = store._rows.get(WALLET_B)  # noqa: SLF001
        return (
            wm_a is not None
            and wm_a.wallet_live_state == "DEGRADED"
            and wm_b is not None
            and wm_b.wallet_live_state == "DEGRADED"
        )

    stop_event = asyncio.Event()
    await _run_until(stop_event, manager, both_degraded, timeout=3.0)
    assert monitor.anomaly_detected is True


# --- Mandatory acceptance test 5: recovery requires reconnection + reconciliation + healthy clock


async def test_recovery_blocked_while_clock_anomaly_outstanding_even_after_reconnect() -> None:
    from datetime import UTC, datetime, timedelta

    from argus.clock import ClockSample

    class _AnomalousClock(Clock):
        def __init__(self) -> None:
            super().__init__(max_drift_seconds=1.0)
            t0 = datetime(2026, 1, 1, tzinfo=UTC)
            self._samples = iter(
                [ClockSample(t0, 100.0), ClockSample(t0 + timedelta(hours=1), 101.0)]
            )

        def sample(self) -> ClockSample:
            return next(self._samples)

    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    stream = FakeLiveStream()
    stream.script(
        WALLET_A,
        [
            ConnectionError("dropped"),
            ConnectionError(
                "also fails to leave DEGRADED-then-reconnect-then-anomaly path clean; second reconnect settles"
            ),
        ],
    )
    monitor = PersistentClockMonitor(
        clock=_AnomalousClock(), recorder=InMemoryClockHealthRecorder()
    )
    manager = _manager(
        provider,
        stream,
        ledger,
        store,
        (WALLET_A,),
        clock_monitor=monitor,
        config=FAST_CONFIG,
    )

    def reconnected_at_least_twice() -> bool:
        return sum(1 for c in stream.subscribe_calls if c == WALLET_A) >= 3

    stop_event = asyncio.Event()
    await _run_until(stop_event, manager, reconnected_at_least_twice, timeout=3.0)

    # The clock anomaly (detected via the first tick pair, immediately)
    # must keep the wallet DEGRADED even though the stream itself
    # successfully reconnected and reconciliation ran without error.
    watermark = await store.get(WALLET_A)
    assert watermark is not None
    assert watermark.wallet_live_state == "DEGRADED"
    assert watermark.is_live_entry_eligible() is False


# --- Mandatory acceptance test 6: streaming usage recorded from the manager's real code path


async def test_streaming_usage_recorded_from_manager_real_code_path() -> None:
    provider = FakeChainProvider()
    provider.add_transaction("sig-A", slot=1, raw_payload=_valid_raw_payload())
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    stream = FakeLiveStream()
    stream.script(
        WALLET_A,
        [
            StreamNotification(wallet_address=WALLET_A, signature="sig-A", slot=1),
            ConnectionError("dropped"),
        ],
    )
    usage = FakeUsageRecorder()
    manager = _manager(provider, stream, ledger, store, (WALLET_A,), streaming_usage_recorder=usage)

    stop_event = asyncio.Event()
    await _run_until(
        stop_event, manager, lambda: ("sig-A", WALLET_A, "TRANSACTION_OBSERVED") in ledger.rows
    )

    assert len(usage.streaming) >= 1
    connection_records = [r for r in usage.streaming if r.connection_count > 0]
    assert len(connection_records) >= 1
    byte_records = [r for r in usage.streaming if r.bytes_received]
    assert len(byte_records) >= 1
    reconnect_records = [r for r in usage.streaming if r.reconnect_count > 0]
    assert len(reconnect_records) >= 1


async def test_manager_never_signs_executes_or_broadcasts() -> None:
    """No live-entry/signing/execution/broadcast path exists anywhere on
    IngestionManager -- asserted directly, not just by absence of use."""
    assert not hasattr(IngestionManager, "sign")
    assert not hasattr(IngestionManager, "execute")
    assert not hasattr(IngestionManager, "broadcast")
    assert not hasattr(IngestionManager, "submit_order")

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
    IngestionManagerFailure,
    StaticWalletSource,
)
from argus.ingestion.parse_ledger import InMemoryParseAttemptRecorder
from argus.ingestion.reconciliation import ReconciliationEngine, ReconciliationRepos
from argus.providers import StreamNotification
from argus.providers.usage import RequestUsageRecord, StreamingUsageRecord
from tests.unit.test_reconciliation import (
    TEST_PARSE_IDENTITY,
    FakeChainProvider,
    FakeCommitmentStore,
    FakeEventLedger,
    FakeSwapRecorder,
    FakeWatermarkStore,
    _FakeUnitOfWork,
    _valid_raw_payload,
)


class FakeSubscription:
    """Implements `argus.providers.StreamSubscription`. ``items is None``
    means "idle forever" (never yields, never ends) -- the fallback once a
    wallet's scripted sessions are exhausted."""

    def __init__(
        self, items: list[Any] | None, *, liveness_results: list[bool] | None = None
    ) -> None:
        self._items = items
        self.closed = False
        # `None` (the default) means "always alive" -- most tests never
        # exercise the liveness-probe path at all (a long
        # stream_receive_timeout_seconds means it's never reached within
        # the test's own timeout budget). A list is popped from in order;
        # once exhausted, further calls report alive.
        self._liveness_results = liveness_results
        self.liveness_checks = 0

    async def check_liveness(self, *, timeout_seconds: float) -> bool:
        self.liveness_checks += 1
        if self._liveness_results:
            return self._liveness_results.pop(0)
        return True

    async def notifications(self) -> AsyncIterator[StreamNotification]:
        if self._items is None:
            await asyncio.Event().wait()  # idle forever; cancelled by the test when done
            return
            yield  # pragma: no cover - unreachable; makes this an async generator function
        for item in self._items:
            if isinstance(item, BaseException):
                raise item
            yield item

    async def close(self) -> None:
        self.closed = True


class FakeLiveStream:
    """A scripted sequence of subscription "sessions" per wallet. Each
    session is a list of items: a `StreamNotification` is yielded; a
    `BaseException` instance is raised (simulating disconnect/malformed-
    message -- whatever the exception type implies) once iteration
    begins. Once a wallet's scripted sessions are exhausted, the next
    ``open_subscription`` call returns a subscription that idles
    indefinitely (an idle-but-healthy connection) until cancelled, so a
    test can deterministically decide when to stop.

    ``ack_gate``, if set for a wallet, makes ``open_subscription`` for
    that wallet await the gate before returning -- proving the manager
    genuinely waits for acknowledgement before doing anything else
    (finding #1), rather than merely calling an API that happens to be
    named correctly."""

    def __init__(self) -> None:
        self._sessions: dict[str, list[list[Any]]] = {}
        self._ack_failures: dict[str, list[BaseException]] = {}
        self._liveness: dict[str, list[list[bool] | None]] = {}
        self.ack_gates: dict[str, asyncio.Event] = {}
        self.subscribe_calls: list[str] = []
        self.subscriptions: list[FakeSubscription] = []

    def script(self, wallet: str, *sessions: list[Any]) -> None:
        self._sessions[wallet] = list(sessions)

    def script_ack_failures(self, wallet: str, *failures: BaseException) -> None:
        """The Nth call to ``open_subscription`` for this wallet raises
        the Nth failure here (simulating connect/subscribe/ack itself
        failing) instead of returning a subscription at all."""
        self._ack_failures[wallet] = list(failures)

    def script_liveness(self, wallet: str, *per_session_results: list[bool] | None) -> None:
        """The Nth ``open_subscription`` call's ``FakeSubscription`` gets
        the Nth entry here as its ``check_liveness`` script (``None`` --
        the default when unscripted -- means "always alive"). Used to
        simulate a genuinely dead connection (round 5, finding #6): a
        receive-timeout alone must not mean DEGRADED any more, only a
        receive-timeout *and* a failed liveness probe."""
        self._liveness[wallet] = list(per_session_results)

    async def open_subscription(self, wallet_address: str) -> FakeSubscription:
        self.subscribe_calls.append(wallet_address)
        call_index = sum(1 for c in self.subscribe_calls if c == wallet_address) - 1

        if wallet_address in self.ack_gates:
            await self.ack_gates[wallet_address].wait()

        failures = self._ack_failures.get(wallet_address, [])
        if call_index < len(failures):
            raise failures[call_index]

        sessions = self._sessions.get(wallet_address, [])
        liveness_scripts = self._liveness.get(wallet_address, [])
        subscription = FakeSubscription(
            sessions[call_index] if call_index < len(sessions) else None,
            liveness_results=(
                list(liveness_scripts[call_index])
                if call_index < len(liveness_scripts) and liveness_scripts[call_index] is not None
                else None
            ),
        )
        self.subscriptions.append(subscription)
        return subscription

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
    recent_event_source: Any | None = None,
    config: IngestionManagerConfig = FAST_CONFIG,
) -> IngestionManager:
    repos = ReconciliationRepos(
        watermark_store=store,
        event_recorder=ledger,
        commitment_store=commitment_store or FakeCommitmentStore(),
        swap_recorder=swap_recorder or FakeSwapRecorder(),
        parse_attempt_recorder=InMemoryParseAttemptRecorder(),
        recent_event_source=recent_event_source,
    )
    engine = ReconciliationEngine(
        chain_provider=provider,
        unit_of_work=_FakeUnitOfWork(repos),
        clock=Clock(),
        provider_name="fake_provider",
        parser_version="test_v1",
        parse_identity=TEST_PARSE_IDENTITY,
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
    OK. Wallet B disconnects with a real error, is marked DEGRADED, and
    then also reconnects to its own fallback "idle forever" session (both
    wallets' fallback sessions eventually reconcile OK the same way --
    the two wallets' reconnect cycles race independently against each
    other in real wall-clock time, so which one finishes first is not
    deterministic and must not be asserted on). Each wallet's own
    condition -- A demonstrably completing a full reconnect cycle
    (subscribe called at least twice, ending OK), B genuinely having been
    marked DEGRADED at least once -- is captured independently, the first
    time it's ever observed, regardless of what the other wallet is doing
    at that moment; this proves both transitions genuinely happened
    without requiring them to coexist at the same instant, and proves
    throughout that wallet B's failure never touches wallet A's watermark
    or vice versa."""
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

    def both_conditions_observed() -> bool:
        # Each wallet's own condition is captured independently, the
        # first time it's ever seen (sticky -- never overwritten by a
        # later observation), regardless of the other wallet's state at
        # that moment: the two wallets' reconnect cycles race against
        # each other in real wall-clock time, so which finishes first is
        # not deterministic and must never be asserted on.
        if "wm_a" not in observed:
            calls_for_a = sum(1 for c in stream.subscribe_calls if c == WALLET_A)
            wm_a = store._rows.get(WALLET_A)  # noqa: SLF001 - direct fake introspection in tests
            if calls_for_a >= 2 and wm_a is not None and wm_a.wallet_live_state == "OK":
                observed["wm_a"] = wm_a
        if "wm_b" not in observed:
            wm_b = store._rows.get(WALLET_B)  # noqa: SLF001
            if wm_b is not None and wm_b.wallet_live_state == "DEGRADED":
                observed["wm_b"] = wm_b
        return "wm_a" in observed and "wm_b" in observed

    stop_event = asyncio.Event()
    await _run_until(stop_event, manager, both_conditions_observed)

    assert observed["wm_a"].is_live_entry_eligible() is True
    assert observed["wm_b"].is_live_entry_eligible() is False
    assert ("sig-A1", WALLET_A, "TRANSACTION_OBSERVED") in ledger.rows


# --- Mandatory acceptance test 4: every disruptive transition fails DEGRADED


async def test_timeout_fails_degraded() -> None:
    """Phase 1 remediation round 5, finding #6: a receive-timeout alone
    is no longer enough to mean DEGRADED -- a quiet-but-healthy
    connection must survive it via a liveness probe. This wallet's
    liveness probe is scripted to fail (a genuinely dead connection), so
    DEGRADED is still the correct outcome once the timeout fires."""
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    stream = FakeLiveStream()  # no scripted sessions -> subscribe hangs -> receive-timeout fires
    stream.script_liveness(WALLET_A, [False])
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
    # Phase 1 remediation round 5, finding #6: two separate scripted
    # *sessions* (each its own list, so each is a genuine, distinct
    # disconnect the manager must itself reconnect from) -- previously
    # both exceptions were nested inside a single session's items list,
    # where the first `raise` inside `FakeSubscription.notifications()`'s
    # `for item in self._items` loop meant the second exception was
    # never actually reached at all. That went unnoticed because
    # `calls_for_a >= 3` was, in practice, being reached only via round
    # 4's own defect this round's finding #6 fixes: a receive-timeout
    # unconditionally reconnecting even a quiet-but-healthy idle-forever
    # fallback session, over and over, every stream_receive_timeout_seconds.
    # Now that a timeout alone no longer reconnects a live connection,
    # the test must genuinely script the two disconnects its own
    # docstring always claimed.
    stream.script(WALLET_A, [ConnectionError("dropped")])
    stream.script_liveness(WALLET_A, None, [False])
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
    # Wait for both scripted items to have taken effect -- sig-A observed
    # *and* the reconnect from the ConnectionError that follows it -- not
    # just the first, since the manager reconnecting and re-subscribing
    # is itself independently-scheduled work racing against this poll
    # loop noticing sig-A alone.
    await _run_until(
        stop_event,
        manager,
        lambda: (
            ("sig-A", WALLET_A, "TRANSACTION_OBSERVED") in ledger.rows
            and any(r.reconnect_count > 0 for r in usage.streaming)
        ),
    )

    assert len(usage.streaming) >= 1
    connection_records = [r for r in usage.streaming if r.connection_count > 0]
    assert len(connection_records) >= 1
    byte_records = [r for r in usage.streaming if r.bytes_received]
    assert len(byte_records) >= 1
    reconnect_records = [r for r in usage.streaming if r.reconnect_count > 0]
    assert len(reconnect_records) >= 1


# --- Phase 1 remediation round 3, finding #4: a streaming usage-recorder
# --- failure must be a visible, non-secret operational signal -- never
# --- silently swallowed, and never allowed to corrupt the real stream
# --- outcome or state machine.


class _FailingStreamingUsageRecorder:
    """`record_streaming` always fails; `record_request` is unused by the
    manager and is never expected to be called."""

    async def record_request(self, record: RequestUsageRecord) -> None:
        raise NotImplementedError

    async def record_streaming(self, record: StreamingUsageRecord) -> None:
        raise RuntimeError("streaming usage DB is down")


async def test_streaming_recorder_connection_subscription_failure_is_visible(capsys) -> None:  # noqa: ANN001
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    stream = FakeLiveStream()
    manager = _manager(
        provider,
        stream,
        ledger,
        store,
        (WALLET_A,),
        streaming_usage_recorder=_FailingStreamingUsageRecorder(),
    )

    await manager._record_streaming(WALLET_A, connection_delta=1, subscription_delta=1)

    captured = capsys.readouterr()
    assert "usage_recorder_failed" in captured.out
    assert "streaming usage DB is down" in captured.out
    assert "fake_provider" in captured.out
    assert WALLET_A in captured.out
    assert "connection_delta" in captured.out and "1" in captured.out
    assert "HELIUS_API_KEY" not in captured.out


async def test_streaming_recorder_reconnect_failure_is_visible(capsys) -> None:  # noqa: ANN001
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    stream = FakeLiveStream()
    manager = _manager(
        provider,
        stream,
        ledger,
        store,
        (WALLET_A,),
        streaming_usage_recorder=_FailingStreamingUsageRecorder(),
    )

    await manager._record_streaming(WALLET_A, reconnect_delta=1)

    captured = capsys.readouterr()
    assert "usage_recorder_failed" in captured.out
    assert "streaming usage DB is down" in captured.out
    assert "reconnect_delta" in captured.out


async def test_streaming_recorder_byte_accounting_failure_is_visible(capsys) -> None:  # noqa: ANN001
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    stream = FakeLiveStream()
    manager = _manager(
        provider,
        stream,
        ledger,
        store,
        (WALLET_A,),
        streaming_usage_recorder=_FailingStreamingUsageRecorder(),
    )

    await manager._record_streaming(WALLET_A, bytes_delta=4096)

    captured = capsys.readouterr()
    assert "usage_recorder_failed" in captured.out
    assert "streaming usage DB is down" in captured.out
    assert "bytes_delta" in captured.out and "4096" in captured.out


async def test_streaming_recorder_failure_never_masks_the_real_stream_outcome() -> None:
    """The full manager run must complete exactly as it would with a
    working recorder -- events observed, watermark advanced, reconnect
    handled -- with a permanently-failing streaming usage recorder wired
    in throughout. A recorder failure is an operational-visibility signal,
    never a change to ingestion's real outcome or control flow."""
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
    manager = _manager(
        provider,
        stream,
        ledger,
        store,
        (WALLET_A,),
        streaming_usage_recorder=_FailingStreamingUsageRecorder(),
    )

    stop_event = asyncio.Event()
    await _run_until(
        stop_event, manager, lambda: ("sig-A", WALLET_A, "TRANSACTION_OBSERVED") in ledger.rows
    )

    assert ("sig-A", WALLET_A, "TRANSACTION_OBSERVED") in ledger.rows
    watermark = await store.get(WALLET_A)
    assert watermark is not None


async def test_manager_never_signs_executes_or_broadcasts() -> None:
    """No live-entry/signing/execution/broadcast path exists anywhere on
    IngestionManager -- asserted directly, not just by absence of use."""
    assert not hasattr(IngestionManager, "sign")
    assert not hasattr(IngestionManager, "execute")
    assert not hasattr(IngestionManager, "broadcast")
    assert not hasattr(IngestionManager, "submit_order")


# --- Phase 1 remediation round 2, finding #1: explicit subscription lifecycle


async def test_reconciliation_cannot_restore_ok_before_subscription_is_genuinely_acknowledged() -> (
    None
):
    """The exact defect finding #1 names: a lazy async-generator handshake
    let reconciliation report a wallet OK before any socket existed. Here
    ``open_subscription`` is gated behind a test-controlled event -- while
    it is closed, the manager must not have called ``mark_stream_ready``
    or ``reconcile`` at all (the watermark row doesn't even exist yet);
    only once the gate opens does the real acknowledgement complete, and
    only then can the wallet reach OK."""
    provider = FakeChainProvider()
    provider.add_transaction("sig-A", slot=1, raw_payload=_valid_raw_payload())
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    stream = FakeLiveStream()
    # No session scripted -- the fallback is "idle forever" once
    # acknowledged (an empty scripted session would instead end
    # immediately with StopAsyncIteration, which is a different,
    # unrelated disruptive transition this test isn't about).
    gate = asyncio.Event()
    stream.ack_gates[WALLET_A] = gate

    manager = _manager(provider, stream, ledger, store, (WALLET_A,))
    stop_event = asyncio.Event()
    run_task = asyncio.ensure_future(manager.run(stop_event=stop_event))
    # Snapshotted the instant OK is observed, inside this closure -- not
    # re-read after shutdown: stopping the manager cancels the still-idle
    # wallet task, and cancellation is itself a disruptive transition this
    # manager must (and does) mark DEGRADED before propagating, which is
    # correct shutdown behavior but not what this test is about.
    observed: dict[str, Any] = {}
    try:
        # Give the manager many chances to (wrongly) race ahead while the
        # acknowledgement is still pending.
        for _ in range(50):
            await asyncio.sleep(0)
        assert stream.subscribe_calls == [WALLET_A]  # attempted, but not yet acknowledged
        watermark_before = await store.get(WALLET_A)
        assert watermark_before is None or watermark_before.wallet_live_state != "OK"
        assert ledger.rows == {}  # reconcile() was never reached

        gate.set()  # the real acknowledgement completes now

        async with asyncio.timeout(2.0):
            while True:
                wm = await store.get(WALLET_A)
                if wm is not None and wm.wallet_live_state == "OK":
                    observed["watermark"] = wm
                    break
                await asyncio.sleep(0)
    finally:
        stop_event.set()
        await run_task

    assert observed["watermark"].is_live_entry_eligible() is True


async def test_open_subscription_failure_never_reaches_reconcile() -> None:
    """A failed acknowledgement (finding #1: connect/subscribe/ack all
    failing before a subscription is ever returned) must be caught before
    any reconciliation is attempted for that connection attempt -- proven
    here by a provider with real data available that reconcile() would
    have picked up, which must remain entirely unrecorded through the
    failed attempt."""
    provider = FakeChainProvider()
    provider.add_transaction("sig-A", slot=1, raw_payload=_valid_raw_payload())
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    stream = FakeLiveStream()
    stream.script_ack_failures(WALLET_A, ConnectionError("ack never arrived"))
    # No session scripted after the failure -- the retry succeeds and
    # then idles forever (see the lazy-ack test above for why an empty
    # scripted session would mean something different).
    manager = _manager(provider, stream, ledger, store, (WALLET_A,))

    stop_event = asyncio.Event()
    await _run_until(
        stop_event, manager, lambda: sum(1 for c in stream.subscribe_calls if c == WALLET_A) >= 2
    )

    # The retry's own reconcile() DID run and durably record sig-A -- but
    # only after the failed first attempt, never as a side effect of it.
    watermark = await store.get(WALLET_A)
    assert watermark is not None
    assert ("sig-A", WALLET_A, "TRANSACTION_OBSERVED") in ledger.rows


# --- Phase 1 remediation round 2, finding #3: structured task supervision


async def test_periodic_reconciliation_task_dying_fails_the_whole_manager() -> None:
    """Finding #3: an unhandled exception in ANY supervised background
    task -- here periodic reconciliation -- must terminate the whole
    manager, not be silently swallowed while everything else keeps
    running. Every tracked wallet is marked DEGRADED and
    IngestionManagerFailure propagates."""
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    stream = FakeLiveStream()  # no session scripted -- wallet loop idles healthily throughout

    class _ExplodingEngine:
        def __init__(self, real: ReconciliationEngine) -> None:
            self._real = real
            self.reconcile_calls = 0

        async def reconcile(self, wallet_address: str, trigger: Any) -> Any:
            self.reconcile_calls += 1
            raise RuntimeError("simulated bug inside periodic reconciliation")

        def __getattr__(self, name: str) -> Any:
            return getattr(self._real, name)

    repos = ReconciliationRepos(
        watermark_store=store,
        event_recorder=ledger,
        commitment_store=FakeCommitmentStore(),
        swap_recorder=FakeSwapRecorder(),
        parse_attempt_recorder=InMemoryParseAttemptRecorder(),
        recent_event_source=None,
    )
    real_engine = ReconciliationEngine(
        chain_provider=provider,
        unit_of_work=_FakeUnitOfWork(repos),
        clock=Clock(),
        provider_name="fake_provider",
        parser_version="test_v1",
        parse_identity=TEST_PARSE_IDENTITY,
    )
    exploding_engine = _ExplodingEngine(real_engine)

    manager = IngestionManager(
        wallet_source=StaticWalletSource((WALLET_A,)),
        stream=stream,
        chain_provider=provider,
        reconciliation_engine=exploding_engine,  # type: ignore[arg-type]
        provider_name="fake_provider",
        clock=Clock(),
        config=IngestionManagerConfig(
            reconnect_base_delay_seconds=0.001,
            reconnect_max_delay_seconds=0.005,
            stream_receive_timeout_seconds=3600,
            periodic_reconciliation_interval_seconds=0.01,
            clock_heartbeat_interval_seconds=3600,
        ),
    )

    with pytest.raises(IngestionManagerFailure):
        await manager.run()

    assert exploding_engine.reconcile_calls >= 1


async def test_normal_shutdown_via_stop_event_never_raises() -> None:
    """The counterpart to the above: a clean, operator-requested shutdown
    (stop_event set, no task failure) must remain a distinct, non-error
    return -- never mistaken for the failure path (finding #3)."""
    provider = FakeChainProvider()
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    stream = FakeLiveStream()  # no session scripted -- idles healthily
    manager = _manager(provider, stream, ledger, store, (WALLET_A,))

    stop_event = asyncio.Event()
    run_task = asyncio.ensure_future(manager.run(stop_event=stop_event))
    for _ in range(10):
        await asyncio.sleep(0)
    stop_event.set()
    await run_task  # must not raise


# --- Phase 1 remediation round 2, finding #4: finalization sweep wiring


async def test_finalization_sweep_runs_from_the_manager_real_code_path() -> None:
    """`sweep_finalization` existed on ReconciliationEngine but no
    production loop ever called it (finding #4). Here the manager's own
    background sweep task -- not a direct call to sweep_finalization --
    must be what performs the FINALIZED promotion."""
    import uuid

    from argus.domain.commitment import COMMITMENT_CONFIRMED, COMMITMENT_FINALIZED
    from argus.ingestion.commitment import CommitmentObservationDraft, derive_current_state
    from argus.providers import SignatureStatusInfo
    from tests.unit.test_reconciliation import FakeRecentEventSource

    provider = FakeChainProvider()
    # sweep_finalization() only ever does real work once a wallet has a
    # non-None last_reconciled_signature (its own guard against sweeping
    # before any truth-path reconciliation has ever run) -- the initial
    # PROCESS_RESTART reconcile the manager runs on startup needs at
    # least one real transaction to advance it past None.
    provider.add_transaction("sig-initial", slot=0, raw_payload=_valid_raw_payload())
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    stream = FakeLiveStream()  # no session scripted -- idles healthily throughout

    now = Clock().utc_now()
    event_id = uuid.uuid4()
    commitment_store = FakeCommitmentStore()
    await commitment_store.append(
        CommitmentObservationDraft(
            observation_id=uuid.uuid4(),
            event_id=event_id,
            commitment_level=COMMITMENT_CONFIRMED,
            transaction_succeeded=True,
            observed_at=now,
            provider="fake_provider",
            provider_received_at=now,
            created_at=now,
        )
    )
    provider.signature_statuses["sig-finalizable"] = SignatureStatusInfo(
        signature="sig-finalizable", confirmation_status="finalized", err=None, slot=1
    )
    recent_event_source = FakeRecentEventSource([(event_id, "sig-finalizable")])

    manager = _manager(
        provider,
        stream,
        ledger,
        store,
        (WALLET_A,),
        commitment_store=commitment_store,
        recent_event_source=recent_event_source,
        config=IngestionManagerConfig(
            reconnect_base_delay_seconds=0.001,
            reconnect_max_delay_seconds=0.005,
            stream_receive_timeout_seconds=3600,
            periodic_reconciliation_interval_seconds=3600,
            clock_heartbeat_interval_seconds=3600,
            finalization_sweep_interval_seconds=0.01,
        ),
    )

    async def finalized() -> bool:
        state = derive_current_state(await commitment_store.list_for_event(event_id))
        return state.commitment_level == COMMITMENT_FINALIZED

    stop_event = asyncio.Event()
    run_task = asyncio.ensure_future(manager.run(stop_event=stop_event))
    try:
        async with asyncio.timeout(2.0):
            while not await finalized():
                await asyncio.sleep(0.01)
    finally:
        stop_event.set()
        await run_task

    state = derive_current_state(await commitment_store.list_for_event(event_id))
    assert state.commitment_level == COMMITMENT_FINALIZED
    assert state.transaction_succeeded is True


async def test_finalization_sweep_failure_is_logged_by_the_manager(capsys) -> None:  # noqa: ANN001
    """Phase 1 remediation round 3, finding #6: a failed sweep
    (``sweep_finalization`` returning ``ok=False``) must be a visible,
    logged operational signal from the manager's own real background
    loop, distinguishable from a genuine zero-promotion sweep -- not
    silently discarded like the old bare-``int`` return was."""
    import uuid

    from tests.unit.test_reconciliation import FakeRecentEventSource

    provider = FakeChainProvider()
    provider.add_transaction("sig-initial", slot=0, raw_payload=_valid_raw_payload())
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    stream = FakeLiveStream()

    class _FailingStatusProvider:
        def __getattr__(self, name: str) -> Any:
            return getattr(provider, name)

        async def get_signature_statuses(self, signatures: list[str]) -> Any:
            raise RuntimeError("simulated provider outage")

    failing_provider = _FailingStatusProvider()
    manager = _manager(
        provider,
        stream,
        ledger,
        store,
        (WALLET_A,),
        recent_event_source=FakeRecentEventSource([(uuid.uuid4(), "sig-initial")]),
        config=IngestionManagerConfig(
            reconnect_base_delay_seconds=0.001,
            reconnect_max_delay_seconds=0.005,
            stream_receive_timeout_seconds=3600,
            periodic_reconciliation_interval_seconds=3600,
            clock_heartbeat_interval_seconds=3600,
            finalization_sweep_interval_seconds=0.01,
        ),
    )
    # Only the reconciliation engine's own provider reference needs to
    # fail -- sweep_finalization() is the only caller of
    # get_signature_statuses() in this scenario.
    manager._reconciliation_engine._chain_provider = failing_provider  # type: ignore[attr-defined]

    stop_event = asyncio.Event()
    run_task = asyncio.ensure_future(manager.run(stop_event=stop_event))
    try:
        async with asyncio.timeout(2.0):
            while "finalization_sweep_failed" not in capsys.readouterr().out:
                await asyncio.sleep(0.01)
    finally:
        stop_event.set()
        await run_task


async def test_finalization_sweep_missing_recent_event_source_is_logged_as_misconfiguration(
    capsys,  # noqa: ANN001
) -> None:
    """Phase 1 remediation round 4, finding #8: no ``RecentEventSource``
    wired at all is a misconfiguration, not a clean zero-result sweep --
    the manager's own real background loop must surface it as a visible
    ``finalization_sweep_failed`` warning naming the misconfiguration,
    exactly like any other sweep failure, not silently treat "nothing to
    check" as success."""
    provider = FakeChainProvider()
    provider.add_transaction("sig-initial", slot=0, raw_payload=_valid_raw_payload())
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    stream = FakeLiveStream()

    # _manager() defaults recent_event_source to None -- deliberately not
    # passed here, simulating the exact misconfiguration this finding
    # names.
    manager = _manager(
        provider,
        stream,
        ledger,
        store,
        (WALLET_A,),
        config=IngestionManagerConfig(
            reconnect_base_delay_seconds=0.001,
            reconnect_max_delay_seconds=0.005,
            stream_receive_timeout_seconds=3600,
            periodic_reconciliation_interval_seconds=3600,
            clock_heartbeat_interval_seconds=3600,
            finalization_sweep_interval_seconds=0.01,
        ),
    )

    stop_event = asyncio.Event()
    run_task = asyncio.ensure_future(manager.run(stop_event=stop_event))
    try:
        async with asyncio.timeout(2.0):
            while True:
                out = capsys.readouterr().out
                if "finalization_sweep_failed" in out and "RecentEventSource" in out:
                    break
                await asyncio.sleep(0.01)
    finally:
        stop_event.set()
        await run_task


async def test_finalization_sweep_recovers_after_restart_with_source_wired() -> None:
    """A misconfigured sweep (no RecentEventSource) followed by a
    "restart" (a fresh manager instance, simulating an operator fixing
    the wiring) must promote normally once correctly configured -- the
    misconfiguration must never leave behind state that blocks recovery."""
    from argus.domain.commitment import COMMITMENT_FINALIZED
    from argus.ingestion.commitment import derive_current_state
    from argus.providers import SignatureStatusInfo
    from tests.unit.test_reconciliation import FakeRecentEventSource

    provider = FakeChainProvider()
    provider.add_transaction("sig-initial", slot=0, raw_payload=_valid_raw_payload())
    ledger = FakeEventLedger()
    store = FakeWatermarkStore()
    commitment_store = FakeCommitmentStore()
    fast_config = IngestionManagerConfig(
        reconnect_base_delay_seconds=0.001,
        reconnect_max_delay_seconds=0.005,
        stream_receive_timeout_seconds=3600,
        periodic_reconciliation_interval_seconds=3600,
        clock_heartbeat_interval_seconds=3600,
        finalization_sweep_interval_seconds=0.01,
    )

    misconfigured_manager = _manager(
        provider,
        FakeLiveStream(),
        ledger,
        store,
        (WALLET_A,),
        commitment_store=commitment_store,
        config=fast_config,
    )
    stop_event = asyncio.Event()
    run_task = asyncio.ensure_future(misconfigured_manager.run(stop_event=stop_event))
    try:
        async with asyncio.timeout(2.0):
            while ("sig-initial", WALLET_A, "TRANSACTION_OBSERVED") not in ledger.rows:
                await asyncio.sleep(0.01)
    finally:
        stop_event.set()
        await run_task

    event_id = ledger.rows[("sig-initial", WALLET_A, "TRANSACTION_OBSERVED")].event_id
    provider.signature_statuses["sig-initial"] = SignatureStatusInfo(
        signature="sig-initial", confirmation_status="finalized", err=None, slot=0
    )

    restarted_manager = _manager(
        provider,
        FakeLiveStream(),
        ledger,
        store,
        (WALLET_A,),
        commitment_store=commitment_store,
        recent_event_source=FakeRecentEventSource([(event_id, "sig-initial")]),
        config=fast_config,
    )

    async def finalized() -> bool:
        state = derive_current_state(await commitment_store.list_for_event(event_id))
        return state.commitment_level == COMMITMENT_FINALIZED

    stop_event2 = asyncio.Event()
    run_task2 = asyncio.ensure_future(restarted_manager.run(stop_event=stop_event2))
    try:
        async with asyncio.timeout(2.0):
            while not await finalized():
                await asyncio.sleep(0.01)
    finally:
        stop_event2.set()
        await run_task2

    state = derive_current_state(await commitment_store.list_for_event(event_id))
    assert state.commitment_level == COMMITMENT_FINALIZED

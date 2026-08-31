"""Ingestion orchestration manager (Phase 1 remediation round 1, finding
#1): the continuously-running process that actually composes the
WebSocket stream, truth-path reconciliation, and clock-health monitoring
into live, restart-safe, per-wallet ingestion.

Before this module, ``HeliusWebSocketStream``, ``ReconciliationEngine``,
and ``PersistentClockMonitor`` were each built and tested in isolation,
but nothing actually ran them together: no code opened a live
subscription, detected a real disconnect, and triggered reconciliation as
runtime behavior. ``IngestionManager`` is that composition.

Every dependency is injected (``WalletSource``, ``LiveChainStream``,
``ChainProvider``, ``ReconciliationEngine``, an optional
``PersistentClockMonitor``, an optional streaming ``UsageRecorder``), so
the complete manager is testable end-to-end with fakes and no credential
or live network -- see ``tests/unit/test_ingestion_manager.py``. A fake
connector proves the manager's own orchestration logic; it is never
claimed to be live-provider validation (MASTER_SPEC.md section 108).

Absolute prohibition, unchanged from every other Phase 1 module: nothing
here signs, executes, or broadcasts a transaction, or has any live-entry
path. This module only ever calls ``ChainProvider.get_transaction`` (read)
and ``ReconciliationEngine`` methods.

Phase 1 remediation round 2 (argus-phase-1-remediation-002) fixed two
further findings:

- **Finding #1**: ``_stream_once`` previously constructed an async
  generator and called ``reconcile()`` before the generator's first
  ``__anext__()`` -- in the real Helius adapter, connect/subscribe/ack all
  happened lazily inside that first iteration, so a successful
  reconciliation could report a wallet OK before any socket existed. The
  stream is now opened via :meth:`~argus.providers.LiveChainStream.open_subscription`,
  an eager, real ``async def`` that only returns once connect + subscribe
  + a valid matching acknowledgement have all genuinely happened; only
  then is :meth:`~argus.ingestion.reconciliation.ReconciliationEngine.mark_stream_ready`
  called, and only after *that* does ``reconcile()`` run -- and even then,
  ``reconcile()`` alone still cannot set the wallet OK unless
  ``mark_stream_ready`` already ran (see that method's docstring for the
  three-independent-dimensions design).
- **Finding #3**: ``run()`` previously only awaited ``stop_event``, so an
  unhandled exception (or an unexpected normal return) in a background
  task -- periodic reconciliation, the clock heartbeat, a per-wallet loop
  -- left the manager silently running forever with part of ingestion
  dead. ``run()`` now races every supervised task against the stop
  condition; any child completing first, for any reason, is fatal: every
  tracked wallet is marked DEGRADED, every sibling task is cancelled, and
  :class:`IngestionManagerFailure` propagates to the caller. A clean
  operator-requested shutdown (``stop_event`` set) remains a distinct,
  non-error return.
- **Finding #4**: ``sweep_finalization`` existed on ``ReconciliationEngine``
  but no production loop ever called it -- dead code. A new
  ``_run_finalization_sweep`` background task calls it on a configurable
  cadence for every tracked wallet, using the same supervised-task
  pattern as periodic reconciliation.

Phase 1 remediation round 5, finding #6: ``_stream_once`` previously
treated *every* receive-timeout as fatal (a wallet with no on-chain
activity for one timeout window looked identical to a dropped
connection), reconnecting a perfectly healthy but quiet socket over and
over. A single pending ``__anext__()`` task is now reused across
multiple receive-timeout cycles -- cancelling and re-creating it on every
mere timeout (the previous ``asyncio.wait_for`` pattern) would poison the
underlying async generator, since an unhandled ``CancelledError``
propagating out of a generator's frame closes it -- and a timeout only
triggers reconnection once
:meth:`~argus.providers.StreamSubscription.check_liveness` (a
transport-level ping/pong probe, entirely separate from waiting for a
notification) has confirmed the connection is genuinely dead.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
from collections.abc import Awaitable, Callable
from typing import Protocol

from argus.clock import Clock
from argus.ingestion.clock_monitor import PersistentClockMonitor
from argus.ingestion.reconciliation import ReconciliationEngine, ReconciliationTrigger
from argus.logging import get_logger
from argus.providers import ChainProvider, LiveChainStream, StreamNotification
from argus.providers.usage import StreamingUsageRecord, UsageRecorder

_logger = get_logger(component="argus.ingestion.manager")


class WalletSource(Protocol):
    """The typed repository/config boundary for which wallets to track
    (Phase 1 remediation finding #1). Phase 1 has no wallet-discovery
    system (that is explicitly Phase 1.5+ scope, forbidden here) -- a real
    deployment supplies a static, operator-configured list via
    :class:`StaticWalletSource`; a later phase can swap in a DB-backed
    source without this manager changing at all."""

    async def tracked_wallets(self) -> tuple[str, ...]: ...


class StaticWalletSource:
    def __init__(self, wallets: tuple[str, ...]) -> None:
        self._wallets = wallets

    async def tracked_wallets(self) -> tuple[str, ...]:
        return self._wallets


class IngestionTimeoutError(RuntimeError):
    """No stream notification arrived within the configured receive
    timeout -- a quiet wallet is never treated as evidence of health; this
    is always the trigger for a truth-path reconciliation."""


class IngestionStreamExhaustedError(RuntimeError):
    """The stream's async iterator ended on its own (``StopAsyncIteration``)
    without an explicit error -- still never read as "no new activity" or
    a clean stop; always treated the same as a disconnect."""


class IngestionManagerFailure(RuntimeError):
    """Raised by :meth:`IngestionManager.run` when any supervised
    background task -- a per-wallet loop, periodic reconciliation, the
    finalization sweep, or the clock heartbeat -- terminates unexpectedly
    (an exception, or an unexpected normal return; every supervised loop
    is written to run forever until cancelled) before ``stop_event`` was
    set. Every tracked wallet is marked DEGRADED and every sibling task is
    cancelled before this propagates -- the manager is never left running
    with part of ingestion silently dead (finding #3). A clean,
    operator-requested shutdown via ``stop_event`` never raises this."""


@dataclasses.dataclass(frozen=True, slots=True)
class IngestionManagerConfig:
    reconnect_base_delay_seconds: float = 1.0
    reconnect_max_delay_seconds: float = 30.0
    stream_receive_timeout_seconds: float = 30.0
    # Phase 1 remediation round 5, finding #6: a quiet-but-healthy socket
    # (no on-chain activity for one receive-timeout window) must not be
    # reconnected -- a transport-level ping/pong liveness probe, bounded
    # by this timeout, decides that instead. Kept well under
    # stream_receive_timeout_seconds so a probe cycle never itself
    # becomes the reason a healthy connection looks unresponsive.
    stream_liveness_probe_timeout_seconds: float = 10.0
    periodic_reconciliation_interval_seconds: float = 60.0
    clock_heartbeat_interval_seconds: float = 5.0
    finalization_sweep_interval_seconds: float = 120.0

    def __post_init__(self) -> None:
        if self.reconnect_base_delay_seconds <= 0:
            raise ValueError("reconnect_base_delay_seconds must be positive")
        if self.reconnect_max_delay_seconds < self.reconnect_base_delay_seconds:
            raise ValueError("reconnect_max_delay_seconds must be >= reconnect_base_delay_seconds")
        if self.stream_receive_timeout_seconds <= 0:
            raise ValueError("stream_receive_timeout_seconds must be positive")
        if self.stream_liveness_probe_timeout_seconds <= 0:
            raise ValueError("stream_liveness_probe_timeout_seconds must be positive")
        if self.periodic_reconciliation_interval_seconds <= 0:
            raise ValueError("periodic_reconciliation_interval_seconds must be positive")
        if self.clock_heartbeat_interval_seconds <= 0:
            raise ValueError("clock_heartbeat_interval_seconds must be positive")
        if self.finalization_sweep_interval_seconds <= 0:
            raise ValueError("finalization_sweep_interval_seconds must be positive")


def _backoff_delay(attempt: int, config: IngestionManagerConfig) -> float:
    """Bounded exponential backoff, deterministic given ``attempt`` --
    injectable ``sleep`` lets tests observe the exact schedule without
    real wall-clock delay."""
    return min(
        config.reconnect_base_delay_seconds * (2 ** max(attempt - 1, 0)),
        config.reconnect_max_delay_seconds,
    )


class IngestionManager:
    """Runs one supervised subscription loop per tracked wallet, a
    periodic truth-path reconciliation sweep, a finalization sweep, and
    (if a clock monitor is injected) a clock-health heartbeat --
    concurrently, with per-wallet state kept strictly separate (each
    wallet's loop only ever touches its own watermark via the shared,
    already-safe :class:`~argus.ingestion.reconciliation.ReconciliationEngine`,
    never another wallet's), and all of it under structured supervision
    (finding #3): see :meth:`run`."""

    def __init__(
        self,
        *,
        wallet_source: WalletSource,
        stream: LiveChainStream,
        chain_provider: ChainProvider,
        reconciliation_engine: ReconciliationEngine,
        provider_name: str,
        clock: Clock,
        clock_monitor: PersistentClockMonitor | None = None,
        streaming_usage_recorder: UsageRecorder | None = None,
        config: IngestionManagerConfig | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._wallet_source = wallet_source
        self._stream = stream
        self._chain_provider = chain_provider
        self._reconciliation_engine = reconciliation_engine
        self._provider_name = provider_name
        self._clock = clock
        self._clock_monitor = clock_monitor
        self._streaming_usage_recorder = streaming_usage_recorder
        self._config = config or IngestionManagerConfig()
        self._sleep = sleep

    async def run(self, *, stop_event: asyncio.Event | None = None) -> None:
        """Runs until ``stop_event`` is set (or this coroutine's own task
        is cancelled). Restart-safe: every wallet's first connection uses
        ``ReconciliationTrigger.PROCESS_RESTART`` so a fresh process always
        catches up from its last durably-persisted watermark, never from
        assumed-clean state.

        Structured supervision (finding #3): every background task is
        raced against the stop condition. If ``stop_event`` is set first,
        this is a clean shutdown -- every task is cancelled and awaited,
        and ``run()`` returns normally. If any task instead completes on
        its own first (whether by raising or by an unexpected normal
        return -- no supervised loop below is ever meant to return except
        via cancellation), that is always fatal: every tracked wallet is
        marked DEGRADED, every task is cancelled, and
        :class:`IngestionManagerFailure` is raised. The stop condition is
        checked directly (``stop_event.is_set()``), not by asking whether
        the stop-waiter task object happened to be reported ``done`` --
        avoiding a race where a wallet loop's own stop-event check and the
        waiter task complete in the same tick but ``asyncio.wait`` only
        surfaces one of them.
        """
        stop_event = stop_event or asyncio.Event()
        wallets = await self._wallet_source.tracked_wallets()

        named_tasks: dict[str, asyncio.Task[None]] = {
            f"wallet:{w}": asyncio.ensure_future(self._run_wallet(w, stop_event)) for w in wallets
        }
        if wallets:
            named_tasks["periodic_reconciliation"] = asyncio.ensure_future(
                self._run_periodic_reconciliation(wallets, stop_event)
            )
            named_tasks["finalization_sweep"] = asyncio.ensure_future(
                self._run_finalization_sweep(wallets, stop_event)
            )
        if self._clock_monitor is not None:
            named_tasks["clock_heartbeat"] = asyncio.ensure_future(
                self._run_clock_heartbeat(wallets, stop_event)
            )

        if not named_tasks:
            return

        stop_waiter = asyncio.ensure_future(stop_event.wait())
        try:
            await asyncio.wait(
                [stop_waiter, *named_tasks.values()], return_when=asyncio.FIRST_COMPLETED
            )
            if not stop_event.is_set():
                failed_name, failed_task = next(
                    (name, t) for name, t in named_tasks.items() if t.done()
                )
                exc = failed_task.exception() if not failed_task.cancelled() else None
                for wallet_address in wallets:
                    await self._reconciliation_engine.mark_degraded(
                        wallet_address,
                        reason=f"ingestion manager task {failed_name!r} terminated unexpectedly",
                    )
                raise IngestionManagerFailure(
                    f"ingestion manager task {failed_name!r} terminated unexpectedly "
                    "before shutdown was requested"
                ) from exc
        finally:
            stop_waiter.cancel()
            for task in named_tasks.values():
                task.cancel()
            await asyncio.gather(stop_waiter, *named_tasks.values(), return_exceptions=True)

    async def _run_wallet(self, wallet_address: str, stop_event: asyncio.Event) -> None:
        attempt = 0
        trigger: ReconciliationTrigger = ReconciliationTrigger.PROCESS_RESTART
        while not stop_event.is_set():
            try:
                await self._stream_once(wallet_address, stop_event, startup_trigger=trigger)
                return  # _stream_once only returns normally on a graceful stop_event
            except asyncio.CancelledError:
                # Cancellation is itself one of the transitions this
                # manager must never treat as "healthy" -- mark DEGRADED
                # before propagating, exactly like every other disruptive
                # transition, then let the cancellation continue upward
                # unmasked.
                await self._reconciliation_engine.mark_degraded(
                    wallet_address, reason="ingestion task cancelled"
                )
                raise
            except Exception as exc:  # noqa: BLE001 - every failure mode converges here deliberately
                # Marked DEGRADED *before* the reconnect attempt below --
                # never left looking OK while recovery is still pending.
                # Covers disconnect, timeout, malformed message,
                # subscription failure, and open_subscription itself
                # failing (finding #1: the stream dimension clears before
                # any recovery attempt begins).
                await self._reconciliation_engine.mark_degraded(
                    wallet_address, reason=f"{type(exc).__name__}: {exc}"
                )
                attempt += 1
                await self._record_streaming(wallet_address, reconnect_delta=1)
                await self._sleep(_backoff_delay(attempt, self._config))
                trigger = ReconciliationTrigger.RECONNECT

    async def _stream_once(
        self,
        wallet_address: str,
        stop_event: asyncio.Event,
        *,
        startup_trigger: ReconciliationTrigger,
    ) -> None:
        # Eager: only returns once connect + subscribe-request-sent + a
        # valid matching acknowledgement have all genuinely happened
        # (finding #1) -- raises otherwise, caught by _run_wallet's
        # except block above exactly like any other disruptive
        # transition, never silently treated as a stream that's "ready".
        subscription = await self._stream.open_subscription(wallet_address)
        # Phase 1 remediation round 5, finding #6: this single pending
        # __anext__() task is reused across multiple receive-timeout/
        # liveness-probe cycles below, rather than being re-created (and
        # the old one cancelled) on every timeout. `asyncio.wait_for`
        # cancelling a pending `__anext__()` on a mere timeout would
        # poison the underlying async generator -- an unhandled
        # CancelledError propagating out of a generator's frame closes
        # it, so the *next* `__anext__()` call would raise
        # StopAsyncIteration immediately instead of genuinely resuming,
        # silently misreading "still quiet" as "the stream ended". This
        # task is only ever cancelled once check_liveness has confirmed
        # the connection is genuinely dead, or in the `finally` cleanup
        # below.
        notif_task: asyncio.Task[StreamNotification] | None = None
        try:
            await self._record_streaming(wallet_address, connection_delta=1, subscription_delta=1)

            # Only now -- after a real acknowledgement -- does the stream
            # dimension become ready. This alone still cannot make the
            # wallet look OK; see mark_stream_ready's docstring.
            await self._reconciliation_engine.mark_stream_ready(wallet_address)

            # Recovery requires reconnection + a complete, successful
            # reconciliation + (via ReconciliationEngine's own
            # clock_monitor check) a healthy clock -- all three, not just
            # "the socket is open again". This is that reconciliation
            # call, run immediately after the stream is genuinely ready,
            # before any notification is processed.
            await self._reconciliation_engine.reconcile(wallet_address, startup_trigger)

            iterator = subscription.notifications().__aiter__()
            while not stop_event.is_set():
                if notif_task is None:
                    notif_task = asyncio.ensure_future(iterator.__anext__())
                done, _pending = await asyncio.wait(
                    {notif_task}, timeout=self._config.stream_receive_timeout_seconds
                )
                if notif_task not in done:
                    # Quiet, not necessarily dead: a wallet with no
                    # on-chain activity for one receive-timeout window is
                    # indistinguishable from a dropped connection by
                    # silence alone. Probe liveness at the transport
                    # level instead of reconnecting on every timeout.
                    alive = await subscription.check_liveness(
                        timeout_seconds=self._config.stream_liveness_probe_timeout_seconds
                    )
                    if alive:
                        continue  # still connected -- keep waiting on the same pending task
                    task = notif_task
                    notif_task = None
                    task.cancel()
                    with contextlib.suppress(BaseException):
                        await task
                    raise IngestionTimeoutError(
                        f"no stream notification for {wallet_address} within "
                        f"{self._config.stream_receive_timeout_seconds}s and the connection "
                        "failed a liveness check"
                    )

                task = notif_task
                notif_task = None
                try:
                    notification = task.result()
                except StopAsyncIteration as exc:
                    raise IngestionStreamExhaustedError(
                        f"stream for {wallet_address} ended without an explicit error"
                    ) from exc

                raw_payload = await self._chain_provider.get_transaction(notification.signature)
                await self._reconciliation_engine.observe_stream_event(notification, raw_payload)
                await self._record_streaming(
                    wallet_address,
                    bytes_delta=len(json.dumps(raw_payload, default=str).encode("utf-8")),
                )
        finally:
            if notif_task is not None and not notif_task.done():
                notif_task.cancel()
                with contextlib.suppress(BaseException):
                    await notif_task
            await subscription.close()

    async def _run_periodic_reconciliation(
        self, wallets: tuple[str, ...], stop_event: asyncio.Event
    ) -> None:
        while not stop_event.is_set():
            await self._sleep(self._config.periodic_reconciliation_interval_seconds)
            if stop_event.is_set():
                return
            for wallet_address in wallets:
                await self._reconciliation_engine.reconcile(
                    wallet_address, ReconciliationTrigger.SCHEDULED
                )

    async def _run_finalization_sweep(
        self, wallets: tuple[str, ...], stop_event: asyncio.Event
    ) -> None:
        """Finding #4's real runtime path for FINALIZED promotion --
        ``ReconciliationEngine.sweep_finalization`` existed and was
        tested in isolation, but no production loop ever called it.

        Finding #6 (round 3): a failed sweep (``result.ok is False`` --
        the provider check itself could not be completed, distinct from a
        genuine zero-promotion sweep) is a visible, logged operational
        signal, never silently discarded. This loop never crashes the
        manager over a single wallet's failed sweep -- exactly like
        periodic reconciliation, a soft per-cycle failure is retried next
        cycle, not fatal to the whole process -- and never uses the
        result to touch wallet health in any way (sweep_finalization
        itself already never does)."""
        while not stop_event.is_set():
            await self._sleep(self._config.finalization_sweep_interval_seconds)
            if stop_event.is_set():
                return
            for wallet_address in wallets:
                result = await self._reconciliation_engine.sweep_finalization(wallet_address)
                if not result.ok:
                    _logger.warning(
                        "finalization_sweep_failed",
                        provider=self._provider_name,
                        wallet_address=wallet_address,
                        promoted=result.promoted,
                        reason=result.reason,
                    )

    async def _run_clock_heartbeat(
        self, wallets: tuple[str, ...], stop_event: asyncio.Event
    ) -> None:
        assert self._clock_monitor is not None
        was_anomalous = self._clock_monitor.anomaly_detected
        while not stop_event.is_set():
            await self._clock_monitor.tick()
            is_anomalous = self._clock_monitor.anomaly_detected
            if is_anomalous and not was_anomalous:
                # A clock anomaly is process-global, not per-wallet: every
                # tracked wallet must be forced DEGRADED and re-checked,
                # not just whichever wallet's stream happens to notice
                # next.
                for wallet_address in wallets:
                    await self._reconciliation_engine.mark_degraded(
                        wallet_address, reason="clock anomaly detected"
                    )
                    await self._reconciliation_engine.reconcile(
                        wallet_address, ReconciliationTrigger.CLOCK_ANOMALY
                    )
            was_anomalous = is_anomalous
            await self._sleep(self._config.clock_heartbeat_interval_seconds)

    async def _record_streaming(
        self,
        wallet_address: str,
        *,
        connection_delta: int = 0,
        subscription_delta: int = 0,
        reconnect_delta: int = 0,
        bytes_delta: int = 0,
    ) -> None:
        if self._streaming_usage_recorder is None:
            return
        # Usage accounting must never mask a real ingestion outcome --
        # same policy as argus.providers.http.send_with_usage. Phase 1
        # remediation round 3, finding #4: a recorder failure used to be
        # swallowed by contextlib.suppress(Exception) with no signal
        # whatsoever -- not even a log line -- so an operator had no way to
        # know streaming usage accounting had silently stopped working.
        # This now emits the same structured `usage_recorder_failed`
        # warning argus.providers.http._record_best_effort emits for the
        # HTTP path: safe metadata only (provider/endpoint/request_class/
        # the delta shape actually attempted/error class+message), no
        # wallet-secret or credential material, and never anything that
        # replaces or masks the real stream outcome this call is
        # accounting for -- the caller's control flow is untouched either
        # way.
        try:
            await self._streaming_usage_recorder.record_streaming(
                StreamingUsageRecord(
                    provider=self._provider_name,
                    endpoint=f"subscribe_wallet:{wallet_address}",
                    request_class="stream",
                    requested_at=self._clock.utc_now(),
                    connection_count=connection_delta,
                    subscription_count=subscription_delta,
                    reconnect_count=reconnect_delta,
                    bytes_received=bytes_delta or None,
                    estimated_streaming_credits=None,
                )
            )
        except Exception as exc:  # noqa: BLE001 - deliberately never re-raised
            _logger.warning(
                "usage_recorder_failed",
                provider=self._provider_name,
                wallet_address=wallet_address,
                request_class="stream",
                connection_delta=connection_delta,
                subscription_delta=subscription_delta,
                reconnect_delta=reconnect_delta,
                bytes_delta=bytes_delta,
                error_class=type(exc).__name__,
                error=str(exc),
            )

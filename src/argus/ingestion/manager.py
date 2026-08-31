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
from argus.providers import ChainProvider, LiveChainStream
from argus.providers.usage import StreamingUsageRecord, UsageRecorder


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


@dataclasses.dataclass(frozen=True, slots=True)
class IngestionManagerConfig:
    reconnect_base_delay_seconds: float = 1.0
    reconnect_max_delay_seconds: float = 30.0
    stream_receive_timeout_seconds: float = 30.0
    periodic_reconciliation_interval_seconds: float = 60.0
    clock_heartbeat_interval_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.reconnect_base_delay_seconds <= 0:
            raise ValueError("reconnect_base_delay_seconds must be positive")
        if self.reconnect_max_delay_seconds < self.reconnect_base_delay_seconds:
            raise ValueError("reconnect_max_delay_seconds must be >= reconnect_base_delay_seconds")
        if self.stream_receive_timeout_seconds <= 0:
            raise ValueError("stream_receive_timeout_seconds must be positive")
        if self.periodic_reconciliation_interval_seconds <= 0:
            raise ValueError("periodic_reconciliation_interval_seconds must be positive")
        if self.clock_heartbeat_interval_seconds <= 0:
            raise ValueError("clock_heartbeat_interval_seconds must be positive")


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
    periodic truth-path reconciliation sweep, and (if a clock monitor is
    injected) a clock-health heartbeat -- concurrently, with per-wallet
    state kept strictly separate (each wallet's loop only ever touches its
    own watermark via the shared, already-safe
    :class:`~argus.ingestion.reconciliation.ReconciliationEngine`, never
    another wallet's)."""

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
        assumed-clean state."""
        stop_event = stop_event or asyncio.Event()
        wallets = await self._wallet_source.tracked_wallets()

        tasks = [asyncio.ensure_future(self._run_wallet(w, stop_event)) for w in wallets]
        if wallets:
            tasks.append(
                asyncio.ensure_future(self._run_periodic_reconciliation(wallets, stop_event))
            )
        if self._clock_monitor is not None:
            tasks.append(asyncio.ensure_future(self._run_clock_heartbeat(wallets, stop_event)))

        if not tasks:
            return
        try:
            await stop_event.wait()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

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
        iterator = self._stream.subscribe_wallet(wallet_address).__aiter__()
        await self._record_streaming(wallet_address, connection_delta=1, subscription_delta=1)

        # Recovery requires reconnection + a complete, successful
        # reconciliation + (via ReconciliationEngine's own clock_monitor
        # check) a healthy clock -- all three, not just "the socket is
        # open again". This is that reconciliation call, run immediately
        # after a fresh subscription is established, before any
        # notification is processed.
        await self._reconciliation_engine.reconcile(wallet_address, startup_trigger)

        while not stop_event.is_set():
            try:
                notification = await asyncio.wait_for(
                    iterator.__anext__(), timeout=self._config.stream_receive_timeout_seconds
                )
            except TimeoutError as exc:
                raise IngestionTimeoutError(
                    f"no stream notification for {wallet_address} within "
                    f"{self._config.stream_receive_timeout_seconds}s"
                ) from exc
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
        # same policy as argus.providers.http.send_with_usage.
        with contextlib.suppress(Exception):
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

"""Fast-path (WebSocket) + truth-path (RPC reconciliation) event ingestion.

MASTER_SPEC.md section 19 (LIVE CHAIN OBSERVATION: FAST PATH + TRUTH PATH):
"WebSocket receipt alone is never treated as proof of complete
observation." Every tracked wallet has both an immediate fast-path
observation (:meth:`ReconciliationEngine.observe_stream_event`) and a
periodic/triggered truth-path reconciliation
(:meth:`ReconciliationEngine.reconcile`) that authoritatively re-derives
what actually happened from the provider's own transaction history.

This module is written entirely against protocols
(:mod:`argus.providers`, :class:`WatermarkStore`, :class:`EventRecorder`)
so it never depends on a real database or a real chain provider -- a fake
implementation of each is a first-class way to exercise the mandatory
deterministic scenario in MASTER_SPEC.md section 19:

    stream connects -> event A observed -> disconnect -> event B occurs
    while disconnected -> reconnect -> reconciliation discovers B

with the final canonical ledger containing A exactly once and B exactly
once, including across process restart and duplicate-delivery variants
(see tests/unit/test_reconciliation.py).
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Protocol

from argus.clock import Clock
from argus.ingestion.clock_monitor import PersistentClockMonitor
from argus.providers import ChainProvider, StreamNotification

EVENT_TYPE_TRANSACTION_OBSERVED = "TRANSACTION_OBSERVED"

STREAM_HEALTH_OK = "OK"
STREAM_HEALTH_DEGRADED = "DEGRADED"

WALLET_LIVE_STATE_OK = "OK"
WALLET_LIVE_STATE_DEGRADED = "DEGRADED"


class ReconciliationTrigger(enum.StrEnum):
    """Every condition MASTER_SPEC.md section 19 requires to trigger
    truth-path reconciliation."""

    DISCONNECT = "DISCONNECT"
    RECONNECT = "RECONNECT"
    PROCESS_RESTART = "PROCESS_RESTART"
    TIMEOUT = "TIMEOUT"
    SUBSCRIPTION_FAILURE = "SUBSCRIPTION_FAILURE"
    CLOCK_ANOMALY = "CLOCK_ANOMALY"
    HOST_RESUME = "HOST_RESUME"
    SCHEDULED = "SCHEDULED"


@dataclasses.dataclass(frozen=True, slots=True)
class ChainEventDraft:
    """Provider-agnostic draft of one ``chain_events`` row. Decoupled from
    the SQLAlchemy model so reconciliation logic never depends on a
    database being present."""

    event_id: uuid.UUID
    chain: str
    slot: int
    block_time: datetime | None
    first_seen_at: datetime
    confirmed_at: datetime | None
    finalized_at: datetime | None
    provider: str
    provider_received_at: datetime
    transaction_signature: str
    event_type: str
    wallet_address: str | None
    mint: str | None
    raw_payload: dict[str, Any]
    payload_hash: str
    parser_version: str
    created_at: datetime


class EventRecorder(Protocol):
    """Persists a :class:`ChainEventDraft`, deduplicated on
    ``(transaction_signature, wallet_address, event_type)``.

    Must return ``True`` only when this call actually created a new row --
    ``False`` when the event already existed (e.g. the DB unique
    constraint rejected it, or an in-memory fake already had it). This is
    what makes "A and B each canonicalize exactly once" independently
    verifiable regardless of which path (fast or truth) observed them
    first.
    """

    async def record(self, draft: ChainEventDraft) -> bool: ...


@dataclasses.dataclass(frozen=True, slots=True)
class WalletWatermark:
    wallet_address: str
    last_stream_signature: str | None = None
    last_stream_slot: int | None = None
    last_reconciled_signature: str | None = None
    last_reconciled_slot: int | None = None
    last_reconciliation_at: datetime | None = None
    stream_health: str = "UNKNOWN"
    wallet_live_state: str = WALLET_LIVE_STATE_OK
    updated_at: datetime | None = None

    def is_live_entry_eligible(self) -> bool:
        return self.wallet_live_state == WALLET_LIVE_STATE_OK


class WatermarkStore(Protocol):
    """Persistent per-wallet watermark storage. A real implementation
    backs onto ``wallet_stream_state``; a fake for tests must be
    constructible fresh from a plain snapshot to simulate a process
    restart correctly reloading persisted state."""

    async def get(self, wallet_address: str) -> WalletWatermark | None: ...
    async def save(self, watermark: WalletWatermark) -> None: ...


@dataclasses.dataclass(frozen=True, slots=True)
class ReconciliationResult:
    ok: bool
    trigger: ReconciliationTrigger
    new_events: int
    reason: str = ""


def _payload_hash(raw_payload: dict[str, Any]) -> str:
    canonical = json.dumps(raw_payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class ReconciliationEngine:
    def __init__(
        self,
        *,
        chain_provider: ChainProvider,
        watermark_store: WatermarkStore,
        event_recorder: EventRecorder,
        clock: Clock,
        provider_name: str,
        parser_version: str,
        clock_monitor: PersistentClockMonitor | None = None,
    ) -> None:
        self._chain_provider = chain_provider
        self._watermark_store = watermark_store
        self._event_recorder = event_recorder
        self._clock = clock
        self._provider_name = provider_name
        self._parser_version = parser_version
        self._clock_monitor = clock_monitor

    async def _get_or_init(self, wallet_address: str) -> WalletWatermark:
        existing = await self._watermark_store.get(wallet_address)
        if existing is not None:
            return existing
        return WalletWatermark(wallet_address=wallet_address)

    async def observe_stream_event(
        self, notification: StreamNotification, raw_payload: dict[str, Any]
    ) -> bool:
        """Fast path: record the observation immediately. Never alone
        treated as confirmed truth (``confirmed_at`` stays unset here --
        only :meth:`reconcile` sets it, since a WebSocket receipt is not
        proof of complete observation per section 19)."""
        now = self._clock.utc_now()
        draft = ChainEventDraft(
            event_id=uuid.uuid4(),
            chain="solana",
            slot=notification.slot,
            block_time=None,
            first_seen_at=now,
            confirmed_at=None,
            finalized_at=None,
            provider=self._provider_name,
            provider_received_at=now,
            transaction_signature=notification.signature,
            event_type=EVENT_TYPE_TRANSACTION_OBSERVED,
            wallet_address=notification.wallet_address,
            mint=None,
            raw_payload=raw_payload,
            payload_hash=_payload_hash(raw_payload),
            parser_version=self._parser_version,
            created_at=now,
        )
        added = await self._event_recorder.record(draft)

        watermark = await self._get_or_init(notification.wallet_address)
        watermark = dataclasses.replace(
            watermark,
            last_stream_signature=notification.signature,
            last_stream_slot=notification.slot,
            updated_at=now,
        )
        await self._watermark_store.save(watermark)
        return added

    async def reconcile(
        self, wallet_address: str, trigger: ReconciliationTrigger
    ) -> ReconciliationResult:
        """Truth path. Fetches every signature newer than
        ``last_reconciled_signature`` from the provider's own history,
        fetches and canonicalizes each transaction, and relies on
        :class:`EventRecorder`'s dedup to guarantee exactly-once
        canonicalization regardless of whether the fast path already saw
        some of them.

        Any provider failure (the "unresolved" case in section 19) marks
        the wallet ``DEGRADED`` rather than silently leaving the previous
        state in place -- a DEGRADED wallet must never look live-entry
        eligible just because nobody got around to re-checking it.
        """
        now = self._clock.utc_now()
        watermark = await self._get_or_init(wallet_address)

        try:
            signatures = await self._chain_provider.get_signatures_for_address(
                wallet_address, until_signature=watermark.last_reconciled_signature
            )
        except Exception as exc:
            degraded = dataclasses.replace(
                watermark,
                wallet_live_state=WALLET_LIVE_STATE_DEGRADED,
                stream_health=STREAM_HEALTH_DEGRADED,
                updated_at=now,
            )
            await self._watermark_store.save(degraded)
            return ReconciliationResult(
                ok=False, trigger=trigger, new_events=0, reason=f"{type(exc).__name__}: {exc}"
            )

        new_events = 0
        latest_signature = watermark.last_reconciled_signature
        latest_slot = watermark.last_reconciled_slot

        # Provider returns newest-first; process oldest-first for a
        # deterministic, causally-ordered ledger.
        for sig_info in reversed(signatures):
            try:
                raw_payload = await self._chain_provider.get_transaction(sig_info.signature)
            except Exception as exc:
                degraded = dataclasses.replace(
                    watermark,
                    last_reconciled_signature=latest_signature,
                    last_reconciled_slot=latest_slot,
                    wallet_live_state=WALLET_LIVE_STATE_DEGRADED,
                    stream_health=STREAM_HEALTH_DEGRADED,
                    updated_at=now,
                )
                await self._watermark_store.save(degraded)
                return ReconciliationResult(
                    ok=False,
                    trigger=trigger,
                    new_events=new_events,
                    reason=f"{type(exc).__name__}: {exc}",
                )

            draft = ChainEventDraft(
                event_id=uuid.uuid4(),
                chain="solana",
                slot=sig_info.slot,
                block_time=sig_info.block_time,
                first_seen_at=now,
                confirmed_at=now if sig_info.err is None else None,
                finalized_at=None,
                provider=self._provider_name,
                provider_received_at=now,
                transaction_signature=sig_info.signature,
                event_type=EVENT_TYPE_TRANSACTION_OBSERVED,
                wallet_address=wallet_address,
                mint=None,
                raw_payload=raw_payload,
                payload_hash=_payload_hash(raw_payload),
                parser_version=self._parser_version,
                created_at=now,
            )
            added = await self._event_recorder.record(draft)
            if added:
                new_events += 1
            latest_signature = sig_info.signature
            latest_slot = sig_info.slot

        # A clock anomaly is a separate, additional gate on live-entry
        # eligibility from reconciliation success (section 17): provider
        # reconnection + chain reconciliation + clock health recovery are
        # all independently required, so an unresolved clock anomaly keeps
        # the wallet DEGRADED here even though this reconciliation itself
        # succeeded.
        clock_anomaly = self._clock_monitor is not None and self._clock_monitor.anomaly_detected
        resolved = dataclasses.replace(
            watermark,
            last_reconciled_signature=latest_signature,
            last_reconciled_slot=latest_slot,
            last_reconciliation_at=now,
            wallet_live_state=WALLET_LIVE_STATE_DEGRADED if clock_anomaly else WALLET_LIVE_STATE_OK,
            stream_health=STREAM_HEALTH_DEGRADED if clock_anomaly else STREAM_HEALTH_OK,
            updated_at=now,
        )
        await self._watermark_store.save(resolved)
        reason = "unresolved clock anomaly blocks live-entry eligibility" if clock_anomaly else ""
        return ReconciliationResult(ok=True, trigger=trigger, new_events=new_events, reason=reason)

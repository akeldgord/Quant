"""Fast-path (WebSocket) + truth-path (RPC reconciliation) event ingestion.

MASTER_SPEC.md section 19 (LIVE CHAIN OBSERVATION: FAST PATH + TRUTH PATH):
"WebSocket receipt alone is never treated as proof of complete
observation." Every tracked wallet has both an immediate fast-path
observation (:meth:`ReconciliationEngine.observe_stream_event`) and a
periodic/triggered truth-path reconciliation
(:meth:`ReconciliationEngine.reconcile`) that authoritatively re-derives
what actually happened from the provider's own transaction history.

This module is written entirely against protocols
(:mod:`argus.providers`, :class:`WatermarkStore`, :class:`EventRecorder`,
:class:`argus.ingestion.commitment.CommitmentObservationStore`,
:class:`SwapRecorder`) so it never depends on a real database or a real
chain provider -- a fake implementation of each is a first-class way to
exercise the mandatory deterministic scenario in MASTER_SPEC.md section 19:

    stream connects -> event A observed -> disconnect -> event B occurs
    while disconnected -> reconnect -> reconciliation discovers B

with the final canonical ledger containing A exactly once and B exactly
once, including across process restart and duplicate-delivery variants
(see tests/unit/test_reconciliation.py).

Phase 1 remediation round 1 (argus-phase-1-remediation-001) rewrote
``reconcile()`` to: (finding #2) fully paginate a truth-path gap larger
than one page instead of silently truncating it and skipping the older
half; (finding #3) record commitment progression as append-only
observations instead of a mutable column a dedup constraint always
blocked from ever being set; (finding #4) parse each fetched transaction
and persist its derived, versioned classification linked to the canonical
event, instead of leaving ``swaps`` write-side dead code.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Protocol

from argus.clock import Clock
from argus.domain.commitment import COMMITMENT_CONFIRMED, COMMITMENT_FINALIZED, COMMITMENT_PROCESSED
from argus.ingestion.clock_monitor import PersistentClockMonitor
from argus.ingestion.commitment import CommitmentObservationStore, CommitmentTracker
from argus.parsing.generic_parser import ParsedTransaction, parse_transaction
from argus.providers import ChainProvider, SignatureInfo, StreamNotification

EVENT_TYPE_TRANSACTION_OBSERVED = "TRANSACTION_OBSERVED"

STREAM_HEALTH_OK = "OK"
STREAM_HEALTH_DEGRADED = "DEGRADED"

WALLET_LIVE_STATE_OK = "OK"
WALLET_LIVE_STATE_DEGRADED = "DEGRADED"

DEFAULT_PAGE_SIZE = 1000
DEFAULT_MAX_PAGES = 50


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


@dataclasses.dataclass(frozen=True, slots=True)
class RecordOutcome:
    """The *authoritative* ``event_id`` for this natural key -- ``draft``'s
    own freshly-generated ``event_id`` when ``is_new`` is ``True``, or the
    real, already-stored row's ``event_id`` when it is ``False``. Callers
    that link further evidence (commitment observations, parsed swaps) to
    an event must always use ``event_id`` from this result, never
    ``draft.event_id`` directly -- on a duplicate, ``draft.event_id`` was
    never actually persisted, and linking to it would violate the
    downstream foreign key (or silently orphan the linked row) instead of
    landing on the real event."""

    event_id: uuid.UUID
    is_new: bool


class EventRecorder(Protocol):
    """Persists a :class:`ChainEventDraft`, deduplicated on
    ``(transaction_signature, wallet_address, event_type)``.

    Returns the authoritative :class:`RecordOutcome` for this natural key
    -- see its docstring for why ``event_id`` there (not
    ``draft.event_id``) is what callers must use. This is what makes "A
    and B each canonicalize exactly once" independently verifiable
    regardless of which path (fast or truth) observed them first, while
    still letting later observations (commitment progression, parsed
    output) attach to the one real row.
    """

    async def record(self, draft: ChainEventDraft) -> RecordOutcome: ...


class RecentEventSource(Protocol):
    """Read-side capability :meth:`ReconciliationEngine.sweep_finalization`
    needs and none of the write-oriented protocols above provide: which
    ``(event_id, signature)`` pairs for a wallet are recent enough to be
    worth re-checking for a FINALIZED promotion. A real implementation
    queries ``chain_events`` directly (see
    ``argus.ingestion.event_repository.SqlEventRecorder.recent_signatures``);
    a fake for tests is a plain in-memory list."""

    async def recent_signatures(
        self, wallet_address: str, *, limit: int
    ) -> list[tuple[uuid.UUID, str]]: ...


class SwapRecorder(Protocol):
    """Persists one parsed, versioned classification linked to a canonical
    ``chain_events`` row. Deduplicated on ``(event_id, parser_version)``:
    re-running the same parser version is idempotent; a new parser version
    may add an additional row without touching a prior one. Returns
    ``True`` only when this call actually created a new row."""

    async def record(
        self,
        *,
        event_id: uuid.UUID,
        wallet_address: str,
        parsed: ParsedTransaction,
        created_at: datetime,
    ) -> bool: ...


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
    parser_failures: int = 0
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
        commitment_store: CommitmentObservationStore,
        swap_recorder: SwapRecorder,
        clock_monitor: PersistentClockMonitor | None = None,
        recent_event_source: RecentEventSource | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = DEFAULT_MAX_PAGES,
        commit_hook: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        if max_pages <= 0:
            raise ValueError("max_pages must be positive")
        self._chain_provider = chain_provider
        self._watermark_store = watermark_store
        self._event_recorder = event_recorder
        self._clock = clock
        self._provider_name = provider_name
        self._parser_version = parser_version
        self._commitment_tracker = CommitmentTracker(commitment_store)
        self._swap_recorder = swap_recorder
        self._clock_monitor = clock_monitor
        self._recent_event_source = recent_event_source
        self._page_size = page_size
        self._max_pages = max_pages
        # A no-op default keeps every existing in-memory-fake test working
        # unchanged; real SQL callers pass `session.commit` so partial
        # progress across a multi-page reconciliation survives a crash
        # (finding #2: "persist partial progress transactionally so a
        # crash resumes without loss").
        self._commit_hook = commit_hook or self._noop_commit

    @staticmethod
    async def _noop_commit() -> None:
        return None

    async def _get_or_init(self, wallet_address: str) -> WalletWatermark:
        existing = await self._watermark_store.get(wallet_address)
        if existing is not None:
            return existing
        return WalletWatermark(wallet_address=wallet_address)

    async def _mark_degraded(
        self, watermark: WalletWatermark, *, now: datetime, **overrides: Any
    ) -> None:
        degraded = dataclasses.replace(
            watermark,
            wallet_live_state=WALLET_LIVE_STATE_DEGRADED,
            stream_health=STREAM_HEALTH_DEGRADED,
            updated_at=now,
            **overrides,
        )
        await self._watermark_store.save(degraded)
        await self._commit_hook()

    async def mark_degraded(self, wallet_address: str, *, reason: str = "") -> None:
        """Public entry point for a caller (the ingestion manager) that
        has *itself* detected a disruptive transition -- a stream
        disconnect, timeout, malformed message, subscription failure, or
        cancellation -- and must mark the wallet DEGRADED immediately,
        before attempting any recovery, not only after a (possibly slow)
        :meth:`reconcile` call resolves. Idempotent: calling this on an
        already-DEGRADED wallet is a harmless no-op re-save."""
        del reason  # not persisted as a column today; kept for caller-side logging/testing clarity
        watermark = await self._get_or_init(wallet_address)
        await self._mark_degraded(watermark, now=self._clock.utc_now())

    async def observe_stream_event(
        self, notification: StreamNotification, raw_payload: dict[str, Any]
    ) -> bool:
        """Fast path: record the observation immediately. Never alone
        treated as confirmed truth -- a WebSocket receipt only ever
        produces a PROCESSED-level commitment observation with unknown
        execution success (a bare notification carries no err field);
        only :meth:`reconcile` can promote it to CONFIRMED/FINALIZED,
        since a WebSocket receipt is not proof of complete observation
        per section 19."""
        now = self._clock.utc_now()
        draft = ChainEventDraft(
            event_id=uuid.uuid4(),
            chain="solana",
            slot=notification.slot,
            block_time=None,
            first_seen_at=now,
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
        outcome = await self._event_recorder.record(draft)

        await self._commitment_tracker.record(
            event_id=outcome.event_id,
            commitment_level=COMMITMENT_PROCESSED,
            transaction_succeeded=None,
            observed_at=now,
            provider=self._provider_name,
            provider_received_at=now,
            created_at=now,
        )

        watermark = await self._get_or_init(notification.wallet_address)
        watermark = dataclasses.replace(
            watermark,
            last_stream_signature=notification.signature,
            last_stream_slot=notification.slot,
            updated_at=now,
        )
        await self._watermark_store.save(watermark)
        await self._commit_hook()
        return outcome.is_new

    async def _fetch_all_pages(
        self, wallet_address: str, *, boundary_signature: str | None
    ) -> tuple[list[SignatureInfo], str | None]:
        """Fully paginates the gap between ``boundary_signature`` (fixed,
        exclusive lower bound) and the newest signature, mirroring real
        Solana ``getSignaturesForAddress`` pagination (finding #2).

        Returns ``(all_signatures_newest_first, degraded_reason)`` --
        ``degraded_reason`` is non-empty (and ``all_signatures_newest_first``
        holds whatever was safely collected before stopping) if a
        non-progressing cursor or the safety-ceiling was hit; both are
        distinct from a provider exception, which the caller handles
        separately since nothing was fetched *this* page.
        """
        all_pages: list[SignatureInfo] = []
        before_cursor: str | None = None
        for page_number in range(1, self._max_pages + 1):
            page = await self._chain_provider.get_signatures_for_address(
                wallet_address,
                until_signature=boundary_signature,
                before_signature=before_cursor,
                limit=self._page_size,
            )
            if not page:
                return all_pages, ""
            oldest_in_page = page[-1].signature
            if before_cursor is not None and oldest_in_page == before_cursor:
                return all_pages, (
                    f"non-progressing pagination cursor detected at {oldest_in_page!r} "
                    f"(page {page_number}) -- provider returned no forward progress"
                )
            all_pages.extend(page)
            before_cursor = oldest_in_page
            if len(page) < self._page_size:
                return all_pages, ""
        return all_pages, (
            f"safety ceiling of {self._max_pages} pages exceeded; more events remain "
            f"unfetched beyond signature {before_cursor!r}"
        )

    async def reconcile(
        self, wallet_address: str, trigger: ReconciliationTrigger
    ) -> ReconciliationResult:
        """Truth path. Fully paginates every signature newer than
        ``last_reconciled_signature`` from the provider's own history
        (finding #2), fetches and canonicalizes each transaction, and
        relies on :class:`EventRecorder`'s dedup to guarantee exactly-once
        canonicalization regardless of whether the fast path already saw
        some of them. Each fetched transaction is also deterministically
        parsed and its versioned classification persisted, linked to the
        canonical event (finding #4); a parser failure is recorded but
        never discards the already-durable raw evidence or aborts the
        rest of the reconciliation.

        Any provider failure, non-progressing pagination cursor, or
        safety-ceiling breach (the "unresolved" case in section 19) marks
        the wallet ``DEGRADED`` rather than silently leaving the previous
        state in place -- a DEGRADED wallet must never look live-entry
        eligible just because nobody got around to re-checking it. The
        watermark only ever advances to the last item this call actually,
        durably finished processing -- never past an unfetched or failed
        item (finding #2).
        """
        now = self._clock.utc_now()
        watermark = await self._get_or_init(wallet_address)
        boundary_signature = watermark.last_reconciled_signature

        try:
            all_signatures, degraded_reason = await self._fetch_all_pages(
                wallet_address, boundary_signature=boundary_signature
            )
        except Exception as exc:
            await self._mark_degraded(watermark, now=now)
            return ReconciliationResult(
                ok=False, trigger=trigger, new_events=0, reason=f"{type(exc).__name__}: {exc}"
            )

        if degraded_reason:
            await self._mark_degraded(watermark, now=now)
            return ReconciliationResult(
                ok=False, trigger=trigger, new_events=0, reason=degraded_reason
            )

        new_events = 0
        parser_failures = 0
        latest_signature = watermark.last_reconciled_signature
        latest_slot = watermark.last_reconciled_slot

        # Provider returns newest-first across all pages combined; process
        # oldest-first for a deterministic, causally-ordered ledger.
        for sig_info in reversed(all_signatures):
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
                await self._commit_hook()
                return ReconciliationResult(
                    ok=False,
                    trigger=trigger,
                    new_events=new_events,
                    parser_failures=parser_failures,
                    reason=f"{type(exc).__name__}: {exc}",
                )

            draft = ChainEventDraft(
                event_id=uuid.uuid4(),
                chain="solana",
                slot=sig_info.slot,
                block_time=sig_info.block_time,
                first_seen_at=now,
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
            outcome = await self._event_recorder.record(draft)
            if outcome.is_new:
                new_events += 1

            # Commitment: `sig_info.err` is transaction *execution*
            # success/failure, not commitment level -- a failed
            # transaction can still be validly CONFIRMED on-chain (finding
            # #3). getSignaturesForAddress with the default/confirmed
            # commitment means this observation is at least CONFIRMED.
            await self._commitment_tracker.record(
                event_id=outcome.event_id,
                commitment_level=COMMITMENT_CONFIRMED,
                transaction_succeeded=sig_info.err is None,
                observed_at=now,
                provider=self._provider_name,
                provider_received_at=now,
                created_at=now,
            )

            # Parse and persist the derived classification (finding #4).
            # A parser failure on structurally-broken raw evidence must
            # never discard that already-durably-recorded raw evidence,
            # and must never abort the rest of this reconciliation.
            try:
                parsed = parse_transaction(
                    raw_payload,
                    wallet_address=wallet_address,
                    slot=sig_info.slot,
                    block_time=sig_info.block_time,
                )
                await self._swap_recorder.record(
                    event_id=outcome.event_id,
                    wallet_address=wallet_address,
                    parsed=parsed,
                    created_at=now,
                )
            except Exception:  # noqa: BLE001 - a parser failure is recorded, not fatal
                parser_failures += 1

            latest_signature = sig_info.signature
            latest_slot = sig_info.slot

            # Advance and durably persist progress after every single item
            # (not just at the end or per page): a crash here must resume
            # from exactly this point on the next reconcile() call,
            # without ever re-losing or re-skipping data (finding #2's
            # "mid-page fetch failure resumes at the exact safe boundary").
            in_progress = dataclasses.replace(
                watermark,
                last_reconciled_signature=latest_signature,
                last_reconciled_slot=latest_slot,
                updated_at=now,
            )
            await self._watermark_store.save(in_progress)
            await self._commit_hook()
            watermark = in_progress

        # A clock anomaly is a separate, additional gate on live-entry
        # eligibility from reconciliation success (section 17): provider
        # reconnection + chain reconciliation + clock health recovery are
        # all independently required, so an unresolved clock anomaly keeps
        # the wallet DEGRADED here even though this reconciliation itself
        # succeeded.
        clock_anomaly = self._clock_monitor is not None and self._clock_monitor.anomaly_detected
        resolved = dataclasses.replace(
            watermark,
            last_reconciliation_at=now,
            wallet_live_state=WALLET_LIVE_STATE_DEGRADED if clock_anomaly else WALLET_LIVE_STATE_OK,
            stream_health=STREAM_HEALTH_DEGRADED if clock_anomaly else STREAM_HEALTH_OK,
            updated_at=now,
        )
        await self._watermark_store.save(resolved)
        await self._commit_hook()
        reason = "unresolved clock anomaly blocks live-entry eligibility" if clock_anomaly else ""
        return ReconciliationResult(
            ok=True,
            trigger=trigger,
            new_events=new_events,
            parser_failures=parser_failures,
            reason=reason,
        )

    async def sweep_finalization(self, wallet_address: str, *, max_signatures: int = 200) -> int:
        """Real code path for FINALIZED commitment (finding #3: a
        schema-only ``finalized_at`` column with no writer is not real
        tracking). Batch-checks the most recent CONFIRMED-or-better events
        for this wallet via ``getSignatureStatuses`` and appends a
        FINALIZED observation wherever the provider now reports it.
        Returns the number of events newly promoted to FINALIZED. Never
        raises on a lookup failure for an individual event -- it simply
        isn't promoted this sweep and will be retried on the next one.

        A no-op (returns 0) if no :class:`RecentEventSource` was
        injected -- callers that never wire one simply never call this
        method's real work, rather than it silently pretending to sweep."""
        if self._recent_event_source is None:
            return 0
        watermark = await self._get_or_init(wallet_address)
        if watermark.last_reconciled_signature is None:
            return 0
        candidates = await self._recent_event_source.recent_signatures(
            wallet_address, limit=max_signatures
        )
        if not candidates:
            return 0
        try:
            statuses = await self._chain_provider.get_signature_statuses(
                [sig for _event_id, sig in candidates]
            )
        except Exception:  # noqa: BLE001 - best-effort sweep, never fatal
            return 0

        now = self._clock.utc_now()
        promoted = 0
        for (event_id, _signature), status in zip(candidates, statuses, strict=True):
            if status.confirmation_status != "finalized":
                continue
            result = await self._commitment_tracker.record(
                event_id=event_id,
                commitment_level=COMMITMENT_FINALIZED,
                transaction_succeeded=status.err is None,
                observed_at=now,
                provider=self._provider_name,
                provider_received_at=now,
                created_at=now,
            )
            if result.accepted:
                promoted += 1
            await self._commit_hook()
        return promoted

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
:class:`SwapRecorder`, :class:`argus.ingestion.parse_ledger.ParseAttemptRecorder`)
so it never depends on a real database or a real chain provider -- a fake
implementation of each is a first-class way to exercise the mandatory
deterministic scenario in MASTER_SPEC.md section 19:

    stream connects -> event A observed -> disconnect -> event B occurs
    while disconnected -> reconnect -> reconciliation discovers B

with the final canonical ledger containing A exactly once and B exactly
once, including across process restart and duplicate-delivery variants
(see tests/unit/test_reconciliation.py).

Phase 1 remediation round 1 (argus-phase-1-remediation-001) rewrote
``reconcile()`` to: fully paginate a truth-path gap larger than one page;
record commitment progression as append-only observations; parse each
fetched transaction and persist its derived, versioned classification.

Phase 1 remediation round 2 (argus-phase-1-remediation-002) rewrote it
again for three further findings:

- **Finding #2** (shared ``AsyncSession`` unsafe across concurrent
  tasks): every repository is now obtained fresh, per atomic operation,
  from an injected :class:`ReconciliationUnitOfWork` factory instead of
  being constructed once and shared. Each per-item write (one signature's
  chain event + commitment observation + parse attempt + swap + watermark
  advance) commits or rolls back together, as one database transaction,
  and a fresh unit of work is opened for the *next* item -- no session
  instance is ever touched by more than one logical operation, so two
  wallets' (or one wallet's stream-triggered and periodic-triggered)
  concurrent reconciliations can never corrupt or cross-commit each
  other's work. There is no more ``commit_hook`` parameter: committing is
  the unit of work's own ``__aexit__`` responsibility.
- **Finding #9** (parser failures were not durably recorded): every parse
  attempt -- success, ambiguous ``UNKNOWN``, or failure -- is written to
  the new durable ``parse_attempts`` ledger in the *same* per-item
  transaction as the watermark advance, so "the watermark moved past this
  item" and "the parse outcome for this item is durably recorded" are now
  atomically the same fact, never one without the other.
- **Finding #10** (pagination validated only the immediately-repeated
  cursor): :meth:`ReconciliationEngine._fetch_all_pages` now also
  rejects out-of-order/regressing slots, a signature repeated across
  pages, and multi-step cursor cycles (not just an immediate repeat), and
  documents why a safety-ceiling breach is the one case this provider
  surface cannot distinguish from provider-side pruning -- both leave the
  watermark exactly where it was, so the next call safely retries.

Phase 1 remediation round 3 (argus-phase-1-remediation-003), finding #2:
round 2's pagination fix still *assumed* a persisted boundary was reached
whenever a page came back short/empty, without ever directly observing
that boundary signature -- indistinguishable from the provider's
retained history simply ending early (pruning/retention limits/a lagging
node). :meth:`ReconciliationEngine._fetch_all_pages` no longer passes
``until_signature`` to the provider at all (Solana's own ``until`` is
exclusive, so honoring it would make the boundary itself unobservable);
it walks purely via ``before_signature`` and only reports success once
the boundary signature is directly matched in the provider's own
returned sequence. An empty/short page reached *without* that direct
match is now its own distinct failure (from bootstrap's ordinary
"reached the true start of history", which needs no boundary at all).
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import uuid
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any, Protocol

from argus.clock import Clock
from argus.domain.commitment import COMMITMENT_CONFIRMED, COMMITMENT_FINALIZED, COMMITMENT_PROCESSED
from argus.ingestion.clock_monitor import PersistentClockMonitor
from argus.ingestion.commitment import (
    CommitmentAppendOutcome,
    CommitmentObservationStore,
    CommitmentTracker,
)
from argus.ingestion.parse_ledger import (
    ParseAttemptDraft,
    ParseAttemptRecorder,
    outcome_for,
    payload_hash,
)
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
    """Phase 1 remediation round 2, finding #1: recovery requires three
    genuinely independent conditions, each tracked by its own field --
    ``stream_health`` (connected + subscribed + acknowledged, owned
    exclusively by the ingestion manager via :meth:`ReconciliationEngine.mark_stream_ready`/
    :meth:`~ReconciliationEngine.mark_degraded`, never by :meth:`~ReconciliationEngine.reconcile`),
    ``reconciliation_ok`` (the truth path's own last-attempt outcome,
    owned exclusively by :meth:`~ReconciliationEngine.reconcile`), and
    clock health (process-global, checked live from the injected
    ``PersistentClockMonitor``, never persisted per-wallet). ``wallet_live_state``
    is always the AND of all three, re-derived every time any one of them
    changes -- never set directly by a caller, and never settable to OK
    by any single dimension changing alone."""

    wallet_address: str
    last_stream_signature: str | None = None
    last_stream_slot: int | None = None
    last_reconciled_signature: str | None = None
    last_reconciled_slot: int | None = None
    last_reconciliation_at: datetime | None = None
    stream_health: str = "UNKNOWN"
    reconciliation_ok: bool = False
    # Fail-closed default: a wallet nobody has ever successfully brought
    # up (no stream ack, no reconciliation) must never look live-entry
    # eligible just because a fresh in-memory default happened to say so.
    wallet_live_state: str = WALLET_LIVE_STATE_DEGRADED
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
class ReconciliationRepos:
    """One bundle of repositories, all scoped to a single atomic unit of
    work (finding #2). Every write ``ReconciliationEngine`` makes goes
    through exactly one ``ReconciliationRepos`` instance obtained from a
    fresh call to the injected :class:`ReconciliationUnitOfWork` -- never
    a repository held across two different atomic operations."""

    watermark_store: WatermarkStore
    event_recorder: EventRecorder
    commitment_store: CommitmentObservationStore
    swap_recorder: SwapRecorder
    parse_attempt_recorder: ParseAttemptRecorder
    recent_event_source: RecentEventSource | None = None


class ReconciliationUnitOfWork(Protocol):
    """A callable that opens one atomic unit of work and yields a fresh
    :class:`ReconciliationRepos` bundle scoped to it. The real SQL
    implementation (``argus.ingestion.unit_of_work.SqlReconciliationUnitOfWork``)
    opens a new ``AsyncSession``, wraps the block in ``session.begin()``
    (commits on a clean exit, rolls back on any exception -- including
    ``asyncio.CancelledError``, since that still runs ``__aexit__`` with
    exception info), and always closes the session on the way out,
    satisfying finding #2's "session rollback/closure is guaranteed on
    cancellation and exceptions". A fake for tests may simply yield an
    already-constructed bundle of in-memory repositories with no real
    transaction semantics."""

    def __call__(self) -> AbstractAsyncContextManager[ReconciliationRepos]: ...


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


def _derive_wallet_live_state(
    *, stream_health: str, reconciliation_ok: bool, clock_anomaly: bool
) -> str:
    """The single point where the three independent recovery dimensions
    (finding #1) combine into the overall gate: stream connected +
    acknowledged, reconciliation's own last attempt succeeded, and no
    outstanding clock anomaly -- all three, every time, never inferred
    from just one of them changing."""
    if stream_health == STREAM_HEALTH_OK and reconciliation_ok and not clock_anomaly:
        return WALLET_LIVE_STATE_OK
    return WALLET_LIVE_STATE_DEGRADED


@dataclasses.dataclass(frozen=True, slots=True)
class _ItemOutcome:
    is_new: bool
    parser_failed: bool


class ReconciliationEngine:
    def __init__(
        self,
        *,
        chain_provider: ChainProvider,
        unit_of_work: ReconciliationUnitOfWork,
        clock: Clock,
        provider_name: str,
        parser_version: str,
        clock_monitor: PersistentClockMonitor | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        if max_pages <= 0:
            raise ValueError("max_pages must be positive")
        self._chain_provider = chain_provider
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._provider_name = provider_name
        self._parser_version = parser_version
        self._clock_monitor = clock_monitor
        self._page_size = page_size
        self._max_pages = max_pages

    async def _get_or_init(
        self, repos: ReconciliationRepos, wallet_address: str
    ) -> WalletWatermark:
        existing = await repos.watermark_store.get(wallet_address)
        if existing is not None:
            return existing
        return WalletWatermark(wallet_address=wallet_address)

    async def _mark_degraded_locked(
        self,
        repos: ReconciliationRepos,
        watermark: WalletWatermark,
        *,
        now: datetime,
        **overrides: Any,
    ) -> None:
        # The *stream* dimension failed (or a caller is unconditionally
        # forcing DEGRADED, e.g. a clock anomaly) -- reconciliation's own
        # last-known outcome is left untouched here; a stream failure
        # never fabricates a reconciliation failure that didn't happen,
        # it just makes the derived overall state DEGRADED regardless.
        degraded = dataclasses.replace(
            watermark,
            wallet_live_state=WALLET_LIVE_STATE_DEGRADED,
            stream_health=STREAM_HEALTH_DEGRADED,
            updated_at=now,
            **overrides,
        )
        await repos.watermark_store.save(degraded)

    async def mark_degraded(self, wallet_address: str, *, reason: str = "") -> None:
        """Public entry point for a caller (the ingestion manager) that
        has *itself* detected a disruptive transition -- a stream
        disconnect, timeout, malformed message, subscription failure, or
        cancellation -- and must mark the wallet DEGRADED immediately,
        before attempting any recovery, not only after a (possibly slow)
        :meth:`reconcile` call resolves. Idempotent: calling this on an
        already-DEGRADED wallet is a harmless no-op re-save."""
        del reason  # not persisted as a column today; kept for caller-side logging/testing clarity
        now = self._clock.utc_now()
        async with self._unit_of_work() as repos:
            watermark = await self._get_or_init(repos, wallet_address)
            await self._mark_degraded_locked(repos, watermark, now=now)

    async def mark_stream_ready(self, wallet_address: str) -> None:
        """Public entry point for the ingestion manager to call exactly
        once, immediately after a fresh subscription's connect + send +
        acknowledgement have all genuinely completed (finding #1) --
        never before, and never inferred from merely constructing a
        stream object. Deliberately does **not** set ``wallet_live_state``
        to OK by itself: recovery still requires reconciliation to
        separately succeed (and the clock to be healthy) before the
        derived overall state can become OK. Marking the stream ready
        while reconciliation's own last-known outcome is still failed (or
        has never yet succeeded) correctly leaves the wallet DEGRADED."""
        now = self._clock.utc_now()
        async with self._unit_of_work() as repos:
            watermark = await self._get_or_init(repos, wallet_address)
            ready = dataclasses.replace(
                watermark,
                stream_health=STREAM_HEALTH_OK,
                wallet_live_state=_derive_wallet_live_state(
                    stream_health=STREAM_HEALTH_OK,
                    reconciliation_ok=watermark.reconciliation_ok,
                    clock_anomaly=self._clock_monitor is not None
                    and self._clock_monitor.anomaly_detected,
                ),
                updated_at=now,
            )
            await repos.watermark_store.save(ready)

    async def observe_stream_event(
        self, notification: StreamNotification, raw_payload: dict[str, Any]
    ) -> bool:
        """Fast path: record the observation immediately. Never alone
        treated as confirmed truth -- a WebSocket receipt only ever
        produces a PROCESSED-level commitment observation with unknown
        execution success (a bare notification carries no err field);
        only :meth:`reconcile` can promote it to CONFIRMED/FINALIZED,
        since a WebSocket receipt is not proof of complete observation
        per section 19. Event record + commitment observation + watermark
        advance all happen inside one atomic unit of work (finding #2)."""
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
        async with self._unit_of_work() as repos:
            outcome = await repos.event_recorder.record(draft)

            await CommitmentTracker(repos.commitment_store).record(
                event_id=outcome.event_id,
                commitment_level=COMMITMENT_PROCESSED,
                transaction_succeeded=None,
                observed_at=now,
                provider=self._provider_name,
                provider_received_at=now,
                created_at=now,
            )

            watermark = await self._get_or_init(repos, notification.wallet_address)
            watermark = dataclasses.replace(
                watermark,
                last_stream_signature=notification.signature,
                last_stream_slot=notification.slot,
                updated_at=now,
            )
            await repos.watermark_store.save(watermark)
        return outcome.is_new

    async def _fetch_all_pages(
        self, wallet_address: str, *, boundary_signature: str | None
    ) -> tuple[list[SignatureInfo], str | None]:
        """Fully paginates the gap between ``boundary_signature`` (fixed,
        exclusive lower bound) and the newest signature, mirroring real
        Solana ``getSignaturesForAddress`` pagination.

        Returns ``(all_signatures_newest_first, degraded_reason)`` --
        ``degraded_reason`` is non-empty (and ``all_signatures_newest_first``
        holds whatever was safely collected before stopping) on any
        continuity/ordering fault; both are distinct from a provider
        exception, which the caller handles separately since nothing was
        fetched *this* page.

        Finding #10 (round 2) validates, beyond the original single-step
        non-progressing-cursor check:

        - **ordering**: every signature's slot must be non-increasing as
          pagination walks newest-to-oldest, within a page and across
          page boundaries (same-slot entries are never treated as
          ordering violations -- Solana gives no total order within one
          slot, and this function never fabricates one);
        - **cross-page uniqueness / cursor cycles**: the same signature
          must never appear twice. This single check is deliberately what
          catches both an immediately-repeated cursor *and* a multi-step
          cycle (C1 -> C2 -> C1) -- the next page's ``before`` cursor is
          always exactly the previous page's last item's own signature
          (mirroring real Solana pagination), so *any* cursor repeating,
          at any distance, is definitionally the same signature
          reappearing in a page's contents, which this check catches
          immediately, per-item, the moment it happens.

        Finding #2 (round 3): a persisted boundary is no longer merely
        *assumed* reached because a page came back short/empty -- that
        signal alone cannot distinguish "we truly walked all the way back
        to the boundary" from "the provider's retained history for this
        wallet ends before the boundary" (pruning, a retention limit, an
        incomplete/lagging RPC node). This function therefore never passes
        ``until_signature`` to the provider: Solana's own ``until``
        semantics are exclusive, so honoring it would mean the boundary
        transaction itself is never returned to us, making direct
        observation impossible. Instead it walks purely via
        ``before_signature`` and watches every returned item for a
        signature match against ``boundary_signature`` -- only that
        direct, positive observation proves the gap is fully and
        continuously covered, matching the boundary's real address
        membership, not merely its absence from a short page. The
        bootstrap case (``boundary_signature is None``, nothing to
        confirm) needs no such observation and is handled by the plain
        ``boundary_signature is None`` checks below -- an empty/short page
        there is still the ordinary, successful "reached the true start of
        this wallet's history" outcome, exactly as before.

        A safety-ceiling breach and provider-side pruning/retention limits
        remain indistinguishable from this provider surface alone (Solana
        RPC has no explicit "this history was pruned" signal); every
        failure message here says so explicitly rather than claiming to
        know which one occurred. Every failure path leaves the watermark
        untouched (the caller never advances it past an unfetched or
        unverified item), so the next ``reconcile()`` call safely retries
        from the exact same boundary once an operator has investigated.
        """
        all_pages: list[SignatureInfo] = []
        seen_signatures: set[str] = set()
        before_cursor: str | None = None
        last_slot: int | None = None

        def _boundary_not_observed_reason(page_number: int) -> str:
            return (
                f"pagination boundary not observed: address history for {wallet_address!r} "
                f"ended (page {page_number}) before persisted boundary signature "
                f"{boundary_signature!r} was directly observed in the provider's own "
                "address-history sequence -- indistinguishable from this provider surface "
                "alone from provider-side pruning/retention limits, an incomplete/lagging RPC "
                "node, or genuine data loss; the watermark is left untouched so the next "
                "reconcile() call safely retries, but an operator should independently confirm "
                "whether the boundary signature is still retrievable (e.g. via "
                "getSignatureStatuses/getTransaction against a different, more complete "
                "provider) before manually advancing past this gap"
            )

        for page_number in range(1, self._max_pages + 1):
            page = await self._chain_provider.get_signatures_for_address(
                wallet_address,
                before_signature=before_cursor,
                limit=self._page_size,
            )
            if not page:
                if boundary_signature is None:
                    return all_pages, ""
                return all_pages, _boundary_not_observed_reason(page_number)

            for item in page:
                if last_slot is not None and item.slot > last_slot:
                    return all_pages, (
                        f"pagination ordering fault: {item.signature!r} at slot {item.slot} is "
                        f"newer than the prior observed slot {last_slot} (page {page_number}) -- "
                        "provider violated newest-first ordering"
                    )
                last_slot = item.slot
                if item.signature == boundary_signature:
                    # The boundary itself is deliberately excluded from the
                    # result and never checked against seen_signatures --
                    # it is expected old evidence from a prior fetch, not
                    # part of this gap's own new-item set. Direct
                    # observation is the success signal (finding #2).
                    return all_pages, ""
                if item.signature in seen_signatures:
                    return all_pages, (
                        f"duplicate signature {item.signature!r} observed across pages (page "
                        f"{page_number}) -- provider pagination overlap or cursor cycle detected"
                    )
                seen_signatures.add(item.signature)
                all_pages.append(item)

            before_cursor = page[-1].signature
            if len(page) < self._page_size:
                if boundary_signature is None:
                    return all_pages, ""
                return all_pages, _boundary_not_observed_reason(page_number)

        if boundary_signature is None:
            return all_pages, (
                f"safety ceiling of {self._max_pages} pages exceeded during initial bootstrap "
                f"pagination for {wallet_address!r} without reaching the true start of this "
                "wallet's history -- raise max_pages/page_size or investigate provider "
                "retention, then retry (the persisted watermark is unchanged, so the next "
                "reconcile() call safely resumes from the same point)"
            )
        return all_pages, (
            f"safety ceiling of {self._max_pages} pages exceeded without observing the "
            f"persisted boundary signature {boundary_signature!r} in the provider's own "
            "address-history sequence -- a large real backlog and provider-side "
            "pruning/retention limits are indistinguishable from this provider surface alone; "
            "raise max_pages/page_size or investigate provider retention, then retry (the "
            "persisted watermark is unchanged, so the next reconcile() call safely resumes "
            "from the same boundary)"
        )

    async def _process_one_item(
        self,
        wallet_address: str,
        sig_info: SignatureInfo,
        raw_payload: dict[str, Any],
        *,
        now: datetime,
    ) -> _ItemOutcome:
        """One fully atomic unit of work for one signature: chain event +
        commitment observation + parse attempt (+ swap row on success) +
        watermark advance all commit together or none do (finding #2,
        finding #9)."""
        async with self._unit_of_work() as repos:
            watermark = await self._get_or_init(repos, wallet_address)

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
            outcome = await repos.event_recorder.record(draft)

            # `sig_info.err` is transaction *execution* success/failure,
            # not commitment level -- a failed transaction can still be
            # validly CONFIRMED on-chain. getSignaturesForAddress with the
            # default/confirmed commitment means this observation is at
            # least CONFIRMED.
            await CommitmentTracker(repos.commitment_store).record(
                event_id=outcome.event_id,
                commitment_level=COMMITMENT_CONFIRMED,
                transaction_succeeded=sig_info.err is None,
                observed_at=now,
                provider=self._provider_name,
                provider_received_at=now,
                created_at=now,
            )

            # Parse, persist the derived classification, and durably
            # record the attempt itself (finding #9) -- all in this same
            # transaction as the watermark advance below, so "watermark
            # moved past this item" and "the parse outcome is durably
            # recorded" are never true one without the other.
            classification: str | None = None
            exc: BaseException | None = None
            try:
                parsed = parse_transaction(
                    raw_payload,
                    wallet_address=wallet_address,
                    slot=sig_info.slot,
                    block_time=sig_info.block_time,
                )
                classification = parsed.classification
                await repos.swap_recorder.record(
                    event_id=outcome.event_id,
                    wallet_address=wallet_address,
                    parsed=parsed,
                    created_at=now,
                )
            except Exception as caught:  # noqa: BLE001 - recorded, never fatal to the rest of the item
                exc = caught

            parse_outcome, retry_disposition = outcome_for(classification=classification, exc=exc)
            await repos.parse_attempt_recorder.record(
                ParseAttemptDraft(
                    attempt_id=uuid.uuid4(),
                    event_id=outcome.event_id,
                    parser_version=self._parser_version,
                    attempted_at=now,
                    outcome=parse_outcome,
                    error_class=type(exc).__name__ if exc is not None else None,
                    error_reason=str(exc)[:512] if exc is not None else None,
                    input_payload_hash=payload_hash(raw_payload),
                    retry_disposition=retry_disposition,
                    created_at=now,
                )
            )

            in_progress = dataclasses.replace(
                watermark,
                last_reconciled_signature=sig_info.signature,
                last_reconciled_slot=sig_info.slot,
                updated_at=now,
            )
            await repos.watermark_store.save(in_progress)

        return _ItemOutcome(is_new=outcome.is_new, parser_failed=exc is not None)

    async def reconcile(
        self, wallet_address: str, trigger: ReconciliationTrigger
    ) -> ReconciliationResult:
        """Truth path. Fully paginates every signature newer than
        ``last_reconciled_signature`` from the provider's own history,
        fetches and canonicalizes each transaction, and relies on
        :class:`EventRecorder`'s dedup to guarantee exactly-once
        canonicalization regardless of whether the fast path already saw
        some of them. Each fetched transaction is also deterministically
        parsed and its versioned classification persisted, linked to the
        canonical event; a parser failure is durably recorded but never
        discards the already-durable raw evidence or aborts the rest of
        the reconciliation.

        Any provider failure, non-progressing pagination cursor, or
        safety-ceiling breach (the "unresolved" case in section 19) marks
        the wallet ``DEGRADED`` rather than silently leaving the previous
        state in place -- a DEGRADED wallet must never look live-entry
        eligible just because nobody got around to re-checking it. The
        watermark only ever advances to the last item this call actually,
        durably finished processing -- never past an unfetched or failed
        item. Each item is its own atomic unit of work (finding #2), so a
        crash mid-reconciliation resumes at exactly the last item that
        was durably, atomically finished, never a partially-written one.
        """
        now = self._clock.utc_now()
        async with self._unit_of_work() as repos:
            watermark = await self._get_or_init(repos, wallet_address)
        boundary_signature = watermark.last_reconciled_signature

        try:
            all_signatures, degraded_reason = await self._fetch_all_pages(
                wallet_address, boundary_signature=boundary_signature
            )
        except Exception as exc:
            await self._mark_reconciliation_failed(wallet_address, now=now)
            return ReconciliationResult(
                ok=False, trigger=trigger, new_events=0, reason=f"{type(exc).__name__}: {exc}"
            )

        if degraded_reason:
            await self._mark_reconciliation_failed(wallet_address, now=now)
            return ReconciliationResult(
                ok=False, trigger=trigger, new_events=0, reason=degraded_reason
            )

        new_events = 0
        parser_failures = 0

        # Provider returns newest-first across all pages combined; process
        # oldest-first for a deterministic, causally-ordered ledger.
        for sig_info in reversed(all_signatures):
            try:
                raw_payload = await self._chain_provider.get_transaction(sig_info.signature)
            except Exception as exc:
                await self._mark_reconciliation_failed(wallet_address, now=now)
                return ReconciliationResult(
                    ok=False,
                    trigger=trigger,
                    new_events=new_events,
                    parser_failures=parser_failures,
                    reason=f"{type(exc).__name__}: {exc}",
                )

            item_outcome = await self._process_one_item(
                wallet_address, sig_info, raw_payload, now=now
            )
            if item_outcome.parser_failed:
                parser_failures += 1
            if item_outcome.is_new:
                new_events += 1

        async with self._unit_of_work() as repos:
            watermark = await self._get_or_init(repos, wallet_address)
            # A clock anomaly is a separate, additional gate on live-entry
            # eligibility from reconciliation success (section 17):
            # provider reconnection + chain reconciliation + clock health
            # recovery are all independently required. Reconciliation's
            # own outcome (`reconciliation_ok`) reflects only whether the
            # truth path itself succeeded, mechanically, regardless of
            # clock state; the clock anomaly is folded in separately by
            # `_derive_wallet_live_state`, and `stream_health` is left
            # completely untouched here -- a truth-path-only success
            # never fabricates "the stream is connected" (finding #1),
            # just as a truth-path failure never fabricates "the stream
            # is down" (below).
            clock_anomaly = self._clock_monitor is not None and self._clock_monitor.anomaly_detected
            resolved = dataclasses.replace(
                watermark,
                last_reconciliation_at=now,
                reconciliation_ok=True,
                wallet_live_state=_derive_wallet_live_state(
                    stream_health=watermark.stream_health,
                    reconciliation_ok=True,
                    clock_anomaly=clock_anomaly,
                ),
                updated_at=now,
            )
            await repos.watermark_store.save(resolved)
        reason = "unresolved clock anomaly blocks live-entry eligibility" if clock_anomaly else ""
        return ReconciliationResult(
            ok=True,
            trigger=trigger,
            new_events=new_events,
            parser_failures=parser_failures,
            reason=reason,
        )

    async def _mark_reconciliation_failed(self, wallet_address: str, *, now: datetime) -> None:
        """The truth path itself failed (provider error, pagination
        continuity fault, mid-item fetch failure) -- ``reconciliation_ok``
        goes false and the derived overall state follows, but
        ``stream_health`` is left exactly as it was: a truth-path failure
        is not evidence the live WebSocket connection is also down
        (finding #1's independent-dimensions requirement)."""
        async with self._unit_of_work() as repos:
            watermark = await self._get_or_init(repos, wallet_address)
            clock_anomaly = self._clock_monitor is not None and self._clock_monitor.anomaly_detected
            failed = dataclasses.replace(
                watermark,
                reconciliation_ok=False,
                wallet_live_state=_derive_wallet_live_state(
                    stream_health=watermark.stream_health,
                    reconciliation_ok=False,
                    clock_anomaly=clock_anomaly,
                ),
                updated_at=now,
            )
            await repos.watermark_store.save(failed)

    async def sweep_finalization(self, wallet_address: str, *, max_signatures: int = 200) -> int:
        """Real code path for FINALIZED commitment. Batch-checks the most
        recent CONFIRMED-or-better events for this wallet via
        ``getSignatureStatuses`` and appends a FINALIZED observation
        wherever the provider now reports it. Returns the number of
        events genuinely newly promoted to FINALIZED -- counted from
        :class:`~argus.ingestion.commitment.CommitmentAppendOutcome`, so a
        DUPLICATE_NOOP re-observation of an already-FINALIZED event is
        never double-counted (finding #5). Never raises on a lookup
        failure for an individual event -- it simply isn't promoted this
        sweep and will be retried on the next one.

        A no-op (returns 0) if no :class:`RecentEventSource` is available
        from the unit of work's repos -- callers that never wire one
        simply never do this method's real work, rather than it silently
        pretending to sweep."""
        async with self._unit_of_work() as repos:
            if repos.recent_event_source is None:
                return 0
            watermark = await self._get_or_init(repos, wallet_address)
            if watermark.last_reconciled_signature is None:
                return 0
            candidates = await repos.recent_event_source.recent_signatures(
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
            async with self._unit_of_work() as repos:
                result = await CommitmentTracker(repos.commitment_store).record(
                    event_id=event_id,
                    commitment_level=COMMITMENT_FINALIZED,
                    transaction_succeeded=status.err is None,
                    observed_at=now,
                    provider=self._provider_name,
                    provider_received_at=now,
                    created_at=now,
                )
            if result.outcome == CommitmentAppendOutcome.APPENDED:
                promoted += 1
        return promoted

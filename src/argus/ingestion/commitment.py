"""Commitment-progression tracking: append-only observation acceptance,
regression/conflict rejection, and deterministic current-state derivation.

MASTER_SPEC.md CORE-002 (raw evidence is append-only), CORE-003 (point-in-
time truth fields stay distinct), section 20 (commitment policy: only a
CONFIRMED-or-better, successfully-executed observation may ever be
live-copy eligible). Phase 1 remediation round 1, finding #3: the earlier
design tried to set ``chain_events.confirmed_at``/``finalized_at`` on an
already-inserted row, which the table's own dedup unique constraint always
silently blocked. This module is the replacement: every observation of a
transaction's commitment level is appended to ``commitment_observations``
(never overwriting a prior one), and "current commitment state" is always
a deterministic query over that log, computed by :func:`derive_current_state`
-- there is no mutable "commitment" column anywhere to get out of sync.

Phase 1 remediation round 2 (argus-phase-1-remediation-002), finding #5,
fixed two further defects in round 1's implementation:

1. ``derive_current_state``'s tie-break used Python list position, which
   depended on how the store happened to order its ``list_for_event``
   result -- unstable across independent queries when rows share
   ``observed_at``. It now uses ``sequence``, a database-generated
   globally monotonic identity column (see ``argus.domain.commitment``),
   which is a stable total order regardless of how a store orders reads.
2. ``CommitmentTracker.record()`` validated a new same-level observation
   against only the *first* same-level row found, not the full current
   same-level state -- after an unknown-to-known refinement, a later
   conflicting known value could be compared against the stale original
   unknown row and wrongly accepted. It now considers every existing
   same-level observation.

It also adds: an append-only audit record for every rejected observation
(``CommitmentObservationStore.append_rejection``, finding #5's "durable
audit record for rejected regression/conflict attempts"); atomic
per-event serialization via ``CommitmentObservationStore.lock`` (a
database-safe advisory lock for the SQL store, an ``asyncio.Lock`` for
the in-memory fake) so concurrent stream/reconciliation/finalization
writers for the same event can never race a read-check-append sequence;
and an explicit :class:`CommitmentAppendOutcome` distinguishing
``APPENDED`` from ``DUPLICATE_NOOP`` so callers like
``ReconciliationEngine.sweep_finalization`` count only genuine new
promotions.
"""

from __future__ import annotations

import dataclasses
import enum
import uuid
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol

from argus.domain.commitment import COMMITMENT_CONFIRMED, COMMITMENT_RANK


@dataclasses.dataclass(frozen=True, slots=True)
class CommitmentObservationDraft:
    observation_id: uuid.UUID
    event_id: uuid.UUID
    commitment_level: str
    transaction_succeeded: bool | None
    observed_at: datetime
    provider: str
    provider_received_at: datetime
    created_at: datetime
    # Database-generated; ``None`` on a not-yet-appended draft. A store's
    # ``list_for_event`` must always populate this from the persisted row.
    sequence: int | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class CommitmentState:
    """Deterministic derived current state for one event_id."""

    commitment_level: str | None  # None = no observation exists yet
    transaction_succeeded: bool | None
    observed_at: datetime | None


class CommitmentAppendOutcome(enum.StrEnum):
    APPENDED = "APPENDED"
    DUPLICATE_NOOP = "DUPLICATE_NOOP"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


@dataclasses.dataclass(frozen=True, slots=True)
class CommitmentAppendResult:
    outcome: CommitmentAppendOutcome
    reason: str = ""

    @property
    def accepted(self) -> bool:
        """``True`` for both ``APPENDED`` and ``DUPLICATE_NOOP`` -- the
        observation is not in conflict with recorded state, whether or
        not it produced a new row. Kept as a convenience for callers that
        only care about "was this a business-rule rejection or failure",
        not the finer APPENDED/DUPLICATE_NOOP distinction."""
        return self.outcome in (
            CommitmentAppendOutcome.APPENDED,
            CommitmentAppendOutcome.DUPLICATE_NOOP,
        )


class CommitmentObservationStore(Protocol):
    """A real implementation backs onto ``commitment_observations``
    (ordered by the database-generated ``sequence`` column) plus
    ``commitment_observation_rejections`` for :meth:`append_rejection`; a
    fake for tests is a plain in-memory list keyed by event_id, with a
    per-event ``asyncio.Lock`` backing :meth:`lock`."""

    async def list_for_event(self, event_id: uuid.UUID) -> list[CommitmentObservationDraft]: ...
    async def append(self, observation: CommitmentObservationDraft) -> None: ...
    async def append_rejection(
        self,
        *,
        event_id: uuid.UUID,
        attempted_commitment_level: str,
        attempted_transaction_succeeded: bool | None,
        attempted_observed_at: datetime,
        attempted_provider: str,
        reason: str,
        created_at: datetime,
    ) -> None: ...

    def lock(self, event_id: uuid.UUID) -> AbstractAsyncContextManager[None]:
        """Serializes every ``record()`` call for this ``event_id`` across
        concurrent tasks (finding #5's "atomic per-event serialization
        using a database-safe mechanism") -- a plain read-check-append is
        race-prone: two concurrent writers can each read the same
        pre-append state and both decide their write is a valid
        refinement, double-appending or accepting a conflict that a
        serialized check would have rejected."""
        ...


def derive_current_state(observations: list[CommitmentObservationDraft]) -> CommitmentState:
    """The single deterministic source of "what is this event's commitment
    state right now" -- highest commitment rank, most recent ``observed_at``
    breaking ties, and the database-generated monotonic ``sequence``
    breaking any remaining tie so the most-recently-appended refinement
    always wins over an earlier observation with an identical rank and
    timestamp, deterministically and identically across independent
    sessions/queries (finding #5). Never a stored/mutated field, always
    this query."""
    if not observations:
        return CommitmentState(commitment_level=None, transaction_succeeded=None, observed_at=None)
    best = max(
        observations,
        key=lambda o: (COMMITMENT_RANK[o.commitment_level], o.observed_at, o.sequence or -1),
    )
    return CommitmentState(
        commitment_level=best.commitment_level,
        transaction_succeeded=best.transaction_succeeded,
        observed_at=best.observed_at,
    )


class CommitmentTracker:
    """Append-only commitment log writer with regression/conflict
    rejection, against an injected :class:`CommitmentObservationStore`."""

    def __init__(self, store: CommitmentObservationStore) -> None:
        self._store = store

    async def record(
        self,
        *,
        event_id: uuid.UUID,
        commitment_level: str,
        transaction_succeeded: bool | None,
        observed_at: datetime,
        provider: str,
        provider_received_at: datetime,
        created_at: datetime,
        observation_id: uuid.UUID | None = None,
    ) -> CommitmentAppendResult:
        if commitment_level not in COMMITMENT_RANK:
            return CommitmentAppendResult(
                outcome=CommitmentAppendOutcome.FAILED,
                reason=f"unknown commitment level {commitment_level!r}",
            )

        async with self._store.lock(event_id):
            existing = await self._store.list_for_event(event_id)
            new_rank = COMMITMENT_RANK[commitment_level]

            # Validate against the *full* current same-level state, not
            # just the first same-level row found (finding #5): a known
            # value recorded anywhere at this level is authoritative for
            # conflict detection, regardless of how many unknown-success
            # observations came before or after it.
            same_level = [o for o in existing if o.commitment_level == commitment_level]
            known_values = {
                o.transaction_succeeded for o in same_level if o.transaction_succeeded is not None
            }

            if same_level:
                if transaction_succeeded is None:
                    return CommitmentAppendResult(
                        outcome=CommitmentAppendOutcome.DUPLICATE_NOOP,
                        reason="duplicate observation (unknown success), no-op",
                    )
                if not known_values:
                    pass  # every existing same-level observation was unknown -- a legitimate refinement, fall through to append.
                elif known_values == {transaction_succeeded}:
                    return CommitmentAppendResult(
                        outcome=CommitmentAppendOutcome.DUPLICATE_NOOP,
                        reason="duplicate observation, no-op",
                    )
                else:
                    reason = (
                        f"conflicting execution result at {commitment_level}: "
                        f"existing={sorted(known_values, key=str)}, new={transaction_succeeded}"
                    )
                    await self._store.append_rejection(
                        event_id=event_id,
                        attempted_commitment_level=commitment_level,
                        attempted_transaction_succeeded=transaction_succeeded,
                        attempted_observed_at=observed_at,
                        attempted_provider=provider,
                        reason=reason,
                        created_at=created_at,
                    )
                    return CommitmentAppendResult(
                        outcome=CommitmentAppendOutcome.REJECTED, reason=reason
                    )
            elif existing:
                max_rank = max(COMMITMENT_RANK[o.commitment_level] for o in existing)
                if new_rank < max_rank:
                    reason = (
                        f"commitment regression rejected: already have rank {max_rank}, "
                        f"new observation is rank {new_rank} ({commitment_level})"
                    )
                    await self._store.append_rejection(
                        event_id=event_id,
                        attempted_commitment_level=commitment_level,
                        attempted_transaction_succeeded=transaction_succeeded,
                        attempted_observed_at=observed_at,
                        attempted_provider=provider,
                        reason=reason,
                        created_at=created_at,
                    )
                    return CommitmentAppendResult(
                        outcome=CommitmentAppendOutcome.REJECTED, reason=reason
                    )

            await self._store.append(
                CommitmentObservationDraft(
                    observation_id=observation_id or uuid.uuid4(),
                    event_id=event_id,
                    commitment_level=commitment_level,
                    transaction_succeeded=transaction_succeeded,
                    observed_at=observed_at,
                    provider=provider,
                    provider_received_at=provider_received_at,
                    created_at=created_at,
                )
            )
            return CommitmentAppendResult(outcome=CommitmentAppendOutcome.APPENDED)

    async def current_state(self, event_id: uuid.UUID) -> CommitmentState:
        return derive_current_state(await self._store.list_for_event(event_id))


def is_execution_eligible(state: CommitmentState) -> bool:
    """A processed-only (or unobserved) event can never be copy-eligible
    (MASTER_SPEC.md section 20's confirmed-only live-entry policy), and a
    transaction that reached commitment but executed-failed can never be
    copy-eligible regardless of commitment level -- it moved nothing."""
    if state.commitment_level is None:
        return False
    if COMMITMENT_RANK[state.commitment_level] < COMMITMENT_RANK[COMMITMENT_CONFIRMED]:
        return False
    return state.transaction_succeeded is True


class InMemoryCommitmentObservationStore:
    """Reference in-memory :class:`CommitmentObservationStore` shared by
    ``argus.ingestion.test_mode`` and the unit-test suite -- a single
    source of truth for the fake's locking/sequencing semantics instead
    of each test file reimplementing it slightly differently."""

    def __init__(self) -> None:
        import asyncio
        import collections

        self._by_event: dict[uuid.UUID, list[CommitmentObservationDraft]] = collections.defaultdict(
            list
        )
        self.rejections: list[dict[str, object]] = []
        self._locks: dict[uuid.UUID, asyncio.Lock] = collections.defaultdict(asyncio.Lock)
        self._next_sequence = 1

    async def list_for_event(self, event_id: uuid.UUID) -> list[CommitmentObservationDraft]:
        return list(self._by_event[event_id])

    async def append(self, observation: CommitmentObservationDraft) -> None:
        stamped = dataclasses.replace(observation, sequence=self._next_sequence)
        self._next_sequence += 1
        self._by_event[observation.event_id].append(stamped)

    async def append_rejection(
        self,
        *,
        event_id: uuid.UUID,
        attempted_commitment_level: str,
        attempted_transaction_succeeded: bool | None,
        attempted_observed_at: datetime,
        attempted_provider: str,
        reason: str,
        created_at: datetime,
    ) -> None:
        self.rejections.append(
            {
                "event_id": event_id,
                "attempted_commitment_level": attempted_commitment_level,
                "attempted_transaction_succeeded": attempted_transaction_succeeded,
                "attempted_observed_at": attempted_observed_at,
                "attempted_provider": attempted_provider,
                "reason": reason,
                "created_at": created_at,
            }
        )

    def lock(self, event_id: uuid.UUID) -> AbstractAsyncContextManager[None]:
        import contextlib

        @contextlib.asynccontextmanager
        async def _cm() -> AsyncIterator[None]:
            async with self._locks[event_id]:
                yield

        return _cm()

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
"""

from __future__ import annotations

import dataclasses
import uuid
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


@dataclasses.dataclass(frozen=True, slots=True)
class CommitmentState:
    """Deterministic derived current state for one event_id."""

    commitment_level: str | None  # None = no observation exists yet
    transaction_succeeded: bool | None
    observed_at: datetime | None


@dataclasses.dataclass(frozen=True, slots=True)
class CommitmentAppendResult:
    accepted: bool
    reason: str = ""


class CommitmentObservationStore(Protocol):
    """A real implementation backs onto ``commitment_observations``; a
    fake for tests is a plain in-memory list keyed by event_id."""

    async def list_for_event(self, event_id: uuid.UUID) -> list[CommitmentObservationDraft]: ...
    async def append(self, observation: CommitmentObservationDraft) -> None: ...


def derive_current_state(observations: list[CommitmentObservationDraft]) -> CommitmentState:
    """The single deterministic source of "what is this event's commitment
    state right now" -- highest commitment rank, most recent ``observed_at``
    breaking ties, and append order (the store's own return order) breaking
    any remaining tie so the most-recently-recorded refinement always wins
    over an earlier observation with an identical rank and timestamp. Never
    a stored/mutated field, always this query."""
    if not observations:
        return CommitmentState(commitment_level=None, transaction_succeeded=None, observed_at=None)
    best_index, best = max(
        enumerate(observations),
        key=lambda pair: (COMMITMENT_RANK[pair[1].commitment_level], pair[1].observed_at, pair[0]),
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
                accepted=False, reason=f"unknown commitment level {commitment_level!r}"
            )

        existing = await self._store.list_for_event(event_id)
        new_rank = COMMITMENT_RANK[commitment_level]

        same_level = next((o for o in existing if o.commitment_level == commitment_level), None)
        if same_level is not None:
            # A second observation at a level we've already recorded is a
            # refinement/duplicate, not a new "step forward" -- handle it
            # completely here and never fall through to the regression
            # check below, which only makes sense for a genuinely new
            # level.
            if same_level.transaction_succeeded == transaction_succeeded:
                return CommitmentAppendResult(accepted=True, reason="duplicate observation, no-op")
            if transaction_succeeded is None:
                return CommitmentAppendResult(
                    accepted=True, reason="duplicate observation (unknown success), no-op"
                )
            if same_level.transaction_succeeded is not None:
                return CommitmentAppendResult(
                    accepted=False,
                    reason=(
                        f"conflicting execution result at {commitment_level}: "
                        f"existing={same_level.transaction_succeeded}, new={transaction_succeeded}"
                    ),
                )
            # existing was unknown, new is known -- a legitimate
            # refinement; falls through to append below.
        elif existing:
            max_rank = max(COMMITMENT_RANK[o.commitment_level] for o in existing)
            if new_rank < max_rank:
                return CommitmentAppendResult(
                    accepted=False,
                    reason=(
                        f"commitment regression rejected: already have rank {max_rank}, "
                        f"new observation is rank {new_rank} ({commitment_level})"
                    ),
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
        return CommitmentAppendResult(accepted=True)

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

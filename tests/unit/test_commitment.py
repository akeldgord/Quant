"""Tests for `argus.ingestion.commitment` (Phase 1 remediation finding #3:
commitment progression as an append-only observation log, not a mutable
column that a dedup constraint silently blocks from ever being set).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from argus.domain.commitment import COMMITMENT_CONFIRMED, COMMITMENT_FINALIZED, COMMITMENT_PROCESSED
from argus.ingestion.commitment import (
    CommitmentAppendOutcome,
    CommitmentObservationDraft,
    CommitmentTracker,
    InMemoryCommitmentObservationStore,
    derive_current_state,
    is_execution_eligible,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
EVENT = uuid.uuid4()

# Phase 1 remediation round 2 (finding #5): the shared reference fake --
# it carries the same lock()/append_rejection()/sequence-stamping
# behavior the real SQL store has, so these tests exercise the exact
# contract every store implementation (including a fresh in-memory
# instance per test) must satisfy.
_InMemoryStore = InMemoryCommitmentObservationStore


def _kwargs(**overrides):
    base = {
        "event_id": EVENT,
        "commitment_level": COMMITMENT_CONFIRMED,
        "transaction_succeeded": True,
        "observed_at": T0,
        "provider": "fake",
        "provider_received_at": T0,
        "created_at": T0,
    }
    base.update(overrides)
    return base


async def test_first_observation_is_accepted() -> None:
    tracker = CommitmentTracker(_InMemoryStore())
    result = await tracker.record(
        **_kwargs(commitment_level=COMMITMENT_PROCESSED, transaction_succeeded=None)
    )
    assert result.accepted is True
    state = await tracker.current_state(EVENT)
    assert state.commitment_level == COMMITMENT_PROCESSED
    assert state.transaction_succeeded is None


async def test_promotion_from_processed_to_confirmed_is_accepted() -> None:
    tracker = CommitmentTracker(_InMemoryStore())
    await tracker.record(
        **_kwargs(commitment_level=COMMITMENT_PROCESSED, transaction_succeeded=None)
    )
    result = await tracker.record(
        **_kwargs(
            commitment_level=COMMITMENT_CONFIRMED,
            transaction_succeeded=True,
            observed_at=T0 + timedelta(seconds=1),
        )
    )
    assert result.accepted is True
    state = await tracker.current_state(EVENT)
    assert state.commitment_level == COMMITMENT_CONFIRMED
    assert state.transaction_succeeded is True


async def test_promotion_to_finalized_preserves_first_seen_semantics() -> None:
    """The fast-path first-seen observation is never overwritten -- it
    remains in the log even after later, higher-rank observations."""
    tracker = CommitmentTracker(_InMemoryStore())
    await tracker.record(
        **_kwargs(commitment_level=COMMITMENT_PROCESSED, transaction_succeeded=None, observed_at=T0)
    )
    await tracker.record(
        **_kwargs(
            commitment_level=COMMITMENT_CONFIRMED,
            transaction_succeeded=True,
            observed_at=T0 + timedelta(seconds=1),
        )
    )
    await tracker.record(
        **_kwargs(
            commitment_level=COMMITMENT_FINALIZED,
            transaction_succeeded=True,
            observed_at=T0 + timedelta(seconds=30),
        )
    )
    state = await tracker.current_state(EVENT)
    assert state.commitment_level == COMMITMENT_FINALIZED
    assert state.transaction_succeeded is True
    tracker_store = tracker._store  # type: ignore[attr-defined]
    all_rows = await tracker_store.list_for_event(EVENT)
    levels = sorted(r.commitment_level for r in all_rows)
    assert levels == sorted([COMMITMENT_PROCESSED, COMMITMENT_CONFIRMED, COMMITMENT_FINALIZED])


async def test_duplicate_observation_same_value_is_idempotent_noop() -> None:
    tracker = CommitmentTracker(_InMemoryStore())
    await tracker.record(
        **_kwargs(commitment_level=COMMITMENT_CONFIRMED, transaction_succeeded=True)
    )
    result = await tracker.record(
        **_kwargs(commitment_level=COMMITMENT_CONFIRMED, transaction_succeeded=True)
    )
    assert result.accepted is True
    assert "no-op" in result.reason
    state = await tracker.current_state(EVENT)
    rows = await tracker._store.list_for_event(EVENT)  # type: ignore[attr-defined]
    assert len(rows) == 1  # not duplicated
    assert state.transaction_succeeded is True


async def test_unknown_success_upgraded_to_known_is_accepted_as_refinement() -> None:
    tracker = CommitmentTracker(_InMemoryStore())
    await tracker.record(
        **_kwargs(commitment_level=COMMITMENT_CONFIRMED, transaction_succeeded=None)
    )
    result = await tracker.record(
        **_kwargs(commitment_level=COMMITMENT_CONFIRMED, transaction_succeeded=False)
    )
    assert result.accepted is True
    state = await tracker.current_state(EVENT)
    assert state.transaction_succeeded is False


async def test_new_unknown_after_known_does_not_downgrade() -> None:
    tracker = CommitmentTracker(_InMemoryStore())
    await tracker.record(
        **_kwargs(commitment_level=COMMITMENT_CONFIRMED, transaction_succeeded=True)
    )
    result = await tracker.record(
        **_kwargs(commitment_level=COMMITMENT_CONFIRMED, transaction_succeeded=None)
    )
    assert result.accepted is True
    state = await tracker.current_state(EVENT)
    assert state.transaction_succeeded is True  # not overwritten to None


async def test_conflicting_execution_result_at_same_level_is_rejected() -> None:
    tracker = CommitmentTracker(_InMemoryStore())
    await tracker.record(
        **_kwargs(commitment_level=COMMITMENT_CONFIRMED, transaction_succeeded=True)
    )
    result = await tracker.record(
        **_kwargs(commitment_level=COMMITMENT_CONFIRMED, transaction_succeeded=False)
    )
    assert result.accepted is False
    assert "conflicting" in result.reason
    state = await tracker.current_state(EVENT)
    assert state.transaction_succeeded is True  # rejected write never applied


async def test_commitment_regression_is_rejected() -> None:
    tracker = CommitmentTracker(_InMemoryStore())
    await tracker.record(
        **_kwargs(commitment_level=COMMITMENT_FINALIZED, transaction_succeeded=True)
    )
    result = await tracker.record(
        **_kwargs(commitment_level=COMMITMENT_PROCESSED, transaction_succeeded=None)
    )
    assert result.accepted is False
    assert "regression" in result.reason
    state = await tracker.current_state(EVENT)
    assert state.commitment_level == COMMITMENT_FINALIZED  # unaffected


async def test_refining_a_non_max_level_after_a_higher_level_exists_is_not_a_regression() -> None:
    """Edge case: PROCESSED(unknown) -> FINALIZED(True) recorded, then a
    late-arriving PROCESSED(unknown) duplicate must not be misread as a
    regression just because FINALIZED already exists."""
    tracker = CommitmentTracker(_InMemoryStore())
    await tracker.record(
        **_kwargs(commitment_level=COMMITMENT_PROCESSED, transaction_succeeded=None)
    )
    await tracker.record(
        **_kwargs(commitment_level=COMMITMENT_FINALIZED, transaction_succeeded=True)
    )
    result = await tracker.record(
        **_kwargs(commitment_level=COMMITMENT_PROCESSED, transaction_succeeded=None)
    )
    assert result.accepted is True
    assert "no-op" in result.reason
    state = await tracker.current_state(EVENT)
    assert state.commitment_level == COMMITMENT_FINALIZED  # still the real current state


def test_derive_current_state_empty_is_none() -> None:
    state = derive_current_state([])
    assert state.commitment_level is None


def test_is_execution_eligible_requires_confirmed_or_better_and_success() -> None:
    unobserved = derive_current_state([])
    assert is_execution_eligible(unobserved) is False

    processed_only = derive_current_state(
        [
            CommitmentObservationDraft(
                uuid.uuid4(), EVENT, COMMITMENT_PROCESSED, None, T0, "p", T0, T0
            )
        ]
    )
    assert is_execution_eligible(processed_only) is False

    confirmed_failed = derive_current_state(
        [
            CommitmentObservationDraft(
                uuid.uuid4(), EVENT, COMMITMENT_CONFIRMED, False, T0, "p", T0, T0
            )
        ]
    )
    assert is_execution_eligible(confirmed_failed) is False  # confirmed but execution-failed

    confirmed_success = derive_current_state(
        [
            CommitmentObservationDraft(
                uuid.uuid4(), EVENT, COMMITMENT_CONFIRMED, True, T0, "p", T0, T0
            )
        ]
    )
    assert is_execution_eligible(confirmed_success) is True

    finalized_success = derive_current_state(
        [
            CommitmentObservationDraft(
                uuid.uuid4(), EVENT, COMMITMENT_FINALIZED, True, T0, "p", T0, T0
            )
        ]
    )
    assert is_execution_eligible(finalized_success) is True


# --- Phase 1 remediation round 2, finding #5 ----------------------------


async def test_conflict_detected_against_full_same_level_state_not_just_first_row() -> None:
    """Regression test for the exact round-1 bug finding #5 names: after
    an unknown-to-known refinement, a *third* observation at the same
    level must be checked against every existing same-level row, not only
    the first one the store happens to return. PROCESSED(unknown) ->
    CONFIRMED(unknown) -> CONFIRMED(True) [refinement, accepted] ->
    CONFIRMED(False) must be rejected as conflicting -- comparing only
    against the first same-level row (the original unknown one) would
    have wrongly accepted it as another "unknown refined to known"."""
    tracker = CommitmentTracker(_InMemoryStore())
    await tracker.record(
        **_kwargs(commitment_level=COMMITMENT_CONFIRMED, transaction_succeeded=None)
    )
    refined = await tracker.record(
        **_kwargs(
            commitment_level=COMMITMENT_CONFIRMED,
            transaction_succeeded=True,
            observed_at=T0 + timedelta(seconds=1),
        )
    )
    assert refined.outcome == CommitmentAppendOutcome.APPENDED

    conflicting = await tracker.record(
        **_kwargs(
            commitment_level=COMMITMENT_CONFIRMED,
            transaction_succeeded=False,
            observed_at=T0 + timedelta(seconds=2),
        )
    )
    assert conflicting.outcome == CommitmentAppendOutcome.REJECTED
    assert "conflicting" in conflicting.reason
    state = await tracker.current_state(EVENT)
    assert state.transaction_succeeded is True  # the accepted refinement, unaffected


async def test_rejected_write_is_durably_audited() -> None:
    store = _InMemoryStore()
    tracker = CommitmentTracker(store)
    await tracker.record(
        **_kwargs(commitment_level=COMMITMENT_FINALIZED, transaction_succeeded=True)
    )
    result = await tracker.record(
        **_kwargs(commitment_level=COMMITMENT_PROCESSED, transaction_succeeded=None)
    )
    assert result.outcome == CommitmentAppendOutcome.REJECTED

    assert len(store.rejections) == 1
    audited = store.rejections[0]
    assert audited["event_id"] == EVENT
    assert audited["attempted_commitment_level"] == COMMITMENT_PROCESSED
    assert "regression" in audited["reason"]


def test_derive_current_state_tiebreaks_on_sequence_not_list_order() -> None:
    """Two observations sharing rank and observed_at: the store-assigned
    ``sequence`` (a durable, database-generated total order in the real
    store) must decide the tie deterministically, regardless of what
    order the list happens to be presented in."""
    older = CommitmentObservationDraft(
        uuid.uuid4(), EVENT, COMMITMENT_CONFIRMED, True, T0, "p", T0, T0, sequence=1
    )
    newer = CommitmentObservationDraft(
        uuid.uuid4(), EVENT, COMMITMENT_CONFIRMED, False, T0, "p", T0, T0, sequence=2
    )
    assert derive_current_state([older, newer]).transaction_succeeded is False
    assert derive_current_state([newer, older]).transaction_succeeded is False  # order-independent


async def test_store_assigns_monotonically_increasing_sequence_on_append() -> None:
    store = _InMemoryStore()
    tracker = CommitmentTracker(store)
    await tracker.record(
        **_kwargs(commitment_level=COMMITMENT_PROCESSED, transaction_succeeded=None)
    )
    await tracker.record(
        **_kwargs(
            commitment_level=COMMITMENT_CONFIRMED,
            transaction_succeeded=True,
            observed_at=T0 + timedelta(seconds=1),
        )
    )
    rows = await store.list_for_event(EVENT)
    sequences = [r.sequence for r in rows]
    assert all(s is not None for s in sequences)
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)  # strictly increasing, never repeated


async def test_concurrent_conflicting_writes_serialize_and_only_one_is_appended() -> None:
    """Without per-event serialization, two concurrent record() calls
    could each read "no same-level observation yet", and both decide
    their own value is a valid first write at that level -- corrupting
    the log with two same-level rows carrying conflicting execution
    results. An artificial yield point between the store's read and
    write is what makes a real interleaving opportunity observable in
    single-threaded asyncio; ``CommitmentObservationStore.lock()`` must
    still serialize through it."""
    import asyncio

    class _SlowStore(InMemoryCommitmentObservationStore):
        async def list_for_event(self, event_id: uuid.UUID) -> list[CommitmentObservationDraft]:
            result = await super().list_for_event(event_id)
            await asyncio.sleep(0)  # yield control -- the race window
            return result

    store = _SlowStore()
    tracker = CommitmentTracker(store)

    results = await asyncio.gather(
        tracker.record(
            **_kwargs(commitment_level=COMMITMENT_CONFIRMED, transaction_succeeded=True)
        ),
        tracker.record(
            **_kwargs(commitment_level=COMMITMENT_CONFIRMED, transaction_succeeded=False)
        ),
    )
    outcomes = sorted(r.outcome for r in results)
    assert outcomes == sorted([CommitmentAppendOutcome.APPENDED, CommitmentAppendOutcome.REJECTED])

    rows = await store.list_for_event(EVENT)
    assert len(rows) == 1  # never two conflicting same-level rows
    assert len(store.rejections) == 1

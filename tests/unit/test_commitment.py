"""Tests for `argus.ingestion.commitment` (Phase 1 remediation finding #3:
commitment progression as an append-only observation log, not a mutable
column that a dedup constraint silently blocks from ever being set).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from argus.domain.commitment import COMMITMENT_CONFIRMED, COMMITMENT_FINALIZED, COMMITMENT_PROCESSED
from argus.ingestion.commitment import (
    CommitmentObservationDraft,
    CommitmentTracker,
    derive_current_state,
    is_execution_eligible,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
EVENT = uuid.uuid4()


class _InMemoryStore:
    def __init__(self) -> None:
        self.rows: list[CommitmentObservationDraft] = []

    async def list_for_event(self, event_id: uuid.UUID) -> list[CommitmentObservationDraft]:
        return [r for r in self.rows if r.event_id == event_id]

    async def append(self, observation: CommitmentObservationDraft) -> None:
        self.rows.append(observation)


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

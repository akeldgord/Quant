"""P6-05 (SPEC_BLOCKING): persisted execution-intent state machine --
MASTER_SPEC.md section 76 (EXECUTION STATE MACHINE), orchestrator
instruction ``argus-phase-6-001``.

Every legal transition in the frozen 11-state graph succeeds; every
illegal transition (including into/out of a terminal state) always
raises rather than silently applying or corrupting state. The
persistence-level "restart reload" half of this row is covered by the
DB-gated integration test in
``tests/integration/test_phase6_persistence_and_concurrency.py``.
"""

from __future__ import annotations

import pytest

from argus.domain.execution_intents import EXECUTION_STATES
from argus.executor.state_machine import (
    TERMINAL_STATES,
    IllegalTransitionError,
    UnknownStateError,
    is_terminal,
    legal_next_states,
    transition,
)

_LEGAL_PAIRS: tuple[tuple[str, str], ...] = (
    ("CREATED", "VALIDATING"),
    ("VALIDATING", "ORDER_REQUESTED"),
    ("VALIDATING", "REJECTED"),
    ("ORDER_REQUESTED", "ORDER_READY"),
    ("ORDER_REQUESTED", "REJECTED"),
    ("ORDER_READY", "ATTESTING"),
    ("ORDER_READY", "REJECTED"),
    ("ATTESTING", "SIGNED"),
    ("ATTESTING", "REJECTED"),
    ("SIGNED", "SUBMITTED"),
    ("SUBMITTED", "CONFIRMED"),
    ("SUBMITTED", "FAILED"),
    ("SUBMITTED", "UNKNOWN"),
    ("UNKNOWN", "CONFIRMED"),
    ("UNKNOWN", "FAILED"),
)


@pytest.mark.parametrize("from_state,to_state", _LEGAL_PAIRS)
def test_legal_transition_succeeds(from_state: str, to_state: str) -> None:
    assert transition(from_state, to_state) == to_state


def test_exactly_eleven_frozen_states() -> None:
    assert len(EXECUTION_STATES) == 11
    assert len(set(EXECUTION_STATES)) == 11


def test_terminal_states_are_exactly_rejected_confirmed_failed() -> None:
    assert frozenset({"REJECTED", "CONFIRMED", "FAILED"}) == TERMINAL_STATES


@pytest.mark.parametrize("terminal_state", sorted(TERMINAL_STATES))
def test_terminal_state_has_no_legal_next_state(terminal_state: str) -> None:
    assert legal_next_states(terminal_state) == frozenset()
    assert is_terminal(terminal_state) is True


@pytest.mark.parametrize("terminal_state", sorted(TERMINAL_STATES))
def test_transition_out_of_terminal_state_always_raises(terminal_state: str) -> None:
    for candidate in EXECUTION_STATES:
        with pytest.raises(IllegalTransitionError):
            transition(terminal_state, candidate)


def test_cannot_skip_validating_straight_to_order_requested_from_created() -> None:
    with pytest.raises(IllegalTransitionError):
        transition("CREATED", "ORDER_REQUESTED")


def test_ambiguous_submitted_never_silently_retries_back_to_signed() -> None:
    """Section 77's own rule: an ambiguous SUBMITTED transaction resolves
    only via reconciliation into CONFIRMED/FAILED -- never a blind retry
    back into SIGNED/SUBMITTED."""
    with pytest.raises(IllegalTransitionError):
        transition("SUBMITTED", "SIGNED")
    with pytest.raises(IllegalTransitionError):
        transition("UNKNOWN", "SIGNED")
    with pytest.raises(IllegalTransitionError):
        transition("UNKNOWN", "SUBMITTED")


def test_unknown_state_name_raises_unknown_state_error() -> None:
    with pytest.raises(UnknownStateError):
        legal_next_states("NOT_A_REAL_STATE")
    with pytest.raises(UnknownStateError):
        transition("NOT_A_REAL_STATE", "CREATED")


def test_is_terminal_false_for_every_non_terminal_state() -> None:
    for state in EXECUTION_STATES:
        if state not in TERMINAL_STATES:
            assert is_terminal(state) is False

"""argus.executor.state_machine — MASTER_SPEC.md section 76 (EXECUTION
STATE MACHINE), Phase 6 (``argus-phase-6-001``).

The frozen 11-state execution-intent lifecycle and its legal-transition
graph. ``transition()`` is a pure function -- it never touches the
database; the persistence layer (``argus.executor.persistence``) is
responsible for making the actual state write plus its audit-trail row
transactional. An illegal transition (including into/out of a terminal
state) always raises :class:`IllegalTransitionError` rather than
silently applying or corrupting state.
"""

from __future__ import annotations

from argus.domain.execution_intents import (
    STATE_ATTESTING,
    STATE_CONFIRMED,
    STATE_CREATED,
    STATE_FAILED,
    STATE_ORDER_READY,
    STATE_ORDER_REQUESTED,
    STATE_REJECTED,
    STATE_SIGNED,
    STATE_SUBMITTED,
    STATE_UNKNOWN,
    STATE_VALIDATING,
)

_LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    STATE_CREATED: frozenset({STATE_VALIDATING}),
    STATE_VALIDATING: frozenset({STATE_ORDER_REQUESTED, STATE_REJECTED}),
    STATE_ORDER_REQUESTED: frozenset({STATE_ORDER_READY, STATE_REJECTED}),
    STATE_ORDER_READY: frozenset({STATE_ATTESTING, STATE_REJECTED}),
    STATE_ATTESTING: frozenset({STATE_SIGNED, STATE_REJECTED}),
    STATE_SIGNED: frozenset({STATE_SUBMITTED}),
    STATE_SUBMITTED: frozenset({STATE_CONFIRMED, STATE_FAILED, STATE_UNKNOWN}),
    # An ambiguous submitted transaction (section 77: crash/timeout with
    # no confirmed outcome) resolves only via reconciliation -- never a
    # blind retry back into SIGNED/SUBMITTED.
    STATE_UNKNOWN: frozenset({STATE_CONFIRMED, STATE_FAILED}),
    STATE_REJECTED: frozenset(),
    STATE_CONFIRMED: frozenset(),
    STATE_FAILED: frozenset(),
}

TERMINAL_STATES: frozenset[str] = frozenset(
    state for state, allowed in _LEGAL_TRANSITIONS.items() if not allowed
)


class IllegalTransitionError(RuntimeError):
    """Raised instead of silently applying an illegal state transition."""


class UnknownStateError(RuntimeError):
    """Raised when ``current_state`` is not one of the 11 frozen states."""


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def legal_next_states(current_state: str) -> frozenset[str]:
    if current_state not in _LEGAL_TRANSITIONS:
        raise UnknownStateError(f"unknown state: {current_state!r}")
    return _LEGAL_TRANSITIONS[current_state]


def transition(current_state: str, to_state: str) -> str:
    """Returns ``to_state`` if the transition is legal; otherwise raises
    :class:`IllegalTransitionError` (never applies a partial/illegal
    change)."""
    allowed = legal_next_states(current_state)
    if to_state not in allowed:
        raise IllegalTransitionError(
            f"{current_state} -> {to_state} is not a legal transition "
            f"(legal: {sorted(allowed) or 'none (terminal state)'})"
        )
    return to_state

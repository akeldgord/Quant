"""P6-09 (SAFETY_OR_INTEGRITY_BLOCKING): no automatic slippage escalation
-- MASTER_SPEC.md section 80, orchestrator instruction
``argus-phase-6-001``.
"""

from __future__ import annotations

from argus.executor.slippage import evaluate_retry, should_abandon


def test_request_within_ceiling_and_no_previous_attempt_is_allowed() -> None:
    decision = evaluate_retry(
        approved_ceiling_bps=100, requested_slippage_bps=50, previous_attempt_bps=None
    )
    assert decision.allowed is True
    assert decision.slippage_bps_to_use == 50


def test_request_exceeding_approved_ceiling_is_rejected() -> None:
    decision = evaluate_retry(
        approved_ceiling_bps=100, requested_slippage_bps=150, previous_attempt_bps=None
    )
    assert decision.allowed is False
    assert decision.slippage_bps_to_use is None


def test_retry_at_exactly_the_ceiling_is_allowed() -> None:
    decision = evaluate_retry(
        approved_ceiling_bps=100, requested_slippage_bps=100, previous_attempt_bps=None
    )
    assert decision.allowed is True


def test_retry_higher_than_previous_attempt_is_rejected_even_within_ceiling() -> None:
    """The core escalation-prevention rule: even a request that stays
    within the approved ceiling is rejected if it exceeds a previous
    attempt -- automatic escalation is structurally impossible."""
    decision = evaluate_retry(
        approved_ceiling_bps=200, requested_slippage_bps=150, previous_attempt_bps=100
    )
    assert decision.allowed is False


def test_retry_lower_than_previous_attempt_is_allowed() -> None:
    decision = evaluate_retry(
        approved_ceiling_bps=200, requested_slippage_bps=80, previous_attempt_bps=100
    )
    assert decision.allowed is True
    assert decision.slippage_bps_to_use == 80


def test_retry_equal_to_previous_attempt_is_allowed_not_escalation() -> None:
    decision = evaluate_retry(
        approved_ceiling_bps=200, requested_slippage_bps=100, previous_attempt_bps=100
    )
    assert decision.allowed is True


def test_repeated_retry_requests_never_compound_above_first_ceiling_hit() -> None:
    """Simulates a sequence of retries -- each must stay monotonically
    non-increasing; none may ever exceed the approved ceiling."""
    ceiling = 150
    attempts = [200, 180, 160, 140]  # first two exceed ceiling
    previous: int | None = None
    used: list[int] = []
    for requested in attempts:
        decision = evaluate_retry(
            approved_ceiling_bps=ceiling,
            requested_slippage_bps=requested,
            previous_attempt_bps=previous,
        )
        if decision.allowed:
            assert decision.slippage_bps_to_use is not None
            used.append(decision.slippage_bps_to_use)
            previous = decision.slippage_bps_to_use
    assert used == [140]
    assert all(value <= ceiling for value in used)


def test_should_abandon_when_no_viable_slippage_evidenced() -> None:
    assert should_abandon(approved_ceiling_bps=100, minimum_viable_slippage_bps=None) is True


def test_should_abandon_when_minimum_viable_exceeds_ceiling() -> None:
    assert should_abandon(approved_ceiling_bps=100, minimum_viable_slippage_bps=150) is True


def test_should_not_abandon_when_minimum_viable_within_ceiling() -> None:
    assert should_abandon(approved_ceiling_bps=100, minimum_viable_slippage_bps=80) is False

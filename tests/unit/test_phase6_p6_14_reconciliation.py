"""P6-14 (SAFETY_OR_INTEGRITY_BLOCKING): host suspend/resume
reconciliation -- MASTER_SPEC.md section 83, orchestrator instruction
``argus-phase-6-001``.

A major clock/scheduling discontinuity auto-disarms new entries; ALL
seven required dimensions must independently report HEALTHY before new
live entry may resume -- a partial recovery (even six of seven) still
blocks.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from argus.executor.reconciliation import (
    ALL_DIMENSIONS,
    DimensionStatus,
    ReconciliationChecklist,
    detect_discontinuity,
    may_resume_new_entries,
)


def test_exactly_seven_dimensions() -> None:
    assert len(ALL_DIMENSIONS) == 7
    assert len(set(ALL_DIMENSIONS)) == 7


def test_gap_within_allowance_is_not_a_discontinuity() -> None:
    assert (
        detect_discontinuity(
            observed_gap=timedelta(seconds=5), max_allowed_gap=timedelta(seconds=30)
        )
        is False
    )


def test_gap_exceeding_allowance_is_a_discontinuity() -> None:
    assert (
        detect_discontinuity(
            observed_gap=timedelta(minutes=10), max_allowed_gap=timedelta(seconds=30)
        )
        is True
    )


def _all_healthy() -> dict[str, DimensionStatus]:
    return dict.fromkeys(ALL_DIMENSIONS, "HEALTHY")


def test_all_seven_healthy_allows_resume() -> None:
    checklist = ReconciliationChecklist(statuses=_all_healthy())
    assert checklist.fully_healthy is True
    assert may_resume_new_entries(checklist) is True
    assert checklist.unhealthy_or_pending == ()


@pytest.mark.parametrize("dimension", ALL_DIMENSIONS)
def test_any_single_unhealthy_dimension_blocks_resume(dimension: str) -> None:
    statuses = _all_healthy()
    statuses[dimension] = "UNHEALTHY"
    checklist = ReconciliationChecklist(statuses=statuses)
    assert checklist.fully_healthy is False
    assert may_resume_new_entries(checklist) is False
    assert dimension in checklist.unhealthy_or_pending


@pytest.mark.parametrize("dimension", ALL_DIMENSIONS)
def test_any_single_pending_dimension_blocks_resume(dimension: str) -> None:
    statuses = _all_healthy()
    statuses[dimension] = "PENDING"
    checklist = ReconciliationChecklist(statuses=statuses)
    assert may_resume_new_entries(checklist) is False


def test_six_of_seven_healthy_still_blocks() -> None:
    statuses = _all_healthy()
    statuses[ALL_DIMENSIONS[0]] = "UNHEALTHY"
    checklist = ReconciliationChecklist(statuses=statuses)
    assert checklist.fully_healthy is False
    assert may_resume_new_entries(checklist) is False
    assert len(checklist.unhealthy_or_pending) == 1


def test_missing_dimension_from_statuses_is_treated_as_not_healthy() -> None:
    statuses: dict[str, DimensionStatus] = dict.fromkeys(ALL_DIMENSIONS[:-1], "HEALTHY")
    checklist = ReconciliationChecklist(statuses=statuses)
    assert checklist.fully_healthy is False
    assert ALL_DIMENSIONS[-1] in checklist.unhealthy_or_pending

"""Unit tests for argus.convergence.outcome_comparison (FSR-06, final spec
recovery): the required 4-class (ordinary overlap / high-surprisal
overlap / rapid confirmation / failed confirmation) outcome-comparison
statistics layer.
"""

from __future__ import annotations

from decimal import Decimal

from argus.convergence.outcome_comparison import (
    CLASS_FAILED_CONFIRMATION,
    CLASS_HIGH_SURPRISAL_OVERLAP,
    CLASS_ORDINARY_OVERLAP,
    CLASS_RAPID_CONFIRMATION,
    OUTCOME_COMPARISON_CLASSES,
    compute_executable_outcome_stats,
    compute_mark_return_summary,
)
from argus.copyability.executable_returns import ExecutableReturnResult


def _success(gross_return_pct: str) -> ExecutableReturnResult:
    return ExecutableReturnResult(
        status="SUCCESS",
        gross_return_fraction=Decimal(gross_return_pct) / 100,
        gross_return_pct=Decimal(gross_return_pct),
        cost_known=False,
    )


def _failed() -> ExecutableReturnResult:
    return ExecutableReturnResult(status="FAILED", failure_class="UNSELLABLE")


def test_all_four_classes_are_named_exactly_as_required() -> None:
    assert OUTCOME_COMPARISON_CLASSES == (
        CLASS_ORDINARY_OVERLAP,
        CLASS_HIGH_SURPRISAL_OVERLAP,
        CLASS_RAPID_CONFIRMATION,
        CLASS_FAILED_CONFIRMATION,
    )


def test_empty_member_list_is_insufficient_never_a_fabricated_zero() -> None:
    stats = compute_executable_outcome_stats([])
    assert stats.member_count == 0
    assert stats.insufficient_executable_sample is True
    assert stats.mean_return_pct is None


def test_no_eligible_evidence_is_insufficient_executable_sample() -> None:
    stats = compute_executable_outcome_stats([None, None, None])
    assert stats.member_count == 3
    assert stats.eligible_count == 0
    assert stats.insufficient_executable_sample is True
    assert stats.mean_return_pct is None
    assert stats.no_route_unsellable_missing_rate is None


def test_deterministic_fixture_known_outcomes_produce_exact_statistics() -> None:
    # Two SUCCESS returns (+50%, -10%), one FAILED (unsellable), one
    # member with no evidence at all.
    outcomes = [_success("50"), _success("-10"), _failed(), None]
    stats = compute_executable_outcome_stats(outcomes)
    assert stats.member_count == 4
    assert stats.eligible_count == 3
    assert stats.sample_count == 2
    assert stats.insufficient_executable_sample is False
    assert stats.mean_return_pct == Decimal("20")
    assert stats.median_return_pct == Decimal("20")
    assert stats.win_rate == Decimal("0.5")
    # 1 of the 3 eligible (the FAILED one) never resolved to a usable return.
    assert stats.no_route_unsellable_missing_rate == Decimal("1") / Decimal("3")


def test_all_eligible_but_none_successful_reports_no_route_rate_of_one() -> None:
    stats = compute_executable_outcome_stats([_failed(), _failed()])
    assert stats.eligible_count == 2
    assert stats.sample_count == 0
    assert stats.insufficient_executable_sample is False
    assert stats.mean_return_pct is None
    assert stats.no_route_unsellable_missing_rate == Decimal("1")


def test_mark_return_summary_is_computed_separately_and_never_substitutes() -> None:
    executable_stats = compute_executable_outcome_stats([None, None])
    assert executable_stats.insufficient_executable_sample is True

    mark = compute_mark_return_summary([Decimal("30"), Decimal("10"), None])
    assert mark.sample_count == 2
    assert mark.mean_return_pct == Decimal("20")
    # The mark summary is unaffected by, and never substituted into, the
    # (still insufficient) executable stats.
    assert executable_stats.mean_return_pct is None


def test_mark_return_summary_empty_is_honestly_none() -> None:
    mark = compute_mark_return_summary([None, None])
    assert mark.sample_count == 0
    assert mark.mean_return_pct is None

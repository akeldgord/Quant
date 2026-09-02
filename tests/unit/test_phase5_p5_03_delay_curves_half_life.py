"""P5-03 (SPEC_BLOCKING): delay curves/half-life -- MASTER_SPEC.md
section 50, mechanic M3 (``argus.copyability.delay_curves``),
orchestrator instruction ``argus-phase-5-001``, remediated per
``argus-phase-5-remediation-001`` finding F5-02 (real cohort-identity
enforcement -- notional/quote-mint/horizon/evidence-class must match
across every compared point, never silently trusted).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from argus.copyability.delay_curves import (
    CohortKey,
    DelayObservation,
    DelayPoint,
    IncompatibleCohortError,
    build_delay_curve,
    compute_half_life,
    decimal_median,
)

COHORT = CohortKey(
    notional_raw=100_000_000,
    quote_mint="SOL",
    horizon_label="5m",
    evidence_class="AUTHENTIC_PROSPECTIVE",
)
OTHER_HORIZON_COHORT = CohortKey(
    notional_raw=100_000_000,
    quote_mint="SOL",
    horizon_label="30m",
    evidence_class="AUTHENTIC_PROSPECTIVE",
)
OTHER_NOTIONAL_COHORT = CohortKey(
    notional_raw=200_000_000,
    quote_mint="SOL",
    horizon_label="5m",
    evidence_class="AUTHENTIC_PROSPECTIVE",
)


def _obs(
    event_id: str, label: str, seconds: int, value: str, cohort: CohortKey = COHORT
) -> DelayObservation:
    return DelayObservation(event_id, label, seconds, Decimal(value), cohort)


def _point(
    label: str, seconds: int, value: str, n: int = 1, cohort: CohortKey = COHORT
) -> DelayPoint:
    return DelayPoint(label, seconds, Decimal(value), n, (f"e-{label}",), cohort)


def test_complete_six_delay_matched_cohort_builds_curve() -> None:
    obs = [
        _obs("e1", "1s", 1, "0.4"),
        _obs("e2", "5s", 5, "0.2"),
        _obs("e3", "15s", 15, "0.1"),
        _obs("e4", "30s", 30, "0.05"),
        _obs("e5", "60s", 60, "0.02"),
        _obs("e6", "300s", 300, "0.01"),
    ]
    curve = build_delay_curve(obs)
    assert [p.target_label for p in curve] == ["1s", "5s", "15s", "30s", "60s", "300s"]
    assert all(p.n == 1 for p in curve)
    assert all(p.cohort == COHORT for p in curve)


def test_target_1s_actual_2_7s_scheduling_delay_preserved_by_caller() -> None:
    """M3 trusts the caller's own target_seconds; the scheduling-delay
    distinction itself is M1/M2's responsibility (target_due_at vs
    requested_at) -- this test proves target_seconds is never silently
    replaced by an actual response time."""
    obs = _obs("e1", "1s", 1, "0.4")
    assert obs.target_seconds == 1  # not 2.7 -- the nominal target label


def test_missing_delay_produces_fewer_points_never_fabricated() -> None:
    obs = [_obs("e1", "1s", 1, "0.4"), _obs("e2", "5s", 5, "0.2")]
    curve = build_delay_curve(obs)
    assert len(curve) == 2
    assert {p.target_label for p in curve} == {"1s", "5s"}


def test_repeated_event_at_same_label_counted_once_distinct_event() -> None:
    obs = [
        _obs("e1", "1s", 1, "0.4"),
        _obs("e1", "1s", 1, "0.4"),  # same event, duplicate probe
        _obs("e2", "1s", 1, "0.2"),
    ]
    curve = build_delay_curve(obs)
    assert len(curve) == 1
    assert curve[0].n == 2  # distinct events e1, e2 -- not 3 probes


def test_incompatible_horizon_cohort_rejected_by_build_delay_curve() -> None:
    obs = [
        _obs("e1", "1s", 1, "0.4", cohort=COHORT),
        _obs("e2", "5s", 5, "0.2", cohort=OTHER_HORIZON_COHORT),
    ]
    with pytest.raises(IncompatibleCohortError):
        build_delay_curve(obs)


def test_incompatible_notional_cohort_rejected_by_build_delay_curve() -> None:
    obs = [
        _obs("e1", "1s", 1, "0.4", cohort=COHORT),
        _obs("e2", "5s", 5, "0.2", cohort=OTHER_NOTIONAL_COHORT),
    ]
    with pytest.raises(IncompatibleCohortError):
        build_delay_curve(obs)


def test_half_life_rejects_points_from_different_cohorts_f5_02() -> None:
    """F5-02: event A at 1s=.4 and event B at 5s=.2 from DIFFERENT
    cohorts (e.g. different horizon) must yield INSUFFICIENT_COMPARABLE_
    EVIDENCE, never a silently-computed PEAK_FOUND."""
    points = [
        _point("1s", 1, "0.4", cohort=COHORT),
        _point("5s", 5, "0.2", cohort=OTHER_HORIZON_COHORT),
    ]
    result = compute_half_life(points)
    assert result.outcome == "INSUFFICIENT_COMPARABLE_EVIDENCE"
    assert result.half_life_seconds is None


def test_half_life_worked_example_1_peak1_crossing5_elapsed4() -> None:
    points = [_point("1s", 1, "0.4"), _point("5s", 5, "0.2"), _point("15s", 15, "0.1")]
    result = compute_half_life(points)
    assert result.outcome == "PEAK_FOUND"
    assert result.peak_seconds == 1
    assert result.peak_return_fraction == Decimal("0.4")
    assert result.crossing_seconds == 5
    assert result.crossing_delay_from_first_seen_seconds == 5
    assert result.half_life_seconds == Decimal(4)


def test_half_life_worked_example_2_best5_crossing15_elapsed10() -> None:
    points = [_point("1s", 1, "0.1"), _point("5s", 5, "0.4"), _point("15s", 15, "0.2")]
    result = compute_half_life(points)
    assert result.outcome == "PEAK_FOUND"
    assert result.peak_seconds == 5
    assert result.crossing_seconds == 15
    assert result.half_life_seconds == Decimal(10)


def test_tied_peaks_break_by_earliest_delay() -> None:
    points = [_point("1s", 1, "0.4"), _point("5s", 5, "0.4"), _point("15s", 15, "0.1")]
    result = compute_half_life(points)
    assert result.peak_seconds == 1  # earliest of the tied maxima


def test_no_positive_values_yields_no_positive_signal() -> None:
    points = [_point("1s", 1, "-0.1"), _point("5s", 5, "-0.2"), _point("15s", 15, "0")]
    result = compute_half_life(points)
    assert result.outcome == "NO_POSITIVE_SIGNAL"
    assert result.half_life_seconds is None


def test_no_later_crossing_is_right_censored_with_null_half_life() -> None:
    points = [_point("1s", 1, "0.1"), _point("5s", 5, "0.4"), _point("15s", 15, "0.3")]
    result = compute_half_life(points)
    assert result.outcome == "RIGHT_CENSORED"
    assert result.half_life_seconds is None
    assert result.peak_seconds == 5


def test_fewer_than_two_points_is_insufficient_comparable_evidence() -> None:
    result = compute_half_life([_point("1s", 1, "0.4")])
    assert result.outcome == "INSUFFICIENT_COMPARABLE_EVIDENCE"
    assert result.half_life_seconds is None


def test_no_points_is_insufficient_comparable_evidence() -> None:
    result = compute_half_life([])
    assert result.outcome == "INSUFFICIENT_COMPARABLE_EVIDENCE"


def test_decimal_median_even_and_odd_counts() -> None:
    assert decimal_median([Decimal(1), Decimal(2), Decimal(3)]) == Decimal(2)
    assert decimal_median([Decimal(1), Decimal(2), Decimal(3), Decimal(4)]) == Decimal("2.5")


def test_best_delay_recorded_even_when_not_earliest() -> None:
    """The peak need not be the earliest observed delay -- it is whichever
    delay achieves the maximum positive median."""
    points = [_point("1s", 1, "0.05"), _point("5s", 5, "0.05"), _point("60s", 60, "0.9")]
    result = compute_half_life(points)
    assert result.peak_seconds == 60

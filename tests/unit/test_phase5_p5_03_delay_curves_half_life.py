"""P5-03 (SPEC_BLOCKING): delay curves/half-life -- MASTER_SPEC.md
section 50, mechanic M3 (``argus.copyability.delay_curves``),
orchestrator instruction ``argus-phase-5-001``.
"""

from __future__ import annotations

from decimal import Decimal

from argus.copyability.delay_curves import (
    DelayObservation,
    DelayPoint,
    build_delay_curve,
    compute_half_life,
    decimal_median,
)


def _point(label: str, seconds: int, value: str, n: int = 1) -> DelayPoint:
    return DelayPoint(label, seconds, Decimal(value), n, (f"e-{label}",))


def test_complete_six_delay_matched_cohort_builds_curve() -> None:
    obs = [
        DelayObservation("e1", "1s", 1, Decimal("0.4")),
        DelayObservation("e2", "5s", 5, Decimal("0.2")),
        DelayObservation("e3", "15s", 15, Decimal("0.1")),
        DelayObservation("e4", "30s", 30, Decimal("0.05")),
        DelayObservation("e5", "60s", 60, Decimal("0.02")),
        DelayObservation("e6", "300s", 300, Decimal("0.01")),
    ]
    curve = build_delay_curve(obs)
    assert [p.target_label for p in curve] == ["1s", "5s", "15s", "30s", "60s", "300s"]
    assert all(p.n == 1 for p in curve)


def test_target_1s_actual_2_7s_scheduling_delay_preserved_by_caller() -> None:
    """M3 trusts the caller's own target_seconds; the scheduling-delay
    distinction itself is M1/M2's responsibility (target_due_at vs
    requested_at) -- this test proves target_seconds is never silently
    replaced by an actual response time."""
    obs = DelayObservation("e1", "1s", 1, Decimal("0.4"))
    assert obs.target_seconds == 1  # not 2.7 -- the nominal target label


def test_missing_delay_produces_fewer_points_never_fabricated() -> None:
    obs = [
        DelayObservation("e1", "1s", 1, Decimal("0.4")),
        DelayObservation("e2", "5s", 5, Decimal("0.2")),
    ]
    curve = build_delay_curve(obs)
    assert len(curve) == 2
    assert {p.target_label for p in curve} == {"1s", "5s"}


def test_repeated_event_at_same_label_counted_once_distinct_event() -> None:
    obs = [
        DelayObservation("e1", "1s", 1, Decimal("0.4")),
        DelayObservation("e1", "1s", 1, Decimal("0.4")),  # same event, duplicate probe
        DelayObservation("e2", "1s", 1, Decimal("0.2")),
    ]
    curve = build_delay_curve(obs)
    assert len(curve) == 1
    assert curve[0].n == 2  # distinct events e1, e2 -- not 3 probes


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

"""Unit tests for argus.convergence.stats (MASTER_SPEC.md Phase 8,
section 59 CONVERGENCE SURPRISE): non-parametric empirical overlap
probability/surprisal and disclosed calibration-confidence buckets.
"""

from __future__ import annotations

import math
from decimal import Decimal

from argus.convergence.stats import (
    CALIBRATION_HIGH,
    CALIBRATION_INSUFFICIENT_SAMPLE,
    CALIBRATION_LOW,
    CALIBRATION_MEDIUM,
    calibration_confidence,
    compute_overlap_surprise,
)


def test_calibration_confidence_buckets() -> None:
    assert calibration_confidence(0) == CALIBRATION_INSUFFICIENT_SAMPLE
    assert calibration_confidence(9) == CALIBRATION_INSUFFICIENT_SAMPLE
    assert calibration_confidence(10) == CALIBRATION_LOW
    assert calibration_confidence(29) == CALIBRATION_LOW
    assert calibration_confidence(30) == CALIBRATION_MEDIUM
    assert calibration_confidence(99) == CALIBRATION_MEDIUM
    assert calibration_confidence(100) == CALIBRATION_HIGH
    assert calibration_confidence(1000) == CALIBRATION_HIGH


def test_empty_history_yields_insufficient_sample_and_probability_one() -> None:
    result = compute_overlap_surprise(Decimal("2.0"), [])
    assert result.sample_size == 0
    assert result.calibration_confidence == CALIBRATION_INSUFFICIENT_SAMPLE
    assert result.expected_overlap == Decimal(0)
    # (1 + 0) / (1 + 0) = 1 -- no smoothing evidence against it yet.
    assert result.empirical_probability == Decimal(1)
    assert result.surprisal == Decimal(0)


def test_expected_overlap_is_mean_of_historical_overlaps() -> None:
    history = [Decimal("1.0"), Decimal("2.0"), Decimal("3.0")]
    result = compute_overlap_surprise(Decimal("2.0"), history)
    assert result.expected_overlap == Decimal(2)
    assert result.sample_size == 3


def test_unprecedented_observation_never_collapses_probability_to_zero() -> None:
    history = [Decimal("1.0")] * 50
    result = compute_overlap_surprise(Decimal("10.0"), history)
    # (1 + 0) / (1 + 50) = 1/51 -- never exactly zero.
    assert result.empirical_probability == Decimal(1) / Decimal(51)
    assert result.empirical_probability > 0
    expected_surprisal = -math.log(1 / 51)
    assert abs(float(result.surprisal) - expected_surprisal) < 1e-9


def test_ordinary_observation_has_low_surprisal() -> None:
    history = [Decimal("2.0")] * 100
    result = compute_overlap_surprise(Decimal("2.0"), history)
    # (1 + 100) / (1 + 100) = 1 -- every prior episode was at or above this
    # one's own value, so it is entirely unsurprising.
    assert result.empirical_probability == Decimal(1)
    assert result.surprisal == Decimal(0)


def test_higher_observed_overlap_never_decreases_surprisal() -> None:
    history = [Decimal(str(v)) for v in range(1, 21)]
    low = compute_overlap_surprise(Decimal("5.0"), history)
    high = compute_overlap_surprise(Decimal("15.0"), history)
    assert high.surprisal >= low.surprisal
    assert high.empirical_probability <= low.empirical_probability


def test_surprisal_is_nonnegative_for_various_inputs() -> None:
    history = [Decimal("1.0"), Decimal("4.0"), Decimal("2.5")]
    for observed in (Decimal("0.5"), Decimal("2.0"), Decimal("10.0")):
        result = compute_overlap_surprise(observed, history)
        assert result.surprisal >= 0
        assert Decimal(0) < result.empirical_probability <= Decimal(1)

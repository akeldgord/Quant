"""Unit tests for argus.prediction.validation (MASTER_SPEC.md Phase 11,
PREDICT INFORMED ORDER FLOW): strict temporal (never random) train/test
splitting and the minimum-sample gate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from argus.prediction.validation import (
    has_adequate_sample,
    temporal_train_test_split,
)

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)


def test_split_is_strictly_chronological_regardless_of_input_order() -> None:
    timestamps = [
        _NOW + timedelta(minutes=3),
        _NOW,
        _NOW + timedelta(minutes=1),
        _NOW + timedelta(minutes=2),
    ]
    split = temporal_train_test_split(timestamps, train_fraction=Decimal("0.5"))
    assert split.train_indices == [1, 2]
    assert split.test_indices == [3, 0]
    assert max(timestamps[i] for i in split.train_indices) <= min(
        timestamps[i] for i in split.test_indices
    )


def test_split_sizes_reflect_train_fraction() -> None:
    timestamps = [_NOW + timedelta(minutes=i) for i in range(10)]
    split = temporal_train_test_split(timestamps, train_fraction=Decimal("0.7"))
    assert len(split.train_indices) == 7
    assert len(split.test_indices) == 3


@pytest.mark.parametrize(
    "train_fraction", [Decimal(0), Decimal(1), Decimal("-0.1"), Decimal("1.1")]
)
def test_split_rejects_train_fraction_outside_open_interval(train_fraction: Decimal) -> None:
    with pytest.raises(ValueError, match="train_fraction"):
        temporal_train_test_split([_NOW], train_fraction=train_fraction)


def test_has_adequate_sample_true_when_both_classes_meet_minimum() -> None:
    y_train = [True, True, False, False]
    y_test = [True, False]
    assert has_adequate_sample(y_train, y_test, min_class_count=1) is True


def test_has_adequate_sample_false_when_train_missing_a_class() -> None:
    y_train = [True, True, True]
    y_test = [True, False]
    assert has_adequate_sample(y_train, y_test, min_class_count=1) is False


def test_has_adequate_sample_false_when_test_missing_a_class() -> None:
    y_train = [True, False]
    y_test = [True, True]
    assert has_adequate_sample(y_train, y_test, min_class_count=1) is False


def test_has_adequate_sample_respects_min_class_count_threshold() -> None:
    y_train = [True, True, False, False]
    y_test = [True, True, False, False]
    assert has_adequate_sample(y_train, y_test, min_class_count=2) is True
    assert has_adequate_sample(y_train, y_test, min_class_count=3) is False

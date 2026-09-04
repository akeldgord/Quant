"""Unit tests for argus.prediction.validation (MASTER_SPEC.md Phase 11,
PREDICT INFORMED ORDER FLOW): FSR-11's deterministic purged + embargoed
train/test split and the minimum-sample gate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from argus.prediction.validation import has_adequate_sample, purged_embargoed_split

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_HORIZON = timedelta(minutes=5)


def test_boundary_crossing_label_is_purged() -> None:
    """A row whose OWN label window straddles the split boundary S
    (``entered_at < S < entered_at + horizon``) is present in NEITHER
    split -- purged, never silently folded into training."""
    timestamps = [
        _NOW,  # train: + horizon (5m) <= boundary (10m)
        _NOW + timedelta(minutes=1),  # train: +horizon (6m) <= boundary (10m)
        _NOW + timedelta(minutes=10),  # == boundary itself; +horizon crosses it -> purged
        _NOW + timedelta(minutes=20),  # >= boundary + embargo -> test
    ]
    split = purged_embargoed_split(timestamps, horizon=_HORIZON, train_fraction=Decimal("0.5"))
    assert split.boundary == _NOW + timedelta(minutes=10)
    assert split.train_indices == [0, 1]
    assert split.test_indices == [3]
    assert split.purged_count == 1


def test_row_inside_embargo_gap_absent_from_test() -> None:
    """A row that starts strictly after the boundary but before the
    embargo elapses (``S <= entered_at < S + embargo``) is purged too,
    even though its own window does not "cross" S in the strict sense --
    it must never leak into the test split."""
    timestamps = [
        _NOW,
        _NOW + timedelta(minutes=1),
        _NOW + timedelta(minutes=10),  # boundary
        _NOW + timedelta(minutes=12),  # inside [S, S+embargo) -- purged, not test
        _NOW + timedelta(minutes=20),  # >= S + embargo -- test
    ]
    split = purged_embargoed_split(timestamps, horizon=_HORIZON, train_fraction=Decimal("0.4"))
    assert (_NOW + timedelta(minutes=12)) not in [timestamps[i] for i in split.test_indices]
    assert split.test_indices == [4]
    assert split.purged_count == 2


def test_earliest_test_row_satisfies_embargo() -> None:
    timestamps = [_NOW + timedelta(minutes=i) for i in range(20)]
    split = purged_embargoed_split(timestamps, horizon=_HORIZON, train_fraction=Decimal("0.5"))
    assert split.test_indices
    earliest_test = min(timestamps[i] for i in split.test_indices)
    assert earliest_test >= split.boundary + split.embargo


def test_embargo_is_exactly_the_horizon() -> None:
    timestamps = [_NOW + timedelta(minutes=i) for i in range(10)]
    split = purged_embargoed_split(timestamps, horizon=_HORIZON, train_fraction=Decimal("0.5"))
    assert split.embargo == _HORIZON


def test_no_row_occurs_in_both_splits() -> None:
    timestamps = [_NOW + timedelta(minutes=i) for i in range(30)]
    split = purged_embargoed_split(timestamps, horizon=_HORIZON, train_fraction=Decimal("0.6"))
    assert set(split.train_indices).isdisjoint(split.test_indices)


def test_mutating_a_test_period_timestamp_cannot_alter_training_split() -> None:
    """Mutating a LATER (test-period) event's own timestamp -- while it
    stays within the test region -- must never change which rows the
    training split contains, nor the boundary itself: no training label
    may depend on an event inside the test/embargo region (FSR-11)."""
    base_timestamps = [
        _NOW,
        _NOW + timedelta(minutes=1),
        _NOW + timedelta(minutes=10),
        _NOW + timedelta(minutes=20),
    ]
    base_split = purged_embargoed_split(
        base_timestamps, horizon=_HORIZON, train_fraction=Decimal("0.5")
    )

    mutated_timestamps = list(base_timestamps)
    mutated_timestamps[3] = _NOW + timedelta(minutes=45)  # still >= boundary + embargo
    mutated_split = purged_embargoed_split(
        mutated_timestamps, horizon=_HORIZON, train_fraction=Decimal("0.5")
    )

    assert mutated_split.boundary == base_split.boundary
    assert mutated_split.train_indices == base_split.train_indices
    assert mutated_split.purged_count == base_split.purged_count


def test_train_and_test_ranges_reflect_actual_membership() -> None:
    timestamps = [_NOW + timedelta(minutes=i) for i in range(30)]
    split = purged_embargoed_split(timestamps, horizon=_HORIZON, train_fraction=Decimal("0.5"))
    assert split.train_range is not None
    assert split.train_range[0] == min(timestamps[i] for i in split.train_indices)
    assert split.train_range[1] == max(timestamps[i] for i in split.train_indices)
    assert split.test_range is not None
    assert split.test_range[0] == min(timestamps[i] for i in split.test_indices)
    assert split.test_range[1] == max(timestamps[i] for i in split.test_indices)


def test_empty_split_side_has_none_range() -> None:
    """A horizon far longer than the whole timestamp spread purges
    everything (no row's window resolves before the boundary, and none
    starts late enough to clear the embargo) -- both ranges are honestly
    ``None``, never a fabricated range over zero rows."""
    timestamps = [_NOW, _NOW + timedelta(seconds=1)]
    split = purged_embargoed_split(
        timestamps, horizon=timedelta(days=1), train_fraction=Decimal("0.5")
    )
    assert split.train_indices == []
    assert split.test_indices == []
    assert split.train_range is None
    assert split.test_range is None


@pytest.mark.parametrize(
    "train_fraction", [Decimal(0), Decimal(1), Decimal("-0.1"), Decimal("1.1")]
)
def test_split_rejects_train_fraction_outside_open_interval(train_fraction: Decimal) -> None:
    with pytest.raises(ValueError, match="train_fraction"):
        purged_embargoed_split([_NOW], horizon=_HORIZON, train_fraction=train_fraction)


def test_split_rejects_empty_timestamps() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        purged_embargoed_split([], horizon=_HORIZON, train_fraction=Decimal("0.5"))


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

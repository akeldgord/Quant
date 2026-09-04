"""argus.prediction.validation -- MASTER_SPEC.md Phase 11 (PREDICT
INFORMED ORDER FLOW): "Use strict temporal validation." FSR-11: a plain
chronological split is not enough on its own when labels have an
overlapping forward-looking window -- a training row whose OWN label
window crosses the split boundary would depend on an event that occurred
during (or after) the test period, a real leak even though the row's own
``entered_at`` is chronologically "before" the boundary. This module
instead performs a deterministic PURGED + EMBARGOED split (MASTER_SPEC
section 101's own prohibition on random splits of overlapping temporal
labels, made concrete): every training row's complete label window must
resolve before the boundary, every test row must begin only after an
embargo of at least the horizon's own length past the boundary, and any
row that satisfies neither is purged -- present in neither split, never
silently folded into one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal


@dataclass(frozen=True)
class PurgedEmbargoedSplit:
    train_indices: list[int]
    test_indices: list[int]
    boundary: datetime
    embargo: timedelta
    purged_count: int
    train_range: tuple[datetime, datetime] | None
    test_range: tuple[datetime, datetime] | None


def purged_embargoed_split(
    timestamps: list[datetime], *, horizon: timedelta, train_fraction: Decimal
) -> PurgedEmbargoedSplit:
    """FSR-11. ``boundary`` ``S`` is the same fractional chronological
    quantile the old plain split used (the timestamp at ``train_fraction``
    through the sorted population), but membership is now decided by each
    row's own COMPLETE label window relative to ``S``, not by its
    ``entered_at`` alone:

    - train: ``entered_at + horizon <= S`` (the label is fully resolved
      strictly before the boundary);
    - test: ``entered_at >= S + embargo`` (``embargo`` is exactly
      ``horizon`` here -- the spec's own disclosed minimum, "a stricter
      deterministic embargo is allowed; a weaker one is not");
    - purged: everything else -- a row whose own label window crosses
      ``S``, or that falls inside the embargo gap -- present in NEITHER
      split.
    """
    if not (Decimal(0) < train_fraction < Decimal(1)):
        raise ValueError("train_fraction must be strictly between 0 and 1")
    if not timestamps:
        raise ValueError("timestamps must be non-empty")

    order = sorted(range(len(timestamps)), key=lambda i: timestamps[i])
    split_point = int(Decimal(len(order)) * train_fraction)
    if split_point >= len(order):
        split_point = len(order) - 1
    boundary = timestamps[order[split_point]]
    embargo = horizon

    train_indices: list[int] = []
    test_indices: list[int] = []
    purged_count = 0
    for i in order:
        t = timestamps[i]
        if t + horizon <= boundary:
            train_indices.append(i)
        elif t >= boundary + embargo:
            test_indices.append(i)
        else:
            purged_count += 1

    train_range = (
        (min(timestamps[i] for i in train_indices), max(timestamps[i] for i in train_indices))
        if train_indices
        else None
    )
    test_range = (
        (min(timestamps[i] for i in test_indices), max(timestamps[i] for i in test_indices))
        if test_indices
        else None
    )
    return PurgedEmbargoedSplit(
        train_indices=train_indices,
        test_indices=test_indices,
        boundary=boundary,
        embargo=embargo,
        purged_count=purged_count,
        train_range=train_range,
        test_range=test_range,
    )


def has_adequate_sample(y_train: list[bool], y_test: list[bool], *, min_class_count: int) -> bool:
    """PHASE 11's own opening instruction: "Only begin with adequate clean
    prospective sample." True only when BOTH splits contain at least
    ``min_class_count`` of EACH class -- a split with too few (or zero)
    positives, or too few negatives, cannot support a meaningful AUC-ROC
    or a trustworthy fit; the caller records ``INSUFFICIENT_SAMPLE``
    rather than fit/evaluate on it."""
    train_positive = sum(1 for v in y_train if v)
    train_negative = len(y_train) - train_positive
    test_positive = sum(1 for v in y_test if v)
    test_negative = len(y_test) - test_positive
    return (
        train_positive >= min_class_count
        and train_negative >= min_class_count
        and test_positive >= min_class_count
        and test_negative >= min_class_count
    )

"""argus.prediction.validation -- MASTER_SPEC.md Phase 11 (PREDICT
INFORMED ORDER FLOW): "Use strict temporal validation." Splits
chronologically -- train on strictly earlier observations, test on
strictly later ones -- never a random shuffle (MASTER_SPEC's own
explicit rule elsewhere: "Never use random train/test splitting when
overlapping forward-return windows could leak information").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class TemporalSplit:
    train_indices: list[int]
    test_indices: list[int]


def temporal_train_test_split(
    timestamps: list[datetime], *, train_fraction: Decimal
) -> TemporalSplit:
    if not (Decimal(0) < train_fraction < Decimal(1)):
        raise ValueError("train_fraction must be strictly between 0 and 1")
    order = sorted(range(len(timestamps)), key=lambda i: timestamps[i])
    split_point = int(Decimal(len(order)) * train_fraction)
    return TemporalSplit(train_indices=order[:split_point], test_indices=order[split_point:])


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

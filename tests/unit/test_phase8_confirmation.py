"""Unit tests for argus.convergence.confirmation (MASTER_SPEC.md Phase 8,
section 60 DOG-THAT-DIDN'T-BARK SIGNAL): expected confirmation window and
ABSENT/EARLY/LATE/STRONG/NORMAL classification.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from argus.convergence.confirmation import (
    OUTCOME_ABSENT,
    OUTCOME_EARLY,
    OUTCOME_LATE,
    OUTCOME_NORMAL,
    OUTCOME_STRONG,
    classify_confirmation,
    expected_confirmation_window,
)

_LEADER_AT = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)


def test_expected_confirmation_window_requires_nonempty_history() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        expected_confirmation_window([])


def test_expected_confirmation_window_single_value_degenerate() -> None:
    low, high = expected_confirmation_window([Decimal("60")])
    assert low == Decimal("60")
    assert high == Decimal("60")


def test_expected_confirmation_window_nearest_rank_percentiles() -> None:
    # 10 values 10..100; p10 nearest-rank = ceil(0.1*10)=1st smallest = 10;
    # p90 nearest-rank = ceil(0.9*10)=9th smallest = 90.
    history = [Decimal(str(v)) for v in range(10, 101, 10)]
    low, high = expected_confirmation_window(history)
    assert low == Decimal("10")
    assert high == Decimal("90")


def test_absent_when_no_follower_entry() -> None:
    result = classify_confirmation(
        leader_entered_at=_LEADER_AT,
        follower_entered_at=None,
        expected_window_low_seconds=Decimal("10"),
        expected_window_high_seconds=Decimal("90"),
        is_strong=False,
    )
    assert result.outcome == OUTCOME_ABSENT
    assert result.follower_entered_at is None
    assert result.lag_seconds is None


def test_early_when_lag_below_window_low() -> None:
    result = classify_confirmation(
        leader_entered_at=_LEADER_AT,
        follower_entered_at=_LEADER_AT + timedelta(seconds=5),
        expected_window_low_seconds=Decimal("10"),
        expected_window_high_seconds=Decimal("90"),
        is_strong=False,
    )
    assert result.outcome == OUTCOME_EARLY
    assert result.lag_seconds == Decimal("5")


def test_late_when_lag_above_window_high() -> None:
    result = classify_confirmation(
        leader_entered_at=_LEADER_AT,
        follower_entered_at=_LEADER_AT + timedelta(seconds=200),
        expected_window_low_seconds=Decimal("10"),
        expected_window_high_seconds=Decimal("90"),
        is_strong=False,
    )
    assert result.outcome == OUTCOME_LATE
    assert result.lag_seconds == Decimal("200")


def test_normal_when_lag_within_window() -> None:
    result = classify_confirmation(
        leader_entered_at=_LEADER_AT,
        follower_entered_at=_LEADER_AT + timedelta(seconds=50),
        expected_window_low_seconds=Decimal("10"),
        expected_window_high_seconds=Decimal("90"),
        is_strong=False,
    )
    assert result.outcome == OUTCOME_NORMAL
    assert result.lag_seconds == Decimal("50")


def test_strong_takes_precedence_over_early_and_late() -> None:
    strong_early = classify_confirmation(
        leader_entered_at=_LEADER_AT,
        follower_entered_at=_LEADER_AT + timedelta(seconds=5),
        expected_window_low_seconds=Decimal("10"),
        expected_window_high_seconds=Decimal("90"),
        is_strong=True,
    )
    assert strong_early.outcome == OUTCOME_STRONG

    strong_late = classify_confirmation(
        leader_entered_at=_LEADER_AT,
        follower_entered_at=_LEADER_AT + timedelta(seconds=200),
        expected_window_low_seconds=Decimal("10"),
        expected_window_high_seconds=Decimal("90"),
        is_strong=True,
    )
    assert strong_late.outcome == OUTCOME_STRONG


def test_absent_takes_precedence_over_strong() -> None:
    result = classify_confirmation(
        leader_entered_at=_LEADER_AT,
        follower_entered_at=None,
        expected_window_low_seconds=Decimal("10"),
        expected_window_high_seconds=Decimal("90"),
        is_strong=True,
    )
    assert result.outcome == OUTCOME_ABSENT

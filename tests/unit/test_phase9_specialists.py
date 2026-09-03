"""Unit tests for argus.counterfactual.specialists (MASTER_SPEC.md Phase
9, section 62 ENTRY AND EXIT SPECIALISTS): percentile ranking and
dominant-specialty classification.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from argus.counterfactual.specialists import (
    DISCOVERY,
    ENTRY,
    EXIT,
    VALIDATION,
    dominant_specialty,
    percentile_rank,
)


def test_percentile_rank_requires_nonempty_population() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        percentile_rank(Decimal(1), [])


def test_percentile_rank_single_member_population() -> None:
    assert percentile_rank(Decimal(5), [Decimal(5)]) == Decimal(1)


def test_percentile_rank_basic() -> None:
    population = [Decimal(1), Decimal(2), Decimal(3), Decimal(4)]
    assert percentile_rank(Decimal(2), population) == Decimal("0.5")
    assert percentile_rank(Decimal(4), population) == Decimal(1)
    assert percentile_rank(Decimal(1), population) == Decimal("0.25")


def test_dominant_specialty_none_with_fewer_than_two_scores() -> None:
    assert dominant_specialty({ENTRY: Decimal("0.9")}) is None
    assert dominant_specialty({}) is None


def test_dominant_specialty_picks_highest() -> None:
    result = dominant_specialty(
        {ENTRY: Decimal("0.2"), EXIT: Decimal("0.9"), DISCOVERY: None, VALIDATION: Decimal("0.5")}
    )
    assert result == EXIT


def test_dominant_specialty_alphabetical_tie_break() -> None:
    result = dominant_specialty({ENTRY: Decimal("0.5"), EXIT: Decimal("0.5")})
    assert result == ENTRY

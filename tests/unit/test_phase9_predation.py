"""Unit tests for argus.counterfactual.predation (MASTER_SPEC.md Phase 9,
section 61 PREDATION DETECTION): disclosed V1 heuristic composite.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from argus.counterfactual.predation import (
    compute_predation_score,
    normalized_follower_influx,
)


def test_normalized_follower_influx_caps_at_one() -> None:
    assert normalized_follower_influx(Decimal(20), cap=Decimal(10)) == Decimal(1)


def test_normalized_follower_influx_scales_linearly() -> None:
    assert normalized_follower_influx(Decimal(5), cap=Decimal(10)) == Decimal("0.5")


def test_normalized_follower_influx_rejects_nonpositive_cap() -> None:
    with pytest.raises(ValueError, match="positive"):
        normalized_follower_influx(Decimal(5), cap=Decimal(0))


def test_predation_score_none_when_influx_missing() -> None:
    assert (
        compute_predation_score(follower_influx_mean=None, exit_after_influx_rate=Decimal("0.5"))
        is None
    )


def test_predation_score_none_when_exit_rate_missing() -> None:
    assert (
        compute_predation_score(follower_influx_mean=Decimal(5), exit_after_influx_rate=None)
        is None
    )


def test_predation_score_composite() -> None:
    score = compute_predation_score(
        follower_influx_mean=Decimal(5), exit_after_influx_rate=Decimal("0.8"), cap=Decimal(10)
    )
    assert score == Decimal("0.5") * Decimal("0.8")


def test_predation_score_high_influx_and_high_exit_rate_is_high() -> None:
    score = compute_predation_score(
        follower_influx_mean=Decimal(20), exit_after_influx_rate=Decimal("1.0"), cap=Decimal(10)
    )
    assert score == Decimal(1)

"""Unit tests for argus.counterfactual.predation (MASTER_SPEC.md Phase 9,
section 61 PREDATION DETECTION): disclosed V1 heuristic composite.

FSR-07 (final spec recovery): one fixture per predation input changed
independently (follower influx, exit timing, repetition frequency,
price impact) plus a combined fixture, and an explicit check that
missing price-impact evidence never silently behaves as zero/safe.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from argus.counterfactual.predation import (
    compute_predation_score,
    normalized_follower_influx,
    normalized_price_impact,
    normalized_repetition_frequency,
)


def test_normalized_follower_influx_caps_at_one() -> None:
    assert normalized_follower_influx(Decimal(20), cap=Decimal(10)) == Decimal(1)


def test_normalized_follower_influx_scales_linearly() -> None:
    assert normalized_follower_influx(Decimal(5), cap=Decimal(10)) == Decimal("0.5")


def test_normalized_follower_influx_rejects_nonpositive_cap() -> None:
    with pytest.raises(ValueError, match="positive"):
        normalized_follower_influx(Decimal(5), cap=Decimal(0))


def test_normalized_repetition_frequency_zero_when_pattern_never_repeated() -> None:
    assert normalized_repetition_frequency(0, cap=3) == Decimal(0)


def test_normalized_repetition_frequency_scales_linearly() -> None:
    assert normalized_repetition_frequency(1, cap=3) == Decimal(1) / Decimal(3)


def test_normalized_repetition_frequency_caps_at_one() -> None:
    assert normalized_repetition_frequency(10, cap=3) == Decimal(1)


def test_normalized_price_impact_clamps_negative_to_zero() -> None:
    assert normalized_price_impact(Decimal(-5), cap=Decimal(20)) == Decimal(0)


def test_normalized_price_impact_scales_linearly() -> None:
    assert normalized_price_impact(Decimal(10), cap=Decimal(20)) == Decimal("0.5")


def test_predation_score_none_when_influx_missing() -> None:
    result = compute_predation_score(
        follower_influx_mean=None,
        exit_after_influx_rate=Decimal("0.5"),
        repeated_pattern_count=1,
        price_impact_mean=None,
    )
    assert result.score is None
    assert result.price_impact_incorporated is False


def test_predation_score_none_when_exit_rate_missing() -> None:
    result = compute_predation_score(
        follower_influx_mean=Decimal(5),
        exit_after_influx_rate=None,
        repeated_pattern_count=1,
        price_impact_mean=None,
    )
    assert result.score is None


def test_predation_score_composite_without_price_impact_uses_core_unchanged() -> None:
    # follower influx 5/10=0.5, exit rate 0.8, repetition 3/3=1.0 (capped)
    # -> core = 0.5 * 0.8 * 1.0 = 0.4, unaffected by absent price impact.
    result = compute_predation_score(
        follower_influx_mean=Decimal(5),
        exit_after_influx_rate=Decimal("0.8"),
        repeated_pattern_count=3,
        price_impact_mean=None,
        follower_influx_cap=Decimal(10),
        repetition_cap=3,
    )
    assert result.score == Decimal("0.4")
    assert result.price_impact_incorporated is False


def test_predation_score_single_repetition_is_weaker_evidence_than_repeated() -> None:
    once = compute_predation_score(
        follower_influx_mean=Decimal(5),
        exit_after_influx_rate=Decimal("0.8"),
        repeated_pattern_count=1,
        price_impact_mean=None,
        follower_influx_cap=Decimal(10),
        repetition_cap=3,
    )
    repeated = compute_predation_score(
        follower_influx_mean=Decimal(5),
        exit_after_influx_rate=Decimal("0.8"),
        repeated_pattern_count=3,
        price_impact_mean=None,
        follower_influx_cap=Decimal(10),
        repetition_cap=3,
    )
    assert once.score is not None
    assert repeated.score is not None
    assert once.score < repeated.score


def test_predation_score_never_repeated_is_zero_even_with_strong_other_evidence() -> None:
    result = compute_predation_score(
        follower_influx_mean=Decimal(20),
        exit_after_influx_rate=Decimal("1.0"),
        repeated_pattern_count=0,
        price_impact_mean=None,
        follower_influx_cap=Decimal(10),
    )
    assert result.score == Decimal(0)


def test_predation_score_with_price_impact_is_explicitly_incorporated() -> None:
    without_impact = compute_predation_score(
        follower_influx_mean=Decimal(5),
        exit_after_influx_rate=Decimal("0.8"),
        repeated_pattern_count=3,
        price_impact_mean=None,
        follower_influx_cap=Decimal(10),
        repetition_cap=3,
    )
    with_high_impact = compute_predation_score(
        follower_influx_mean=Decimal(5),
        exit_after_influx_rate=Decimal("0.8"),
        repeated_pattern_count=3,
        price_impact_mean=Decimal(20),
        follower_influx_cap=Decimal(10),
        repetition_cap=3,
        price_impact_cap=Decimal(20),
    )
    assert with_high_impact.price_impact_incorporated is True
    assert without_impact.price_impact_incorporated is False
    # Maximal measured price impact raises the score above the
    # price-impact-blind core, never leaves it unchanged or zeroes it.
    assert without_impact.score is not None
    assert with_high_impact.score is not None
    assert with_high_impact.score > without_impact.score


def test_predation_score_zero_price_impact_still_keeps_half_weight_of_core() -> None:
    # Absent price impact is honestly reported as not incorporated; a
    # genuinely MEASURED zero price impact is real evidence and must
    # never be treated identically to missing evidence -- it still
    # scales the core score down toward, but not below, half its value
    # (the blend weight), never to zero.
    core_only = compute_predation_score(
        follower_influx_mean=Decimal(5),
        exit_after_influx_rate=Decimal("0.8"),
        repeated_pattern_count=3,
        price_impact_mean=None,
        follower_influx_cap=Decimal(10),
        repetition_cap=3,
    )
    zero_impact = compute_predation_score(
        follower_influx_mean=Decimal(5),
        exit_after_influx_rate=Decimal("0.8"),
        repeated_pattern_count=3,
        price_impact_mean=Decimal(0),
        follower_influx_cap=Decimal(10),
        repetition_cap=3,
        price_impact_cap=Decimal(20),
    )
    assert zero_impact.price_impact_incorporated is True
    assert core_only.score is not None
    assert zero_impact.score == core_only.score / Decimal(2)


def test_predation_score_high_influx_and_high_exit_rate_and_repetition_is_high() -> None:
    result = compute_predation_score(
        follower_influx_mean=Decimal(20),
        exit_after_influx_rate=Decimal("1.0"),
        repeated_pattern_count=5,
        price_impact_mean=None,
        follower_influx_cap=Decimal(10),
        repetition_cap=3,
    )
    assert result.score == Decimal(1)


def test_predation_score_all_four_inputs_combined_at_maximum_is_one() -> None:
    result = compute_predation_score(
        follower_influx_mean=Decimal(20),
        exit_after_influx_rate=Decimal("1.0"),
        repeated_pattern_count=5,
        price_impact_mean=Decimal(100),
        follower_influx_cap=Decimal(10),
        repetition_cap=3,
        price_impact_cap=Decimal(20),
    )
    assert result.score == Decimal(1)
    assert result.price_impact_incorporated is True

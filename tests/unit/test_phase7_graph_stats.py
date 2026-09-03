"""Phase 7 (ALPHA ANCESTRY): argus.graph.stats -- base-rate binomial
test, effect size, and Benjamini-Hochberg FDR correction.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from argus.graph.stats import benjamini_hochberg, binomial_upper_tail_p_value, effect_size_z


def test_binomial_p_value_k_zero_is_one() -> None:
    assert binomial_upper_tail_p_value(k=0, n=10, p=Decimal("0.5")) == Decimal(1)


def test_binomial_p_value_k_exceeds_n_is_zero() -> None:
    assert binomial_upper_tail_p_value(k=11, n=10, p=Decimal("0.5")) == Decimal(0)


def test_binomial_p_value_fair_coin_all_heads_is_small() -> None:
    p = binomial_upper_tail_p_value(k=10, n=10, p=Decimal("0.5"))
    assert p == pytest.approx(1 / 1024, rel=1e-6)


def test_binomial_p_value_matches_hand_computed_example() -> None:
    # P(X >= 3) for X ~ Binomial(5, 0.5) = C(5,3)+C(5,4)+C(5,5) over 32 = 16/32 = 0.5
    p = binomial_upper_tail_p_value(k=3, n=5, p=Decimal("0.5"))
    assert p == pytest.approx(0.5, rel=1e-9)


def test_binomial_p_value_zero_probability_never_exceeds() -> None:
    assert binomial_upper_tail_p_value(k=1, n=10, p=Decimal(0)) == Decimal(0)


def test_binomial_p_value_certain_probability_always_exceeds() -> None:
    assert binomial_upper_tail_p_value(k=10, n=10, p=Decimal(1)) == Decimal(1)


def test_binomial_p_value_large_n_uses_normal_approximation() -> None:
    # n=1000, p=0.1 -> mean=100, std=~9.49. k=100 (at the mean) should be
    # close to 0.5 under the normal approximation.
    p = binomial_upper_tail_p_value(k=100, n=1000, p=Decimal("0.1"))
    assert Decimal("0.3") < p < Decimal("0.7")


def test_binomial_p_value_rejects_out_of_range_probability() -> None:
    with pytest.raises(ValueError):
        binomial_upper_tail_p_value(k=1, n=10, p=Decimal("1.5"))


def test_effect_size_z_positive_when_observed_exceeds_expected() -> None:
    z = effect_size_z(observed=10, expected=Decimal(5), variance=Decimal(4))
    assert z == Decimal("2.5")


def test_effect_size_z_none_for_zero_variance() -> None:
    assert effect_size_z(observed=5, expected=Decimal(5), variance=Decimal(0)) is None


def test_benjamini_hochberg_empty_input() -> None:
    assert benjamini_hochberg([]) == []


def test_benjamini_hochberg_single_value_q_equals_p() -> None:
    results = benjamini_hochberg([Decimal("0.03")])
    assert results[0].q_value == Decimal("0.03")


def test_benjamini_hochberg_preserves_input_order() -> None:
    p_values = [Decimal("0.20"), Decimal("0.01"), Decimal("0.10")]
    results = benjamini_hochberg(p_values)
    assert [r.p_value for r in results] == p_values


def test_benjamini_hochberg_monotonic_by_rank() -> None:
    """q-values, when read in ascending p-value order, must never
    decrease -- the standard BH step-up monotonicity guarantee."""
    p_values = [Decimal("0.01"), Decimal("0.02"), Decimal("0.03"), Decimal("0.50")]
    results = benjamini_hochberg(p_values)
    ordered_by_p = sorted(results, key=lambda r: r.p_value)
    q_values = [r.q_value for r in ordered_by_p]
    assert q_values == sorted(q_values)


def test_benjamini_hochberg_matches_hand_computed_example() -> None:
    # Classic textbook example: p = [0.01, 0.04, 0.03, 0.005], m=4.
    # Sorted: 0.005(1), 0.01(2), 0.03(3), 0.04(4).
    # raw q: 0.005*4/1=0.02, 0.01*4/2=0.02, 0.03*4/3=0.04, 0.04*4/4=0.04
    # running min from the end: rank4=0.04, rank3=min(0.04,0.04)=0.04,
    # rank2=min(0.04,0.02)=0.02, rank1=min(0.02,0.02)=0.02
    p_values = [Decimal("0.01"), Decimal("0.04"), Decimal("0.03"), Decimal("0.005")]
    results = benjamini_hochberg(p_values)
    q_by_p = {str(r.p_value): r.q_value for r in results}
    assert q_by_p["0.01"] == Decimal("0.02")
    assert q_by_p["0.005"] == Decimal("0.02")
    assert q_by_p["0.03"] == Decimal("0.04")
    assert q_by_p["0.04"] == Decimal("0.04")


def test_benjamini_hochberg_q_value_never_exceeds_one() -> None:
    results = benjamini_hochberg([Decimal("0.9"), Decimal("0.99")])
    assert all(r.q_value <= Decimal(1) for r in results)

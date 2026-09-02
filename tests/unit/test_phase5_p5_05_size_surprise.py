"""P5-05 (SPEC_BLOCKING): size surprise -- MASTER_SPEC.md section 52,
mechanic M4 (``argus.copyability.size_surprise``), orchestrator
instruction ``argus-phase-5-001``.
"""

from __future__ import annotations

from decimal import Decimal

from argus.copyability.delay_curves import decimal_median
from argus.copyability.size_surprise import (
    MAD_SCALE_CONSTANT,
    SizeSurpriseInput,
    compute_size_surprise,
)


def _sizes(*values: int) -> list[Decimal]:
    return [Decimal(v) for v in values]


def test_worked_example_prior_1_2_3_4_5_current_9() -> None:
    data = SizeSurpriseInput(prior_sizes=_sizes(1, 2, 3, 4, 5), current_size=Decimal(9))
    result = compute_size_surprise(data)
    assert result.median == Decimal(3)
    assert result.mad == Decimal(1)
    expected_z = (Decimal(9) - Decimal(3)) / (MAD_SCALE_CONSTANT * Decimal(1))
    assert result.z == expected_z
    expected_component = min(Decimal(100), max(Decimal(0), Decimal(50) + Decimal(10) * expected_z))
    assert result.component == expected_component


def test_clamping_huge_outlier_clamped_to_100() -> None:
    data = SizeSurpriseInput(prior_sizes=_sizes(1, 2, 3, 4, 5), current_size=Decimal(10_000))
    result = compute_size_surprise(data)
    assert result.component == Decimal(100)


def test_clamping_huge_negative_z_clamped_to_0() -> None:
    data = SizeSurpriseInput(prior_sizes=_sizes(10, 11, 12, 13, 14), current_size=Decimal("0.001"))
    result = compute_size_surprise(data)
    assert result.component == Decimal(0)


def test_n_below_5_makes_z_and_component_unavailable() -> None:
    data = SizeSurpriseInput(prior_sizes=_sizes(1, 2, 3, 4), current_size=Decimal(9))
    result = compute_size_surprise(data)
    assert result.z is None
    assert result.component is None
    assert result.unavailable_reason is not None
    # descriptive median/typical size may remain available
    assert result.median == Decimal("2.5")


def test_constant_size_mad_zero_makes_z_unavailable() -> None:
    data = SizeSurpriseInput(prior_sizes=_sizes(5, 5, 5, 5, 5), current_size=Decimal(9))
    result = compute_size_surprise(data)
    assert result.mad == Decimal(0)
    assert result.z is None
    assert result.component is None
    assert "MAD" in result.unavailable_reason


def test_nonpositive_median_makes_z_unavailable() -> None:
    data = SizeSurpriseInput(prior_sizes=_sizes(-1, -2, -3, -4, -5), current_size=Decimal(9))
    result = compute_size_surprise(data)
    assert result.median <= 0
    assert result.z is None
    assert result.component is None


def test_no_baseline_evidence_everything_unavailable() -> None:
    data = SizeSurpriseInput(prior_sizes=[], current_size=Decimal(9))
    result = compute_size_surprise(data)
    assert result.baseline_count == 0
    assert result.median is None
    assert result.z is None
    assert result.component is None
    assert result.unavailable_reason is not None


def test_missing_portfolio_valuation_is_unavailable_never_summed_open_positions() -> None:
    data = SizeSurpriseInput(
        prior_sizes=_sizes(1, 2, 3, 4, 5), current_size=Decimal(9), portfolio_value_at_signal=None
    )
    result = compute_size_surprise(data)
    assert result.portfolio_relative_size_fraction is None
    assert result.portfolio_relative_unavailable_reason is not None


def test_evidenced_portfolio_valuation_produces_relative_fraction() -> None:
    data = SizeSurpriseInput(
        prior_sizes=_sizes(1, 2, 3, 4, 5),
        current_size=Decimal(9),
        portfolio_value_at_signal=Decimal(90),
    )
    result = compute_size_surprise(data)
    assert result.portfolio_relative_size_fraction == Decimal(9) / Decimal(90)
    assert result.portfolio_relative_unavailable_reason is None


def test_current_size_none_never_substituted_with_zero_f5_01() -> None:
    """F5-01 remediation: a genuinely missing current-opportunity size
    must never be silently treated as zero -- z/component/portfolio
    fraction all stay explicitly unavailable, never a fabricated signal."""
    data = SizeSurpriseInput(prior_sizes=_sizes(1, 2, 3, 4, 5), current_size=None)
    result = compute_size_surprise(data)
    assert result.z is None
    assert result.component is None
    assert "no current-opportunity size evidenced" in result.unavailable_reason
    assert result.portfolio_relative_size_fraction is None
    # descriptive baseline stats remain available even with no current size
    assert result.median == Decimal(3)
    assert result.mad == Decimal(1)


def test_recent_median_uses_most_recent_window() -> None:
    # 25 ascending values; recent_window default 20 -> excludes first 5.
    sizes = _sizes(*range(1, 26))
    data = SizeSurpriseInput(prior_sizes=sizes, current_size=Decimal(30))
    result = compute_size_surprise(data)
    recent_slice = sizes[-20:]
    expected_recent_median = decimal_median(recent_slice)
    assert result.recent_median == expected_recent_median
    assert result.baseline_count == 25

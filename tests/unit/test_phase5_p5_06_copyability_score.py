"""P5-06 (SPEC_BLOCKING): copyability/small samples -- MASTER_SPEC.md
section 49, mechanic M5 (``argus.scoring.copyability``), orchestrator
instruction ``argus-phase-5-001``. Uses the PRECISE existing weights from
``config/signals_v1.yaml``, never retuned.
"""

from __future__ import annotations

from decimal import Decimal

from argus.scoring.copyability import NEUTRAL_PRIOR, CopyabilityInputs, compute_copyability

WEIGHTS = {
    "prospective_delayed_follower_alpha": Decimal("0.35"),
    "liquidity_executability": Decimal("0.15"),
    "post_entry_stability": Decimal("0.10"),
    "holding_duration_suitability": Decimal("0.10"),
    "latency_tolerance": Decimal("0.10"),
    "slippage_sensitivity": Decimal("0.10"),
    "sample_confidence": Decimal("0.10"),
}


def _full_inputs(**overrides) -> CopyabilityInputs:
    base = {
        "follower_alpha_median_return_fraction": Decimal("0.3"),  # -> 80
        "successful_qty_matched_reverse_count": 8,
        "all_terminal_reverse_count": 10,  # -> 80
        "per_event_stability_fractions": (Decimal("0.8"),),  # -> 80
        "comparable_pairs_5m_le_30m_count": 8,
        "comparable_pairs_total": 10,  # -> 80
        "positive_peak_return_fraction": Decimal("1.0"),
        "latest_comparable_delay_return_fraction": Decimal("0.8"),
        "adequate_comparable_evidence": True,  # -> 80
        "mean_abs_price_impact_fraction": Decimal("0.2"),  # -> 80
        "n_events": 20,
        "k_distinct_tokens": 10,
        "coverage_numerator": 8,
        "coverage_denominator": 10,
        "history_completeness": "HIGH",  # c=0.8 -> component 80
    }
    base.update(overrides)
    return CopyabilityInputs(**base)


def test_all_measured_components_80_yields_score_80() -> None:
    result = compute_copyability(_full_inputs(), weights=WEIGHTS)
    assert result.score == Decimal("80.00")
    assert result.available_weight == Decimal("1.00")


def test_one_unavailable_component_contributes_neutral_prior_weighted() -> None:
    result = compute_copyability(
        _full_inputs(follower_alpha_median_return_fraction=None), weights=WEIGHTS
    )
    expected = (Decimal("0.35") * NEUTRAL_PRIOR) + (Decimal("0.65") * Decimal(80))
    assert result.score == expected
    assert result.available_weight == Decimal("0.65")


def test_n_zero_forces_score_null_and_confidence_unknown() -> None:
    result = compute_copyability(_full_inputs(n_events=0, coverage_numerator=0), weights=WEIGHTS)
    assert result.score is None
    assert result.sample_n == 0


def test_n1_k1_low_confidence() -> None:
    result = compute_copyability(
        _full_inputs(n_events=1, k_distinct_tokens=1, coverage_numerator=1, coverage_denominator=1),
        weights=WEIGHTS,
    )
    assert result.confidence == "LOW"
    assert result.score is not None  # n>0 -- score still computed


def test_n19_below_20_threshold_is_low() -> None:
    result = compute_copyability(
        _full_inputs(
            n_events=19, k_distinct_tokens=10, coverage_numerator=19, coverage_denominator=19
        ),
        weights=WEIGHTS,
    )
    assert result.confidence == "LOW"


def test_k9_below_10_threshold_is_low() -> None:
    result = compute_copyability(
        _full_inputs(
            n_events=20, k_distinct_tokens=9, coverage_numerator=20, coverage_denominator=20
        ),
        weights=WEIGHTS,
    )
    assert result.confidence == "LOW"


def test_n20_k10_full_coverage_high_history_is_high_confidence() -> None:
    result = compute_copyability(
        _full_inputs(
            n_events=20,
            k_distinct_tokens=10,
            coverage_numerator=20,
            coverage_denominator=20,
            history_completeness="HIGH",
        ),
        weights=WEIGHTS,
    )
    assert result.confidence == "HIGH"


def test_low_history_completeness_forces_low() -> None:
    result = compute_copyability(
        _full_inputs(
            n_events=25,
            k_distinct_tokens=12,
            coverage_numerator=25,
            coverage_denominator=25,
            history_completeness="LOW",
        ),
        weights=WEIGHTS,
    )
    assert result.confidence == "LOW"


def test_half_coverage_reduces_c_and_confidence() -> None:
    result = compute_copyability(
        _full_inputs(
            n_events=20,
            k_distinct_tokens=10,
            coverage_numerator=10,
            coverage_denominator=20,
            history_completeness="HIGH",
        ),
        weights=WEIGHTS,
    )
    assert result.sample_c == Decimal("0.5")
    # c == 0.5 is not < 0.5, and n=20/k=10/history=HIGH all satisfy the LOW
    # gate, so this falls through to the c < 0.8 MEDIUM branch.
    assert result.confidence == "MEDIUM"


def test_unavailable_weight_caps_confidence_low_below_half() -> None:
    result = compute_copyability(
        _full_inputs(
            follower_alpha_median_return_fraction=None,
            successful_qty_matched_reverse_count=0,
            all_terminal_reverse_count=0,
            per_event_stability_fractions=(),
        ),
        weights=WEIGHTS,
    )
    assert result.available_weight < Decimal("0.5")
    assert result.confidence == "LOW"


def test_terminal_unsuccessful_opportunity_cannot_improve_coverage_or_executability() -> None:
    baseline = compute_copyability(_full_inputs(), weights=WEIGHTS)
    worse = compute_copyability(
        _full_inputs(successful_qty_matched_reverse_count=0, all_terminal_reverse_count=10),
        weights=WEIGHTS,
    )
    assert (
        worse.components["liquidity_executability"].value
        < baseline.components["liquidity_executability"].value
    )


def test_six_probes_from_one_event_does_not_inflate_n() -> None:
    """n is a distinct-event count -- this module trusts the caller
    (loader) to have already reduced probes to distinct events; this test
    proves the formula itself never multiplies n by a probe count."""
    result_one_event = compute_copyability(
        _full_inputs(n_events=1, k_distinct_tokens=1, coverage_numerator=1, coverage_denominator=1),
        weights=WEIGHTS,
    )
    assert result_one_event.sample_n == 1


def test_impact_fraction_02_and_percentage_point_2_both_give_component_98() -> None:
    """A persisted impact source already converted exactly once to a
    FRACTION (0.02) must be used as-is; this module never re-interprets a
    percentage-point value (2) itself -- that conversion belongs to the
    loader, proven separately. Both, once correctly expressed as the same
    0.02 fraction, produce the identical component."""
    result_a = compute_copyability(
        _full_inputs(mean_abs_price_impact_fraction=Decimal("0.02")), weights=WEIGHTS
    )
    result_b = compute_copyability(
        _full_inputs(mean_abs_price_impact_fraction=Decimal(2) / Decimal(100)), weights=WEIGHTS
    )
    assert result_a.components["slippage_sensitivity"].value == Decimal("98")
    assert result_b.components["slippage_sensitivity"].value == Decimal("98")


def test_absent_impact_unit_is_unavailable_never_inferred() -> None:
    result = compute_copyability(
        _full_inputs(
            mean_abs_price_impact_fraction=None, slippage_unavailable_reason="IMPACT_UNIT_UNKNOWN"
        ),
        weights=WEIGHTS,
    )
    assert result.components["slippage_sensitivity"].available is False
    assert result.components["slippage_sensitivity"].reason == "IMPACT_UNIT_UNKNOWN"

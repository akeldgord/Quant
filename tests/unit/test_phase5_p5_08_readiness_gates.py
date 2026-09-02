"""P5-08 (SAFETY_OR_INTEGRITY_BLOCKING): readiness/hard gates --
MASTER_SPEC.md section 53, mechanic M6 (``argus.scoring.readiness``),
orchestrator instruction ``argus-phase-5-001``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from argus.domain.opportunity_readiness_snapshots import ALL_GATE_KEYS
from argus.scoring.readiness import (
    GATE_FAIL,
    GATE_PASS,
    GATE_UNKNOWN,
    ReadinessGates,
    ReadinessInputs,
    compute_readiness,
    gate,
)

WEIGHTS = {
    "qualification_score": Decimal("0.20"),
    "copyability": Decimal("0.20"),
    "remaining_information_at_current_delay": Decimal("0.15"),
    "liquidity_executable_price_impact": Decimal("0.15"),
    "price_movement_since_leader": Decimal("0.10"),
    "relative_position_size_surprise": Decimal("0.10"),
    "independent_confirmation": Decimal("0.10"),
}


def _all_pass_gates() -> ReadinessGates:
    return ReadinessGates(
        token_safety=gate(GATE_PASS, "ok"),
        chain_freshness=gate(GATE_PASS, "ok"),
        wallet_eligibility=gate(GATE_PASS, "ok"),
        history_quality=gate(GATE_PASS, "ok"),
        quote_validity=gate(GATE_PASS, "ok"),
        risk_caps=gate(GATE_PASS, "ok"),
    )


def _full_inputs(gates: ReadinessGates, **overrides) -> ReadinessInputs:
    base = {
        "gates": gates,
        "qualification_score": Decimal(80),
        "copyability_score": Decimal(80),
        "remaining_information_return_fraction": Decimal("0.3"),  # -> 80
        "current_quote_price_impact_fraction": Decimal("0.2"),  # -> 80
        "current_price": Decimal(120),
        "leader_price": Decimal(100),  # ratio .2 -> 100-20=80
        "size_surprise_component": Decimal(80),
        "independent_confirmation_value": Decimal(80),
    }
    base.update(overrides)
    return ReadinessInputs(**base)


def test_all_seven_components_80_all_gates_pass_yields_80() -> None:
    result = compute_readiness(_full_inputs(_all_pass_gates()), weights=WEIGHTS)
    assert result.eligible is True
    assert result.diagnostic_score == Decimal("80.00")
    assert result.actionable_score == Decimal("80.00")


def test_one_missing_component_uses_neutral_50_at_original_weight() -> None:
    result = compute_readiness(
        _full_inputs(_all_pass_gates(), qualification_score=None), weights=WEIGHTS
    )
    expected = (Decimal("0.20") * Decimal(50)) + (Decimal("0.80") * Decimal(80))
    assert result.diagnostic_score == expected
    assert result.actionable_score == expected  # still eligible -- gates unaffected


@pytest.mark.parametrize("gate_key", ALL_GATE_KEYS)
def test_each_gate_fail_independently_blocks_eligibility(gate_key: str) -> None:
    gates_kwargs = {k: gate(GATE_PASS, "ok") for k in ALL_GATE_KEYS}
    gates_kwargs[gate_key] = gate(GATE_FAIL, "failed for test")
    gates = ReadinessGates(**gates_kwargs)
    result = compute_readiness(_full_inputs(gates), weights=WEIGHTS)
    assert result.eligible is False
    assert result.actionable_score is None
    # Diagnostic score is still computed (labeled research-only).
    assert result.diagnostic_score == Decimal("80.00")


@pytest.mark.parametrize("gate_key", ALL_GATE_KEYS)
def test_each_gate_unknown_independently_blocks_eligibility(gate_key: str) -> None:
    gates_kwargs = {k: gate(GATE_PASS, "ok") for k in ALL_GATE_KEYS}
    gates_kwargs[gate_key] = gate(GATE_UNKNOWN, "unknown for test")
    gates = ReadinessGates(**gates_kwargs)
    result = compute_readiness(_full_inputs(gates), weights=WEIGHTS)
    assert result.eligible is False
    assert result.actionable_score is None


def test_lower_tier_wallet_eligibility_fail_blocks() -> None:
    gates_kwargs = {k: gate(GATE_PASS, "ok") for k in ALL_GATE_KEYS}
    gates_kwargs["wallet_eligibility"] = gate(GATE_FAIL, "tier B, below A/S")
    result = compute_readiness(_full_inputs(ReadinessGates(**gates_kwargs)), weights=WEIGHTS)
    assert result.eligible is False


def test_low_unknown_history_quality_gate_blocks() -> None:
    gates_kwargs = {k: gate(GATE_PASS, "ok") for k in ALL_GATE_KEYS}
    gates_kwargs["history_quality"] = gate(GATE_UNKNOWN, "history quality LOW/UNKNOWN")
    result = compute_readiness(_full_inputs(ReadinessGates(**gates_kwargs)), weights=WEIGHTS)
    assert result.eligible is False


def test_stale_invalid_quote_gate_blocks() -> None:
    gates_kwargs = {k: gate(GATE_PASS, "ok") for k in ALL_GATE_KEYS}
    gates_kwargs["quote_validity"] = gate(GATE_FAIL, "stale quote")
    result = compute_readiness(_full_inputs(ReadinessGates(**gates_kwargs)), weights=WEIGHTS)
    assert result.eligible is False


def test_zero_default_risk_allowance_gate_blocks() -> None:
    gates_kwargs = {k: gate(GATE_PASS, "ok") for k in ALL_GATE_KEYS}
    gates_kwargs["risk_caps"] = gate(GATE_FAIL, "zero/default risk allowance")
    result = compute_readiness(_full_inputs(ReadinessGates(**gates_kwargs)), weights=WEIGHTS)
    assert result.eligible is False


def test_out_of_range_input_treated_as_unavailable_not_silently_trusted() -> None:
    """A component value outside [0, 100] is clamped, never silently
    passed through unbounded."""
    result = compute_readiness(
        _full_inputs(_all_pass_gates(), qualification_score=Decimal(150)), weights=WEIGHTS
    )
    assert result.components["qualification_score"].value == Decimal(100)


def test_current_event_future_data_never_fabricated_pass() -> None:
    """A caller that has no evidence for a gate must report UNKNOWN, never
    a fabricated PASS -- proven by the UNKNOWN-blocks test above; this
    test additionally proves a None component value never counts as
    'available'."""
    gates_kwargs = {k: gate(GATE_PASS, "ok") for k in ALL_GATE_KEYS}
    result = compute_readiness(
        _full_inputs(
            ReadinessGates(**gates_kwargs),
            independent_confirmation_value=None,
        ),
        weights=WEIGHTS,
    )
    assert result.components["independent_confirmation"].available is False


def test_qualification_boundary_84_999_vs_85_no_threshold_change_here() -> None:
    """M6 itself does not enforce the A/S qualification_score_min=85
    threshold (that lives in config/tier-eligibility logic elsewhere) --
    this proves the component value passes through unweakened at both
    sides of the boundary, so a caller applying the threshold sees the
    real number."""
    below = compute_readiness(
        _full_inputs(_all_pass_gates(), qualification_score=Decimal("84.999")), weights=WEIGHTS
    )
    at = compute_readiness(
        _full_inputs(_all_pass_gates(), qualification_score=Decimal("85")), weights=WEIGHTS
    )
    assert below.components["qualification_score"].value == Decimal("84.999")
    assert at.components["qualification_score"].value == Decimal("85")


def test_no_bypass_from_high_weighted_score_when_gate_fails() -> None:
    gates_kwargs = {k: gate(GATE_PASS, "ok") for k in ALL_GATE_KEYS}
    gates_kwargs["token_safety"] = gate(GATE_FAIL, "unsafe token")
    result = compute_readiness(
        _full_inputs(
            ReadinessGates(**gates_kwargs),
            qualification_score=Decimal(100),
            copyability_score=Decimal(100),
            remaining_information_return_fraction=Decimal(1),
            current_quote_price_impact_fraction=Decimal(0),
            current_price=Decimal(100),
            leader_price=Decimal(100),
            size_surprise_component=Decimal(100),
            independent_confirmation_value=Decimal(100),
        ),
        weights=WEIGHTS,
    )
    assert result.diagnostic_score == Decimal("100.00")
    assert result.eligible is False
    assert result.actionable_score is None

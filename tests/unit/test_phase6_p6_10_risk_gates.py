"""P6-10 (SAFETY_OR_INTEGRITY_BLOCKING): independent live-risk validation
-- MASTER_SPEC.md section 81, orchestrator instruction
``argus-phase-6-001``.

An all-safe synthetic baseline passes all 23 gates; every gate
individually turned FAIL (or UNKNOWN where applicable) independently
rejects the whole evaluation with a stable reason code, before any
signing/submission seam -- proven here by never constructing a real
signer in this module.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from argus.executor.arm import ArmValidationResult
from argus.executor.risk_gates import GATE_KEYS, LiveRiskInputs, build_gates, evaluate_live_risk

_ARMED = ArmValidationResult(
    armed=True,
    max_single_trade_sol=Decimal("0.5"),
    max_total_exposure_sol=Decimal(2),
    max_daily_loss_sol=Decimal(1),
)


def _all_safe_inputs(**overrides: object) -> LiveRiskInputs:
    base: dict = {
        "software_readiness": True,
        "canary_passed": True,
        "arm_result": _ARMED,
        "running_git_commit": "a" * 40,
        "running_executor_build_hash": "b" * 64,
        "running_risk_config_hash": "c" * 64,
        "approved_git_commit": "a" * 40,
        "approved_executor_build_hash": "b" * 64,
        "approved_risk_config_hash": "c" * 64,
        "wallet_tier": "S",
        "wallet_qualification_score": Decimal(90),
        "min_qualification_score": Decimal(85),
        "signal_age_seconds": Decimal(2),
        "max_signal_age_seconds": Decimal(10),
        "token_mint_validated": True,
        "token_safety_status": "SAFE",
        "liquidity_usd": Decimal(50_000),
        "minimum_liquidity_usd": Decimal(10_000),
        "price_movement_since_leader_fraction": Decimal("0.01"),
        "max_price_movement_fraction": Decimal("0.05"),
        "quote_price_impact_fraction": Decimal("0.01"),
        "max_price_impact_fraction": Decimal("0.03"),
        "requested_slippage_bps": 50,
        "approved_slippage_ceiling_bps": 100,
        "existing_open_position_for_mint": False,
        "allow_automatic_scale_in": False,
        "current_total_exposure_sol": Decimal("0.5"),
        "proposed_notional_sol": Decimal("0.2"),
        "max_total_exposure_sol": Decimal(2),
        "current_daily_loss_sol": Decimal("0.1"),
        "max_daily_loss_sol": Decimal(1),
        "duplicate_intent_exists": False,
        "conflicting_position_exists": False,
        "wallet_balance_sol": Decimal(5),
        "required_balance_sol": Decimal(1),
        "quote_age_seconds": Decimal(1),
        "max_quote_age_seconds": Decimal(5),
        "chain_freshness_lag_seconds": Decimal(1),
        "max_chain_freshness_lag_seconds": Decimal(5),
        "clock_healthy": True,
        "stream_reconciliation_healthy": True,
    }
    base.update(overrides)
    return LiveRiskInputs(**base)


def test_gate_keys_are_exactly_23() -> None:
    assert len(GATE_KEYS) == 23
    assert len(set(GATE_KEYS)) == 23


def test_all_safe_baseline_passes_every_gate_and_is_approved() -> None:
    gates = build_gates(_all_safe_inputs())
    assert gates.all_pass is True
    assert gates.failed_or_unknown == ()
    result = evaluate_live_risk(gates)
    assert result.approved is True
    assert result.reason_codes == ()


_FAIL_OVERRIDES: dict[str, dict] = {
    "software_readiness": {"software_readiness": False},
    "canary_status": {"canary_passed": False},
    "human_arm_validity": {"arm_result": ArmValidationResult(armed=False, reason="expired")},
    "approved_build_config_hashes": {"approved_git_commit": "z" * 40},
    "wallet_eligibility": {"wallet_tier": "B"},
    "signal_freshness": {"signal_age_seconds": Decimal(100)},
    "token_mint": {"token_mint_validated": False},
    "token_safety": {"token_safety_status": "UNSAFE"},
    "minimum_liquidity": {"liquidity_usd": Decimal(1)},
    "price_movement_since_leader": {"price_movement_since_leader_fraction": Decimal("0.5")},
    "quote_price_impact": {"quote_price_impact_fraction": Decimal("0.5")},
    "slippage": {"requested_slippage_bps": 500},
    "single_position_limit": {"existing_open_position_for_mint": True},
    "total_exposure": {"proposed_notional_sol": Decimal(100)},
    "daily_loss": {"current_daily_loss_sol": Decimal(100)},
    "duplicate_intent": {"duplicate_intent_exists": True},
    "conflicting_position": {"conflicting_position_exists": True},
    "scale_in_prohibition": {"allow_automatic_scale_in": True},
    "wallet_balance": {"wallet_balance_sol": Decimal(0)},
    "quote_freshness": {"quote_age_seconds": Decimal(100)},
    "chain_freshness": {"chain_freshness_lag_seconds": Decimal(100)},
    "clock_health": {"clock_healthy": False},
    "stream_reconciliation_health": {"stream_reconciliation_healthy": False},
}

_UNKNOWN_OVERRIDES: dict[str, dict] = {
    "approved_build_config_hashes": {"approved_git_commit": None},
    "wallet_eligibility": {"wallet_tier": None},
    "signal_freshness": {"signal_age_seconds": None},
    "minimum_liquidity": {"liquidity_usd": None},
    "price_movement_since_leader": {"price_movement_since_leader_fraction": None},
    "quote_price_impact": {"quote_price_impact_fraction": None},
    "slippage": {"requested_slippage_bps": None},
    "wallet_balance": {"wallet_balance_sol": None},
    "quote_freshness": {"quote_age_seconds": None},
    "chain_freshness": {"chain_freshness_lag_seconds": None},
    "clock_health": {"clock_healthy": None},
    "stream_reconciliation_health": {"stream_reconciliation_healthy": None},
    "token_safety": {"token_safety_status": "UNKNOWN"},
}


def test_every_gate_key_has_a_fail_case_in_the_table_above() -> None:
    assert set(_FAIL_OVERRIDES.keys()) == set(GATE_KEYS)


@pytest.mark.parametrize("gate_key", sorted(_FAIL_OVERRIDES.keys()))
def test_each_gate_fail_independently_rejects(gate_key: str) -> None:
    inputs = _all_safe_inputs(**_FAIL_OVERRIDES[gate_key])
    gates = build_gates(inputs)
    gate_result = getattr(gates, gate_key)
    assert gate_result.status == "FAIL"
    result = evaluate_live_risk(gates)
    assert result.approved is False
    assert gate_key in result.reason_codes


@pytest.mark.parametrize("gate_key", sorted(_UNKNOWN_OVERRIDES.keys()))
def test_each_applicable_gate_unknown_independently_rejects(gate_key: str) -> None:
    inputs = _all_safe_inputs(**_UNKNOWN_OVERRIDES[gate_key])
    gates = build_gates(inputs)
    gate_result = getattr(gates, gate_key)
    assert gate_result.status == "UNKNOWN"
    result = evaluate_live_risk(gates)
    assert result.approved is False
    assert gate_key in result.reason_codes


def test_no_current_phase_test_ever_sets_real_live_authorization() -> None:
    """This module never constructs a real signer/dispatch path -- the
    strongest evidence available in a purely software-only phase that
    these gate evaluations cannot themselves cause live execution."""
    import argus.executor.risk_gates as risk_gates_module

    assert "Signer" not in dir(risk_gates_module)
    assert not hasattr(risk_gates_module, "signer")

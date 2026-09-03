"""P6-12 (SAFETY_OR_INTEGRITY_BLOCKING): independent risk exits --
MASTER_SPEC.md section 67, orchestrator instruction
``argus-phase-6-001``.

Each of the six exit triggers is evaluated purely from ARGUS's own
position/market/operator state -- none of them depends on the leader
wallet having sold anything, proven here by never referencing any
leader/source-wallet field anywhere in ``RiskExitInputs``.
"""

from __future__ import annotations

from decimal import Decimal

from argus.domain.risk_exit_events import (
    TRIGGER_LIQUIDITY_COLLAPSE,
    TRIGGER_MAX_AGGREGATE_EXPOSURE,
    TRIGGER_MAX_DAILY_LOSS,
    TRIGGER_MAX_POSITION_LOSS,
    TRIGGER_OPERATOR_EMERGENCY_EXIT,
    TRIGGER_TOKEN_RISK_STATE_CHANGE,
    TRIGGER_TYPES,
)
from argus.executor.risk_exits import RiskExitInputs, evaluate_risk_exits


def _safe_inputs(**overrides: object) -> RiskExitInputs:
    base: dict = {
        "position_unrealized_loss_fraction": Decimal("0.05"),
        "max_position_loss_fraction": Decimal("0.30"),
        "current_liquidity_usd": Decimal(50_000),
        "minimum_liquidity_usd": Decimal(10_000),
        "token_risk_status_changed_to_unsafe": False,
        "daily_realized_loss_sol": Decimal("0.1"),
        "max_daily_loss_sol": Decimal(1),
        "aggregate_exposure_sol": Decimal("0.5"),
        "max_aggregate_exposure_sol": Decimal(2),
        "operator_emergency_exit_requested": False,
    }
    base.update(overrides)
    return RiskExitInputs(**base)


def test_safe_inputs_trigger_nothing() -> None:
    assert evaluate_risk_exits(_safe_inputs()) == ()


def test_max_position_loss_triggers() -> None:
    triggers = evaluate_risk_exits(_safe_inputs(position_unrealized_loss_fraction=Decimal("0.5")))
    assert len(triggers) == 1
    assert triggers[0].trigger_type == TRIGGER_MAX_POSITION_LOSS


def test_liquidity_collapse_triggers() -> None:
    triggers = evaluate_risk_exits(_safe_inputs(current_liquidity_usd=Decimal(100)))
    assert len(triggers) == 1
    assert triggers[0].trigger_type == TRIGGER_LIQUIDITY_COLLAPSE


def test_token_risk_state_change_triggers() -> None:
    triggers = evaluate_risk_exits(_safe_inputs(token_risk_status_changed_to_unsafe=True))
    assert len(triggers) == 1
    assert triggers[0].trigger_type == TRIGGER_TOKEN_RISK_STATE_CHANGE


def test_max_daily_loss_triggers() -> None:
    triggers = evaluate_risk_exits(_safe_inputs(daily_realized_loss_sol=Decimal(5)))
    assert len(triggers) == 1
    assert triggers[0].trigger_type == TRIGGER_MAX_DAILY_LOSS


def test_max_aggregate_exposure_triggers() -> None:
    triggers = evaluate_risk_exits(_safe_inputs(aggregate_exposure_sol=Decimal(10)))
    assert len(triggers) == 1
    assert triggers[0].trigger_type == TRIGGER_MAX_AGGREGATE_EXPOSURE


def test_operator_emergency_exit_triggers() -> None:
    triggers = evaluate_risk_exits(_safe_inputs(operator_emergency_exit_requested=True))
    assert len(triggers) == 1
    assert triggers[0].trigger_type == TRIGGER_OPERATOR_EMERGENCY_EXIT


def test_multiple_co_occurring_triggers_are_all_returned() -> None:
    """A liquidity collapse and a daily-loss breach can legitimately
    co-occur -- both must be returned, never only the first match."""
    triggers = evaluate_risk_exits(
        _safe_inputs(
            current_liquidity_usd=Decimal(100),
            daily_realized_loss_sol=Decimal(5),
        )
    )
    trigger_types = {t.trigger_type for t in triggers}
    assert trigger_types == {TRIGGER_LIQUIDITY_COLLAPSE, TRIGGER_MAX_DAILY_LOSS}


def test_all_six_triggers_are_covered() -> None:
    assert set(TRIGGER_TYPES) == {
        TRIGGER_MAX_POSITION_LOSS,
        TRIGGER_LIQUIDITY_COLLAPSE,
        TRIGGER_TOKEN_RISK_STATE_CHANGE,
        TRIGGER_MAX_DAILY_LOSS,
        TRIGGER_MAX_AGGREGATE_EXPOSURE,
        TRIGGER_OPERATOR_EMERGENCY_EXIT,
    }
    assert len(TRIGGER_TYPES) == 6


def test_risk_exit_inputs_has_no_leader_wallet_dependency() -> None:
    """Structural proof that no field of RiskExitInputs references the
    source/leader wallet's own behavior -- risk exits never depend on
    leader-sell evidence."""
    field_names = set(RiskExitInputs.__dataclass_fields__)
    assert not any("leader" in name or "source_wallet" in name for name in field_names)

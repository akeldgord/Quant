"""argus.executor.risk_exits — MASTER_SPEC.md section 67 (INDEPENDENT
RISK EXITS), Phase 6 (``argus-phase-6-001``).

ARGUS never surrenders risk control to a source wallet. Every trigger
here is evaluated purely from ARGUS's own position/market/operator
state -- none of them depends on the leader wallet having sold
anything. Exact capital limits are operator-defined (passed in, never
hardcoded here beyond the zero defaults in ``argus.executor.capital``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from argus.domain.risk_exit_events import (
    TRIGGER_LIQUIDITY_COLLAPSE,
    TRIGGER_MAX_AGGREGATE_EXPOSURE,
    TRIGGER_MAX_DAILY_LOSS,
    TRIGGER_MAX_POSITION_LOSS,
    TRIGGER_OPERATOR_EMERGENCY_EXIT,
    TRIGGER_TOKEN_RISK_STATE_CHANGE,
)


@dataclass(frozen=True)
class RiskExitTrigger:
    trigger_type: str
    detail: str


@dataclass(frozen=True)
class RiskExitInputs:
    position_unrealized_loss_fraction: Decimal | None
    max_position_loss_fraction: Decimal

    current_liquidity_usd: Decimal | None
    minimum_liquidity_usd: Decimal

    token_risk_status_changed_to_unsafe: bool

    daily_realized_loss_sol: Decimal
    max_daily_loss_sol: Decimal

    aggregate_exposure_sol: Decimal
    max_aggregate_exposure_sol: Decimal

    operator_emergency_exit_requested: bool


def evaluate_risk_exits(inputs: RiskExitInputs) -> tuple[RiskExitTrigger, ...]:
    """Every independently-true trigger is returned -- callers act on
    ALL of them (never only the first), since e.g. a liquidity collapse
    and a daily-loss breach can legitimately co-occur."""
    triggers: list[RiskExitTrigger] = []

    if (
        inputs.position_unrealized_loss_fraction is not None
        and inputs.position_unrealized_loss_fraction >= inputs.max_position_loss_fraction
    ):
        triggers.append(
            RiskExitTrigger(
                TRIGGER_MAX_POSITION_LOSS,
                f"unrealized loss {inputs.position_unrealized_loss_fraction} >= "
                f"{inputs.max_position_loss_fraction}",
            )
        )

    if (
        inputs.current_liquidity_usd is not None
        and inputs.current_liquidity_usd < inputs.minimum_liquidity_usd
    ):
        triggers.append(
            RiskExitTrigger(
                TRIGGER_LIQUIDITY_COLLAPSE,
                f"liquidity {inputs.current_liquidity_usd} below {inputs.minimum_liquidity_usd}",
            )
        )

    if inputs.token_risk_status_changed_to_unsafe:
        triggers.append(
            RiskExitTrigger(
                TRIGGER_TOKEN_RISK_STATE_CHANGE, "token safety status changed to UNSAFE"
            )
        )

    if inputs.daily_realized_loss_sol >= inputs.max_daily_loss_sol:
        triggers.append(
            RiskExitTrigger(
                TRIGGER_MAX_DAILY_LOSS,
                f"daily loss {inputs.daily_realized_loss_sol} >= {inputs.max_daily_loss_sol}",
            )
        )

    if inputs.aggregate_exposure_sol >= inputs.max_aggregate_exposure_sol:
        triggers.append(
            RiskExitTrigger(
                TRIGGER_MAX_AGGREGATE_EXPOSURE,
                f"exposure {inputs.aggregate_exposure_sol} >= {inputs.max_aggregate_exposure_sol}",
            )
        )

    if inputs.operator_emergency_exit_requested:
        triggers.append(
            RiskExitTrigger(TRIGGER_OPERATOR_EMERGENCY_EXIT, "operator requested emergency exit")
        )

    return tuple(triggers)

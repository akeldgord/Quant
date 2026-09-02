"""M6 (Opportunity readiness V1, research-only) — MASTER_SPEC.md section
53, Phase 5 (``argus-phase-5-001``).

Uses PRECISELY the existing ``trade_readiness_weights`` already frozen in
``config/signals_v1.yaml``. Six master hard gates are evaluated strictly
BEFORE any eligible score; any gate FAIL or UNKNOWN makes
``eligible=False`` and ``actionable_score=None`` -- no exception, no
bypass from a high weighted diagnostic score. A separately labeled
research ``diagnostic_score`` may still be computed (neutral-50 priors for
unavailable components, never redistributed) even when ineligible, but it
is never an order or permission -- real live authorization stays
unconditionally false in this phase regardless of either score (P5-14).

A/S thresholds (``qualification_score_min`` 85, ``copyability_score_min``
75, ``trade_readiness_min`` 90 in ``config/signals_v1.yaml``) and existing
confidence/risk constraints are never weakened by anything in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from argus.copyability.util import clamp
from argus.domain.opportunity_readiness_snapshots import (
    ALL_GATE_KEYS,
    GATE_FAIL,
    GATE_PASS,
    GATE_UNKNOWN,
)
from argus.scoring.copyability import NEUTRAL_PRIOR, ComponentValue

READINESS_COMPONENT_KEYS = (
    "qualification_score",
    "copyability",
    "remaining_information_at_current_delay",
    "liquidity_executable_price_impact",
    "price_movement_since_leader",
    "relative_position_size_surprise",
    "independent_confirmation",
)

GateStatus = Literal["PASS", "FAIL", "UNKNOWN"]


@dataclass(frozen=True)
class GateResult:
    status: GateStatus
    reason: str

    def as_dict(self) -> dict:
        return {"status": self.status, "reason": self.reason}


@dataclass(frozen=True)
class ReadinessGates:
    token_safety: GateResult
    chain_freshness: GateResult
    wallet_eligibility: GateResult
    history_quality: GateResult
    quote_validity: GateResult
    risk_caps: GateResult

    def all_pass(self) -> bool:
        return all(getattr(self, key).status == GATE_PASS for key in ALL_GATE_KEYS)

    def as_dict(self) -> dict:
        return {key: getattr(self, key).as_dict() for key in ALL_GATE_KEYS}


@dataclass(frozen=True)
class ReadinessInputs:
    gates: ReadinessGates

    # 1. qualification_score -- from the frozen wallet_score_snapshots row
    # (qualification_score column only, never descriptive_score).
    qualification_score: Decimal | None = None

    # 2. copyability -- an eligible as-of copyability score EXCLUDING the
    # current event (the caller built this snapshot with that exclusion).
    copyability_score: Decimal | None = None

    # 3. remaining_information_at_current_delay -- the latest nonfuture
    # comparable observed return proxy at delay <= the opportunity's own
    # current elapsed delay (no extrapolation beyond support).
    remaining_information_return_fraction: Decimal | None = None

    # 4. liquidity_executable_price_impact -- M5's impact normalization
    # applied to the single actual current valid quote's impact fraction.
    current_quote_price_impact_fraction: Decimal | None = None
    current_quote_impact_unavailable_reason: str | None = None

    # 5. price_movement_since_leader -- only when both contemporaneous
    # prices are evidenced/comparable.
    current_price: Decimal | None = None
    leader_price: Decimal | None = None

    # 6. relative_position_size_surprise -- M4's own component value.
    size_surprise_component: Decimal | None = None
    size_surprise_unavailable_reason: str | None = None

    # 7. independent_confirmation -- 100 (evidenced independent actor),
    # 0 (evidenced absence), or None (unknown -- never inferred from
    # distinct addresses alone).
    independent_confirmation_value: Decimal | None = None


def _available(value: Decimal) -> ComponentValue:
    return ComponentValue(available=True, value=value)


def _unavailable(reason: str) -> ComponentValue:
    return ComponentValue(available=False, reason=reason)


def _component_qualification(inputs: ReadinessInputs) -> ComponentValue:
    if inputs.qualification_score is None:
        return _unavailable("no frozen qualification_score snapshot available")
    return _available(clamp(inputs.qualification_score, Decimal(0), Decimal(100)))


def _component_copyability(inputs: ReadinessInputs) -> ComponentValue:
    if inputs.copyability_score is None:
        return _unavailable("no eligible copyability snapshot available (excluding current event)")
    return _available(clamp(inputs.copyability_score, Decimal(0), Decimal(100)))


def _component_remaining_information(inputs: ReadinessInputs) -> ComponentValue:
    if inputs.remaining_information_return_fraction is None:
        return _unavailable("no comparable observation at or before the current elapsed delay")
    value = clamp(
        Decimal(50) + Decimal(100) * inputs.remaining_information_return_fraction,
        Decimal(0),
        Decimal(100),
    )
    return _available(value)


def _component_liquidity_impact(inputs: ReadinessInputs) -> ComponentValue:
    if inputs.current_quote_price_impact_fraction is None:
        return _unavailable(inputs.current_quote_impact_unavailable_reason or "IMPACT_UNIT_UNKNOWN")
    value = clamp(
        Decimal(100) * (Decimal(1) - inputs.current_quote_price_impact_fraction),
        Decimal(0),
        Decimal(100),
    )
    return _available(value)


def _component_price_movement(inputs: ReadinessInputs) -> ComponentValue:
    if inputs.current_price is None or inputs.leader_price is None:
        return _unavailable("both contemporaneous prices not evidenced/comparable")
    if inputs.leader_price <= 0:
        return _unavailable("nonpositive leader price")
    ratio = inputs.current_price / inputs.leader_price - 1
    value = clamp(Decimal(100) - Decimal(100) * max(Decimal(0), ratio), Decimal(0), Decimal(100))
    return _available(value)


def _component_size_surprise(inputs: ReadinessInputs) -> ComponentValue:
    if inputs.size_surprise_component is None:
        return _unavailable(inputs.size_surprise_unavailable_reason or "size surprise unavailable")
    return _available(clamp(inputs.size_surprise_component, Decimal(0), Decimal(100)))


def _component_independent_confirmation(inputs: ReadinessInputs) -> ComponentValue:
    if inputs.independent_confirmation_value is None:
        return _unavailable(
            "independent confirmation unknown -- never inferred from addresses alone"
        )
    return _available(clamp(inputs.independent_confirmation_value, Decimal(0), Decimal(100)))


@dataclass(frozen=True)
class ReadinessResult:
    gates: ReadinessGates
    eligible: bool
    actionable_score: Decimal | None
    diagnostic_score: Decimal
    components: dict[str, ComponentValue]


def compute_readiness(inputs: ReadinessInputs, *, weights: dict[str, Decimal]) -> ReadinessResult:
    """``weights`` must be exactly ``config/signals_v1.yaml``'s
    ``trade_readiness_weights`` block, converted to ``Decimal``."""
    components: dict[str, ComponentValue] = {
        "qualification_score": _component_qualification(inputs),
        "copyability": _component_copyability(inputs),
        "remaining_information_at_current_delay": _component_remaining_information(inputs),
        "liquidity_executable_price_impact": _component_liquidity_impact(inputs),
        "price_movement_since_leader": _component_price_movement(inputs),
        "relative_position_size_surprise": _component_size_surprise(inputs),
        "independent_confirmation": _component_independent_confirmation(inputs),
    }

    diagnostic_total = Decimal(0)
    for key, comp in components.items():
        weight = weights[key]
        value: Decimal = (
            comp.value if (comp.available and comp.value is not None) else NEUTRAL_PRIOR
        )
        diagnostic_total += weight * value

    eligible = inputs.gates.all_pass()
    actionable_score = diagnostic_total if eligible else None

    return ReadinessResult(
        gates=inputs.gates,
        eligible=eligible,
        actionable_score=actionable_score,
        diagnostic_score=diagnostic_total,
        components=components,
    )


def gate(status: GateStatus, reason: str) -> GateResult:
    return GateResult(status=status, reason=reason)


__all__ = [
    "READINESS_COMPONENT_KEYS",
    "GateStatus",
    "GateResult",
    "ReadinessGates",
    "ReadinessInputs",
    "ReadinessResult",
    "compute_readiness",
    "gate",
    "GATE_PASS",
    "GATE_FAIL",
    "GATE_UNKNOWN",
]

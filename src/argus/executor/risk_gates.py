"""argus.executor.risk_gates — MASTER_SPEC.md section 81 (LIVE RISK
VALIDATION), Phase 6 (``argus-phase-6-001``).

The executor independently rechecks every one of section 81's 23 gates
before any signing/submission seam. ANY single failed or unknown gate
rejects the intent with a stable reason code -- this module never lets
a partial pass through, and never fabricates a PASS for
``software_readiness``/``canary_status``/``human_arm_validity`` (those
are always fed real upstream evidence by the caller via
:class:`LiveRiskInputs`; this module only evaluates what it is given).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from argus.executor.arm import ArmValidationResult

GateStatus = Literal["PASS", "FAIL", "UNKNOWN"]


@dataclass(frozen=True)
class GateResult:
    status: GateStatus
    reason: str


def gate(status: GateStatus, reason: str) -> GateResult:
    return GateResult(status=status, reason=reason)


GATE_KEYS: tuple[str, ...] = (
    "software_readiness",
    "canary_status",
    "human_arm_validity",
    "approved_build_config_hashes",
    "wallet_eligibility",
    "signal_freshness",
    "token_mint",
    "token_safety",
    "minimum_liquidity",
    "price_movement_since_leader",
    "quote_price_impact",
    "slippage",
    "single_position_limit",
    "total_exposure",
    "daily_loss",
    "duplicate_intent",
    "conflicting_position",
    "scale_in_prohibition",
    "wallet_balance",
    "quote_freshness",
    "chain_freshness",
    "clock_health",
    "stream_reconciliation_health",
)


@dataclass(frozen=True)
class LiveRiskGates:
    software_readiness: GateResult
    canary_status: GateResult
    human_arm_validity: GateResult
    approved_build_config_hashes: GateResult
    wallet_eligibility: GateResult
    signal_freshness: GateResult
    token_mint: GateResult
    token_safety: GateResult
    minimum_liquidity: GateResult
    price_movement_since_leader: GateResult
    quote_price_impact: GateResult
    slippage: GateResult
    single_position_limit: GateResult
    total_exposure: GateResult
    daily_loss: GateResult
    duplicate_intent: GateResult
    conflicting_position: GateResult
    scale_in_prohibition: GateResult
    wallet_balance: GateResult
    quote_freshness: GateResult
    chain_freshness: GateResult
    clock_health: GateResult
    stream_reconciliation_health: GateResult

    def as_dict(self) -> dict[str, dict[str, str]]:
        return {
            key: {"status": getattr(self, key).status, "reason": getattr(self, key).reason}
            for key in GATE_KEYS
        }

    @property
    def all_pass(self) -> bool:
        return all(getattr(self, key).status == "PASS" for key in GATE_KEYS)

    @property
    def failed_or_unknown(self) -> tuple[str, ...]:
        return tuple(key for key in GATE_KEYS if getattr(self, key).status != "PASS")


@dataclass(frozen=True)
class LiveRiskResult:
    gates: LiveRiskGates
    approved: bool
    reason_codes: tuple[str, ...]


def evaluate_live_risk(gates: LiveRiskGates) -> LiveRiskResult:
    if gates.all_pass:
        return LiveRiskResult(gates=gates, approved=True, reason_codes=())
    return LiveRiskResult(gates=gates, approved=False, reason_codes=gates.failed_or_unknown)


_ELIGIBLE_TIERS = ("A", "S")


@dataclass(frozen=True)
class LiveRiskInputs:
    software_readiness: bool
    canary_passed: bool
    arm_result: ArmValidationResult
    running_git_commit: str
    running_executor_build_hash: str
    running_risk_config_hash: str
    approved_git_commit: str | None
    approved_executor_build_hash: str | None
    approved_risk_config_hash: str | None

    wallet_tier: str | None
    wallet_qualification_score: Decimal | None
    min_qualification_score: Decimal

    signal_age_seconds: Decimal | None
    max_signal_age_seconds: Decimal

    token_mint_validated: bool
    token_safety_status: str  # "SAFE" | "UNSAFE" | "UNKNOWN"

    liquidity_usd: Decimal | None
    minimum_liquidity_usd: Decimal

    price_movement_since_leader_fraction: Decimal | None
    max_price_movement_fraction: Decimal

    quote_price_impact_fraction: Decimal | None
    max_price_impact_fraction: Decimal

    requested_slippage_bps: int | None
    approved_slippage_ceiling_bps: int

    existing_open_position_for_mint: bool
    allow_automatic_scale_in: bool

    current_total_exposure_sol: Decimal
    proposed_notional_sol: Decimal
    max_total_exposure_sol: Decimal

    current_daily_loss_sol: Decimal
    max_daily_loss_sol: Decimal

    duplicate_intent_exists: bool
    conflicting_position_exists: bool

    wallet_balance_sol: Decimal | None
    required_balance_sol: Decimal

    quote_age_seconds: Decimal | None
    max_quote_age_seconds: Decimal

    chain_freshness_lag_seconds: Decimal | None
    max_chain_freshness_lag_seconds: Decimal

    clock_healthy: bool | None
    stream_reconciliation_healthy: bool | None


def build_gates(inputs: LiveRiskInputs) -> LiveRiskGates:
    software_readiness = (
        gate("PASS", "software readiness confirmed")
        if inputs.software_readiness
        else gate("FAIL", "software readiness not confirmed")
    )
    canary_status = (
        gate("PASS", "canary passed")
        if inputs.canary_passed
        else gate("FAIL", "LIVE_CANARY_PASSED is not true")
    )
    human_arm_validity = (
        gate("PASS", "arm file valid")
        if inputs.arm_result.armed
        else gate("FAIL", f"arm invalid: {inputs.arm_result.reason or 'unknown reason'}")
    )

    hashes_present = (
        inputs.approved_git_commit is not None
        and inputs.approved_executor_build_hash is not None
        and inputs.approved_risk_config_hash is not None
    )
    if not hashes_present:
        approved_build_config_hashes = gate("UNKNOWN", "no approved build/config hashes evidenced")
    elif (
        inputs.approved_git_commit == inputs.running_git_commit
        and inputs.approved_executor_build_hash == inputs.running_executor_build_hash
        and inputs.approved_risk_config_hash == inputs.running_risk_config_hash
    ):
        approved_build_config_hashes = gate(
            "PASS", "approved build/config hashes match running build"
        )
    else:
        approved_build_config_hashes = gate("FAIL", "approved build/config hash mismatch")

    if inputs.wallet_tier is None or inputs.wallet_qualification_score is None:
        wallet_eligibility = gate("UNKNOWN", "no wallet tier/qualification evidence")
    elif (
        inputs.wallet_tier in _ELIGIBLE_TIERS
        and inputs.wallet_qualification_score >= inputs.min_qualification_score
    ):
        wallet_eligibility = gate(
            "PASS", f"tier {inputs.wallet_tier} qualification {inputs.wallet_qualification_score}"
        )
    else:
        wallet_eligibility = gate(
            "FAIL",
            f"tier {inputs.wallet_tier} qualification {inputs.wallet_qualification_score} "
            f"below A/S or {inputs.min_qualification_score}",
        )

    if inputs.signal_age_seconds is None:
        signal_freshness = gate("UNKNOWN", "no signal age evidenced")
    elif inputs.signal_age_seconds <= inputs.max_signal_age_seconds:
        signal_freshness = gate("PASS", f"signal age {inputs.signal_age_seconds}s")
    else:
        signal_freshness = gate(
            "FAIL",
            f"signal age {inputs.signal_age_seconds}s exceeds {inputs.max_signal_age_seconds}s",
        )

    token_mint = (
        gate("PASS", "token mint validated")
        if inputs.token_mint_validated
        else gate("FAIL", "token mint not validated")
    )

    if inputs.token_safety_status == "SAFE":
        token_safety = gate("PASS", "token safety SAFE")
    elif inputs.token_safety_status == "UNSAFE":
        token_safety = gate("FAIL", "token safety UNSAFE")
    else:
        token_safety = gate("UNKNOWN", "token safety UNKNOWN")

    if inputs.liquidity_usd is None:
        minimum_liquidity = gate("UNKNOWN", "no liquidity evidence")
    elif inputs.liquidity_usd >= inputs.minimum_liquidity_usd:
        minimum_liquidity = gate("PASS", f"liquidity {inputs.liquidity_usd} USD")
    else:
        minimum_liquidity = gate(
            "FAIL", f"liquidity {inputs.liquidity_usd} below {inputs.minimum_liquidity_usd} USD"
        )

    if inputs.price_movement_since_leader_fraction is None:
        price_movement_since_leader = gate("UNKNOWN", "no price-movement-since-leader evidence")
    elif abs(inputs.price_movement_since_leader_fraction) <= inputs.max_price_movement_fraction:
        price_movement_since_leader = gate(
            "PASS", f"movement {inputs.price_movement_since_leader_fraction}"
        )
    else:
        price_movement_since_leader = gate(
            "FAIL",
            f"movement {inputs.price_movement_since_leader_fraction} exceeds "
            f"{inputs.max_price_movement_fraction}",
        )

    if inputs.quote_price_impact_fraction is None:
        quote_price_impact = gate("UNKNOWN", "no quote price-impact evidence")
    elif inputs.quote_price_impact_fraction <= inputs.max_price_impact_fraction:
        quote_price_impact = gate("PASS", f"impact {inputs.quote_price_impact_fraction}")
    else:
        quote_price_impact = gate(
            "FAIL",
            f"impact {inputs.quote_price_impact_fraction} exceeds {inputs.max_price_impact_fraction}",
        )

    if inputs.requested_slippage_bps is None:
        slippage = gate("UNKNOWN", "no requested slippage evidenced")
    elif inputs.requested_slippage_bps <= inputs.approved_slippage_ceiling_bps:
        slippage = gate("PASS", f"slippage {inputs.requested_slippage_bps}bps")
    else:
        slippage = gate(
            "FAIL",
            f"slippage {inputs.requested_slippage_bps}bps exceeds "
            f"{inputs.approved_slippage_ceiling_bps}bps ceiling",
        )

    single_position_limit = (
        gate("FAIL", "an open position already exists for this mint")
        if inputs.existing_open_position_for_mint
        else gate("PASS", "no existing open position for this mint")
    )

    proposed_total = inputs.current_total_exposure_sol + inputs.proposed_notional_sol
    total_exposure = (
        gate("PASS", f"projected exposure {proposed_total} SOL")
        if proposed_total <= inputs.max_total_exposure_sol
        else gate(
            "FAIL",
            f"projected exposure {proposed_total} SOL exceeds {inputs.max_total_exposure_sol} SOL",
        )
    )

    daily_loss = (
        gate("PASS", f"daily loss {inputs.current_daily_loss_sol} SOL")
        if inputs.current_daily_loss_sol <= inputs.max_daily_loss_sol
        else gate(
            "FAIL",
            f"daily loss {inputs.current_daily_loss_sol} SOL exceeds "
            f"{inputs.max_daily_loss_sol} SOL",
        )
    )

    duplicate_intent = (
        gate("FAIL", "a duplicate intent already exists")
        if inputs.duplicate_intent_exists
        else gate("PASS", "no duplicate intent")
    )
    conflicting_position = (
        gate("FAIL", "a conflicting position exists")
        if inputs.conflicting_position_exists
        else gate("PASS", "no conflicting position")
    )
    scale_in_prohibition = (
        gate("FAIL", "automatic scale-in is prohibited (ALLOW_AUTOMATIC_SCALE_IN=false)")
        if inputs.allow_automatic_scale_in
        else gate("PASS", "ALLOW_AUTOMATIC_SCALE_IN=false honored")
    )

    if inputs.wallet_balance_sol is None:
        wallet_balance = gate("UNKNOWN", "no executor wallet balance evidenced")
    elif inputs.wallet_balance_sol >= inputs.required_balance_sol:
        wallet_balance = gate("PASS", f"balance {inputs.wallet_balance_sol} SOL")
    else:
        wallet_balance = gate(
            "FAIL",
            f"balance {inputs.wallet_balance_sol} SOL below required "
            f"{inputs.required_balance_sol} SOL",
        )

    if inputs.quote_age_seconds is None:
        quote_freshness = gate("UNKNOWN", "no quote age evidenced")
    elif inputs.quote_age_seconds <= inputs.max_quote_age_seconds:
        quote_freshness = gate("PASS", f"quote age {inputs.quote_age_seconds}s")
    else:
        quote_freshness = gate(
            "FAIL", f"quote age {inputs.quote_age_seconds}s exceeds {inputs.max_quote_age_seconds}s"
        )

    if inputs.chain_freshness_lag_seconds is None:
        chain_freshness = gate("UNKNOWN", "no chain freshness lag evidenced")
    elif inputs.chain_freshness_lag_seconds <= inputs.max_chain_freshness_lag_seconds:
        chain_freshness = gate("PASS", f"chain lag {inputs.chain_freshness_lag_seconds}s")
    else:
        chain_freshness = gate(
            "FAIL",
            f"chain lag {inputs.chain_freshness_lag_seconds}s exceeds "
            f"{inputs.max_chain_freshness_lag_seconds}s",
        )

    if inputs.clock_healthy is None:
        clock_health = gate("UNKNOWN", "no clock health evidenced")
    elif inputs.clock_healthy:
        clock_health = gate("PASS", "clock healthy")
    else:
        clock_health = gate("FAIL", "clock unhealthy")

    if inputs.stream_reconciliation_healthy is None:
        stream_reconciliation_health = gate("UNKNOWN", "no stream/reconciliation health evidenced")
    elif inputs.stream_reconciliation_healthy:
        stream_reconciliation_health = gate("PASS", "streams/reconciliation healthy")
    else:
        stream_reconciliation_health = gate("FAIL", "streams/reconciliation unhealthy")

    return LiveRiskGates(
        software_readiness=software_readiness,
        canary_status=canary_status,
        human_arm_validity=human_arm_validity,
        approved_build_config_hashes=approved_build_config_hashes,
        wallet_eligibility=wallet_eligibility,
        signal_freshness=signal_freshness,
        token_mint=token_mint,
        token_safety=token_safety,
        minimum_liquidity=minimum_liquidity,
        price_movement_since_leader=price_movement_since_leader,
        quote_price_impact=quote_price_impact,
        slippage=slippage,
        single_position_limit=single_position_limit,
        total_exposure=total_exposure,
        daily_loss=daily_loss,
        duplicate_intent=duplicate_intent,
        conflicting_position=conflicting_position,
        scale_in_prohibition=scale_in_prohibition,
        wallet_balance=wallet_balance,
        quote_freshness=quote_freshness,
        chain_freshness=chain_freshness,
        clock_health=clock_health,
        stream_reconciliation_health=stream_reconciliation_health,
    )

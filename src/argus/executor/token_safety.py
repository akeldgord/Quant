"""argus.executor.token_safety — MASTER_SPEC.md section 68 (TOKEN
SAFETY GATE) and section 69 (PRE-ENTRY SELLABILITY PROBE), Phase 6
(``argus-phase-6-001``).

Deterministic hazard evaluation over ``token_risk_flags`` (persisted in
``token_safety_assessments``, migration ``0024``): any flag that is
``FAIL`` or ``UNKNOWN`` makes the overall status ``UNSAFE``/``UNKNOWN``
respectively -- unknown dangerous token mechanics can never become
auto-live eligible. No safety screen here is ever described as a
guarantee (section 68's own explicit caution).

Pre-entry sellability (section 69) is evaluated the same fail-closed
way: an absent reverse route, excessive reverse price impact, or a
stale reverse quote all make the opportunity ineligible -- this is an
additional safety observation, never a sellability guarantee either.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

FlagStatus = Literal["PASS", "FAIL", "UNKNOWN"]

RISK_FLAG_MINT_AUTHORITY = "mint_authority"
RISK_FLAG_FREEZE_AUTHORITY = "freeze_authority"
RISK_FLAG_TOKEN_2022_EXTENSIONS = "token_2022_extensions"
RISK_FLAG_TRANSFER_FEES = "transfer_fees"
RISK_FLAG_UNSUPPORTED_TRANSFER_BEHAVIOR = "unsupported_transfer_behavior"
RISK_FLAG_SUPPLY_CONCENTRATION = "supply_concentration"
RISK_FLAG_EXTREME_LIQUIDITY_WEAKNESS = "extreme_liquidity_weakness"
RISK_FLAG_SUSPICIOUS_MUTABILITY = "suspicious_mutability"

ALL_RISK_FLAGS: tuple[str, ...] = (
    RISK_FLAG_MINT_AUTHORITY,
    RISK_FLAG_FREEZE_AUTHORITY,
    RISK_FLAG_TOKEN_2022_EXTENSIONS,
    RISK_FLAG_TRANSFER_FEES,
    RISK_FLAG_UNSUPPORTED_TRANSFER_BEHAVIOR,
    RISK_FLAG_SUPPLY_CONCENTRATION,
    RISK_FLAG_EXTREME_LIQUIDITY_WEAKNESS,
    RISK_FLAG_SUSPICIOUS_MUTABILITY,
)

OVERALL_SAFE = "SAFE"
OVERALL_UNSAFE = "UNSAFE"
OVERALL_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TokenSafetyEvaluation:
    overall_status: str
    unsafe_flags: tuple[str, ...]
    unknown_flags: tuple[str, ...]


def evaluate_token_safety(flags: dict[str, FlagStatus]) -> TokenSafetyEvaluation:
    """Every one of ``ALL_RISK_FLAGS`` must be evidenced and ``PASS``
    for ``SAFE``. A flag absent from ``flags`` is treated exactly like
    ``UNKNOWN`` -- missing evidence is never treated as safe."""
    unsafe = tuple(f for f in ALL_RISK_FLAGS if flags.get(f) == "FAIL")
    unknown = tuple(f for f in ALL_RISK_FLAGS if flags.get(f, "UNKNOWN") == "UNKNOWN")
    if unsafe:
        return TokenSafetyEvaluation(OVERALL_UNSAFE, unsafe, unknown)
    if unknown:
        return TokenSafetyEvaluation(OVERALL_UNKNOWN, unsafe, unknown)
    return TokenSafetyEvaluation(OVERALL_SAFE, unsafe, unknown)


@dataclass(frozen=True)
class SellabilityEvidence:
    reverse_route_available: bool | None
    reverse_price_impact_fraction: Decimal | None
    reverse_quote_at: datetime | None


@dataclass(frozen=True)
class SellabilityResult:
    status: FlagStatus
    reason: str


def evaluate_pre_entry_sellability(
    evidence: SellabilityEvidence,
    *,
    cutoff: datetime,
    max_reverse_price_impact_fraction: Decimal,
    max_quote_age_seconds: Decimal,
) -> SellabilityResult:
    if evidence.reverse_route_available is None:
        return SellabilityResult("UNKNOWN", "no reverse-route evidence")
    if not evidence.reverse_route_available:
        return SellabilityResult("FAIL", "no reverse route available")
    if evidence.reverse_price_impact_fraction is None:
        return SellabilityResult("UNKNOWN", "no reverse price-impact evidence")
    if evidence.reverse_price_impact_fraction > max_reverse_price_impact_fraction:
        return SellabilityResult(
            "FAIL",
            f"reverse price impact {evidence.reverse_price_impact_fraction} exceeds "
            f"{max_reverse_price_impact_fraction}",
        )
    if evidence.reverse_quote_at is None:
        return SellabilityResult("UNKNOWN", "no reverse quote timestamp evidence")
    if evidence.reverse_quote_at > cutoff:
        return SellabilityResult("UNKNOWN", "reverse quote is from after the cutoff")
    age_seconds = Decimal((cutoff - evidence.reverse_quote_at).total_seconds())
    if age_seconds > max_quote_age_seconds:
        return SellabilityResult(
            "FAIL", f"reverse quote age {age_seconds}s exceeds {max_quote_age_seconds}s (stale)"
        )
    return SellabilityResult("PASS", "reverse route available, impact and freshness within limits")

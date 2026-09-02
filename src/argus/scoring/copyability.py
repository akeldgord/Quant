"""M5 (Copyability V1 score/confidence) — MASTER_SPEC.md section 49,
Phase 5 (``argus-phase-5-001``).

Uses PRECISELY the existing ``copyability_weights`` already frozen in
``config/signals_v1.yaml`` -- never retuned here (this instruction's own
explicit config-reuse requirement). Every per-component formula below is
byte-exact to the sealed acceptance contract's frozen text. A component
that cannot be computed keeps its frozen weight but contributes the
labeled neutral prior 50 -- never redistributed onto the remaining
components (this instruction's own explicit "no redistribution" rule).
``n=0`` (zero usable primary-horizon events) forces the overall
``copyability_score`` to ``None``, regardless of any individual
component's own availability.

Frozen normalization version name: ``copyability_components_v1``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from argus.copyability.util import clamp

COMPONENT_NORMALIZATION_VERSION = "copyability_components_v1"

NEUTRAL_PRIOR = Decimal(50)

_CONFIDENCE_ORDER = ("UNKNOWN", "LOW", "MEDIUM", "HIGH")

COMPONENT_KEYS = (
    "prospective_delayed_follower_alpha",
    "liquidity_executability",
    "post_entry_stability",
    "holding_duration_suitability",
    "latency_tolerance",
    "slippage_sensitivity",
    "sample_confidence",
)


@dataclass(frozen=True)
class ComponentValue:
    available: bool
    value: Decimal | None = None
    reason: str | None = None

    def as_dict(self, *, weight: Decimal) -> dict:
        return {
            "available": self.available,
            "value": str(self.value) if self.value is not None else None,
            "weight": str(weight),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CopyabilityInputs:
    # 1. prospective_delayed_follower_alpha: median executable return
    # fraction across comparable events at the fixed primary horizon
    # (5m), versus the explicit cash baseline.
    follower_alpha_median_return_fraction: Decimal | None = None
    follower_alpha_reason: str | None = None

    # 2. liquidity_executability
    successful_qty_matched_reverse_count: int = 0
    all_terminal_reverse_count: int = 0

    # 3. post_entry_stability: one fraction per event (nonnegative
    # successful executable outcomes / successful executable outcomes,
    # across that event's own observed horizons), averaged across events.
    per_event_stability_fractions: tuple[Decimal, ...] = ()

    # 4. holding_duration_suitability
    comparable_pairs_5m_le_30m_count: int = 0
    comparable_pairs_total: int = 0

    # 5. latency_tolerance (uses M3's comparable delay curve)
    positive_peak_return_fraction: Decimal | None = None
    latest_comparable_delay_return_fraction: Decimal | None = None
    adequate_comparable_evidence: bool = False

    # 6. slippage_sensitivity -- mean absolute price-impact FRACTION
    # (never a raw percentage-point value; the caller has already
    # converted exactly once -- see argus.copyability.loaders).
    mean_abs_price_impact_fraction: Decimal | None = None
    slippage_unavailable_reason: str | None = None

    # 7. sample_confidence
    n_events: int = 0
    k_distinct_tokens: int = 0
    coverage_numerator: int = 0
    coverage_denominator: int = 0
    history_completeness: str = "UNKNOWN"


def _available(value: Decimal) -> ComponentValue:
    return ComponentValue(available=True, value=value)


def _unavailable(reason: str) -> ComponentValue:
    return ComponentValue(available=False, reason=reason)


def _component_follower_alpha(inputs: CopyabilityInputs) -> ComponentValue:
    if inputs.follower_alpha_median_return_fraction is None:
        return _unavailable(
            inputs.follower_alpha_reason
            or "no comparable executable-return evidence at the primary horizon"
        )
    value = clamp(
        Decimal(50) + Decimal(100) * inputs.follower_alpha_median_return_fraction,
        Decimal(0),
        Decimal(100),
    )
    return _available(value)


def _component_liquidity_executability(inputs: CopyabilityInputs) -> ComponentValue:
    if inputs.all_terminal_reverse_count <= 0:
        return _unavailable("no terminal reverse-executable outcomes at the primary horizon")
    value = clamp(
        Decimal(100)
        * Decimal(inputs.successful_qty_matched_reverse_count)
        / Decimal(inputs.all_terminal_reverse_count),
        Decimal(0),
        Decimal(100),
    )
    return _available(value)


def _component_post_entry_stability(inputs: CopyabilityInputs) -> ComponentValue:
    fractions = inputs.per_event_stability_fractions
    if not fractions:
        return _unavailable("no observed executable outcomes across horizons")
    average = sum(fractions, Decimal(0)) / Decimal(len(fractions))
    value = clamp(Decimal(100) * average, Decimal(0), Decimal(100))
    return _available(value)


def _component_holding_duration_suitability(inputs: CopyabilityInputs) -> ComponentValue:
    if inputs.comparable_pairs_total <= 0:
        return _unavailable("no comparable same-event 5m/30m executable-return pairs")
    value = clamp(
        Decimal(100)
        * Decimal(inputs.comparable_pairs_5m_le_30m_count)
        / Decimal(inputs.comparable_pairs_total),
        Decimal(0),
        Decimal(100),
    )
    return _available(value)


def _component_latency_tolerance(inputs: CopyabilityInputs) -> ComponentValue:
    if inputs.positive_peak_return_fraction is None or inputs.positive_peak_return_fraction <= 0:
        if inputs.adequate_comparable_evidence:
            return _available(Decimal(0))
        return _unavailable("no positive peak and insufficient comparable delay evidence")
    if inputs.latest_comparable_delay_return_fraction is None:
        return _unavailable("no observation at the latest comparable delay")
    value = clamp(
        Decimal(100)
        * inputs.latest_comparable_delay_return_fraction
        / inputs.positive_peak_return_fraction,
        Decimal(0),
        Decimal(100),
    )
    return _available(value)


def _component_slippage_sensitivity(inputs: CopyabilityInputs) -> ComponentValue:
    if inputs.mean_abs_price_impact_fraction is None:
        return _unavailable(inputs.slippage_unavailable_reason or "IMPACT_UNIT_UNKNOWN")
    value = clamp(
        Decimal(100) * (Decimal(1) - inputs.mean_abs_price_impact_fraction),
        Decimal(0),
        Decimal(100),
    )
    return _available(value)


@dataclass(frozen=True)
class SampleConfidenceOutcome:
    component: ComponentValue
    confidence: str
    n: int
    k: int
    denominator: int
    numerator: int
    coverage: Decimal
    c: Decimal


def _sample_confidence(inputs: CopyabilityInputs) -> SampleConfidenceOutcome:
    n = inputs.n_events
    k = inputs.k_distinct_tokens
    denominator = inputs.coverage_denominator
    coverage = (
        Decimal(inputs.coverage_numerator) / Decimal(denominator) if denominator > 0 else Decimal(0)
    )
    c = min(Decimal(1), Decimal(n) / Decimal(20), Decimal(k) / Decimal(10)) * coverage

    if n == 0:
        confidence = "UNKNOWN"
    elif (
        n < 20 or k < 10 or c < Decimal("0.5") or inputs.history_completeness in ("LOW", "UNKNOWN")
    ):
        confidence = "LOW"
    elif c < Decimal("0.8") or inputs.history_completeness == "MEDIUM":
        confidence = "MEDIUM"
    else:
        confidence = "HIGH"

    component = _available(Decimal(100) * c)
    return SampleConfidenceOutcome(
        component=component,
        confidence=confidence,
        n=n,
        k=k,
        denominator=denominator,
        numerator=inputs.coverage_numerator,
        coverage=coverage,
        c=c,
    )


@dataclass(frozen=True)
class CopyabilityResult:
    score: Decimal | None
    components: dict[str, ComponentValue]
    available_weight: Decimal
    confidence: str
    sample_n: int
    sample_k: int
    sample_coverage_denominator: int
    sample_coverage: Decimal
    sample_c: Decimal


def compute_copyability(
    inputs: CopyabilityInputs, *, weights: dict[str, Decimal]
) -> CopyabilityResult:
    """``weights`` must be exactly ``config/signals_v1.yaml``'s
    ``copyability_weights`` block, converted to ``Decimal`` -- see
    ``argus.scoring.config_weights.load_copyability_weights``."""
    sample = _sample_confidence(inputs)

    components: dict[str, ComponentValue] = {
        "prospective_delayed_follower_alpha": _component_follower_alpha(inputs),
        "liquidity_executability": _component_liquidity_executability(inputs),
        "post_entry_stability": _component_post_entry_stability(inputs),
        "holding_duration_suitability": _component_holding_duration_suitability(inputs),
        "latency_tolerance": _component_latency_tolerance(inputs),
        "slippage_sensitivity": _component_slippage_sensitivity(inputs),
        "sample_confidence": sample.component,
    }

    available_weight = sum(
        (weights[key] for key, comp in components.items() if comp.available), Decimal(0)
    )

    if sample.n == 0:
        score: Decimal | None = None
    else:
        total = Decimal(0)
        for key, comp in components.items():
            weight = weights[key]
            value: Decimal = (
                comp.value if (comp.available and comp.value is not None) else NEUTRAL_PRIOR
            )
            total += weight * value
        score = total

    weight_cap = (
        "LOW"
        if available_weight < Decimal("0.5")
        else ("MEDIUM" if available_weight < Decimal(1) else "HIGH")
    )
    final_confidence = min(sample.confidence, weight_cap, key=_CONFIDENCE_ORDER.index)

    return CopyabilityResult(
        score=score,
        components=components,
        available_weight=available_weight,
        confidence=final_confidence,
        sample_n=sample.n,
        sample_k=sample.k,
        sample_coverage_denominator=sample.denominator,
        sample_coverage=sample.coverage,
        sample_c=sample.c,
    )

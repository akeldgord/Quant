"""argus.counterfactual.predation -- MASTER_SPEC.md Phase 9, section 61
(PREDATION DETECTION): a disclosed V1 heuristic composite, not a
calibrated probability (the same "V1 priors to be evaluated
prospectively" status section 38 gives the wallet qualification score
weights).

FSR-07 (final spec recovery): section 61 requires estimating all FOUR
evidence families -- follower influx, price impact, leader exit timing,
repetition frequency -- never silently omitting one while still
presenting the result as complete. ``follower_influx_mean`` and
``exit_after_influx_rate`` (leader exit timing) were already computed by
the pre-recovery build; this module now also incorporates repetition
frequency (always computable from the same raw-swap-derived exit
signal, so it always participates once the core evidence exists) and
price impact (real contemporaneous evidence, but not always available --
per FSR-07's own explicit rule, its ABSENCE must lower confidence or
make the result explicitly partial, never silently behave as zero/safe).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

# Disclosed policy constants: the level treated as "maximally predatory"
# for normalization purposes, for each of the count-shaped evidence
# families. Chosen as round, documented numbers, not derived from any
# calibration study (section 38's own V1 precedent).
DEFAULT_FOLLOWER_INFLUX_NORMALIZATION_CAP: Final[Decimal] = Decimal(10)
DEFAULT_REPETITION_NORMALIZATION_CAP: Final[int] = 3
DEFAULT_PRICE_IMPACT_NORMALIZATION_CAP: Final[Decimal] = Decimal(20)

# When price-impact evidence IS available, it modulates the core
# (follower-influx x exit-timing x repetition) signal by a factor in
# [_PRICE_IMPACT_BLEND_FLOOR, _PRICE_IMPACT_BLEND_FLOOR + 1]: a genuinely
# MEASURED zero price impact still keeps at least this fraction of the
# core score (never zeroed out by a low-but-real reading), while a
# maximal measured impact can raise the score above the price-impact-
# blind core (the final composite stays bounded to [0, 1]).
_PRICE_IMPACT_BLEND_FLOOR: Final[Decimal] = Decimal("0.5")


def normalized_follower_influx(
    follower_influx_mean: Decimal, *, cap: Decimal = DEFAULT_FOLLOWER_INFLUX_NORMALIZATION_CAP
) -> Decimal:
    if cap <= 0:
        raise ValueError("cap must be positive")
    return min(follower_influx_mean / cap, Decimal(1))


def normalized_repetition_frequency(
    repeated_pattern_count: int, *, cap: int = DEFAULT_REPETITION_NORMALIZATION_CAP
) -> Decimal:
    """How many times the leader-buy -> follower-influx -> leader-exit
    pattern has actually repeated -- a single occurrence is comparatively
    weak evidence of a deliberate strategy versus coincidence, so it
    contributes proportionally less than a pattern seen ``cap`` or more
    times."""
    if cap <= 0:
        raise ValueError("cap must be positive")
    if repeated_pattern_count <= 0:
        return Decimal(0)
    return min(Decimal(repeated_pattern_count) / Decimal(cap), Decimal(1))


def normalized_price_impact(
    price_impact_mean: Decimal, *, cap: Decimal = DEFAULT_PRICE_IMPACT_NORMALIZATION_CAP
) -> Decimal:
    if cap <= 0:
        raise ValueError("cap must be positive")
    return min(max(price_impact_mean, Decimal(0)) / cap, Decimal(1))


@dataclass(frozen=True)
class PredationScoreResult:
    score: Decimal | None
    price_impact_incorporated: bool


def compute_predation_score(
    *,
    follower_influx_mean: Decimal | None,
    exit_after_influx_rate: Decimal | None,
    repeated_pattern_count: int,
    price_impact_mean: Decimal | None,
    follower_influx_cap: Decimal = DEFAULT_FOLLOWER_INFLUX_NORMALIZATION_CAP,
    repetition_cap: int = DEFAULT_REPETITION_NORMALIZATION_CAP,
    price_impact_cap: Decimal = DEFAULT_PRICE_IMPACT_NORMALIZATION_CAP,
) -> PredationScoreResult:
    """``score`` is ``None`` when either core component (follower influx
    or leader exit timing) is unavailable -- never a fabricated partial
    score. Otherwise a bounded [0, 1] composite: high follower influx,
    a high rate of leader-exit-shortly-after that influx, AND repeated
    occurrence of the pattern all raise the score (repetition frequency
    -- a wallet that merely attracts followers without distributing to
    them, or that has done so only once, is weaker predation evidence
    than one that has repeatedly done both).

    When real price-impact evidence is available it further modulates
    the score (a higher measured adverse impact on followers raises it);
    when it is NOT available, the core score is returned UNCHANGED
    (never assumed zero, never assumed maximal) but
    ``price_impact_incorporated`` is False -- FSR-07's own explicit rule
    that missing price impact must make the result honestly partial,
    never silently behave as complete."""
    if follower_influx_mean is None or exit_after_influx_rate is None:
        return PredationScoreResult(score=None, price_impact_incorporated=False)

    core = (
        normalized_follower_influx(follower_influx_mean, cap=follower_influx_cap)
        * exit_after_influx_rate
        * normalized_repetition_frequency(repeated_pattern_count, cap=repetition_cap)
    )
    if price_impact_mean is None:
        return PredationScoreResult(score=core, price_impact_incorporated=False)

    impact_factor = _PRICE_IMPACT_BLEND_FLOOR + normalized_price_impact(
        price_impact_mean, cap=price_impact_cap
    )
    return PredationScoreResult(
        score=min(core * impact_factor, Decimal(1)), price_impact_incorporated=True
    )

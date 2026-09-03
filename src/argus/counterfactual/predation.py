"""argus.counterfactual.predation -- MASTER_SPEC.md Phase 9, section 61
(PREDATION DETECTION): a disclosed V1 heuristic composite, not a
calibrated probability (the same "V1 priors to be evaluated
prospectively" status section 38 gives the wallet qualification score
weights).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

# Disclosed policy constant: the follower-influx level (mean distinct
# followers per leader entry) treated as "maximally predatory" for
# normalization purposes. Chosen as a round, documented number, not
# derived from any calibration study.
DEFAULT_FOLLOWER_INFLUX_NORMALIZATION_CAP: Final[Decimal] = Decimal(10)


def normalized_follower_influx(
    follower_influx_mean: Decimal, *, cap: Decimal = DEFAULT_FOLLOWER_INFLUX_NORMALIZATION_CAP
) -> Decimal:
    if cap <= 0:
        raise ValueError("cap must be positive")
    return min(follower_influx_mean / cap, Decimal(1))


def compute_predation_score(
    *,
    follower_influx_mean: Decimal | None,
    exit_after_influx_rate: Decimal | None,
    cap: Decimal = DEFAULT_FOLLOWER_INFLUX_NORMALIZATION_CAP,
) -> Decimal | None:
    """``None`` when either underlying component is unavailable -- never
    a fabricated partial score. Otherwise a bounded [0, 1] composite:
    high follower influx AND a high rate of leader-exit-shortly-after
    that influx both need to hold for a high score (a wallet that merely
    attracts followers without then distributing to them is not
    predatory by this definition)."""
    if follower_influx_mean is None or exit_after_influx_rate is None:
        return None
    return normalized_follower_influx(follower_influx_mean, cap=cap) * exit_after_influx_rate

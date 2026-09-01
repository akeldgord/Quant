"""Deterministic wallet lifecycle-state transitions (MASTER_SPEC.md
section 36 WALLET LIFECYCLE; Phase 3, `argus-phase-3-001`).

``determine_tier_transition`` is a pure function: current tier + a fresh
``ScoringResult`` (+ cluster/insider evidence already folded into it) in,
either ``(new_tier, reason)`` or ``None`` out. Returning ``None`` when the
freshly-computed tier equals the current tier is deliberate and required
for restart/replay idempotency (this instruction's required test 9):
repeated scoring from identical evidence must never insert a duplicate
``wallet_tier_history`` row.

``A``/``S`` are "potentially live eligible" evidence, never live
authorization by themselves (section 36's own explicit rule, restated on
``argus.domain.wallets.Wallet.current_tier``'s own docstring) -- this
module assigns a research tier only; it has no live-arming, signing, or
execution side effect anywhere, and cannot (this instruction's own
prohibitions).

``QUARANTINE`` always takes priority over every other rule (insider/
cluster/predation evidence is exactly the "no automatic live copying"
case section 36 describes). ``RETIRED`` is deliberately never
auto-assigned in this V1 -- "persistent degradation" requires comparing
multiple snapshots over time, out of this phase's scope; the tier exists
in the schema/enum for a later phase to assign, not silently claimed here
(an explicit, disclosed scope limit, not a fabricated behavior).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from argus.domain.wallet_tier_history import (
    TIER_A,
    TIER_B,
    TIER_DISCOVERED,
    TIER_DORMANT,
    TIER_QUARANTINE,
    TIER_S,
    TIER_WATCH,
)

if TYPE_CHECKING:
    from decimal import Decimal

    from argus.wallets.scoring import ScoringResult

ALGORITHM_VERSION: Final[str] = "wallet_tier_lifecycle_v1"

# V1 frozen qualification-score tier thresholds -- deliberately simple,
# transparent cutoffs (matching this project's "no black box" ethos
# already set elsewhere), not claimed as calibrated/optimal.
_TIER_S_THRESHOLD: Final[int] = 80
_TIER_A_THRESHOLD: Final[int] = 65
_TIER_B_THRESHOLD: Final[int] = 50
_WATCH_THRESHOLD: Final[int] = 60  # for an ineligible (small-sample) wallet
_INSIDER_QUARANTINE_THRESHOLD: Final[int] = 50
_CLUSTER_QUARANTINE_THRESHOLD_PCT: Final[int] = 80
_DORMANT_RECENCY_FLOOR: Final[int] = 5  # recency score below this -> effectively no recent activity


def determine_tier_transition(
    *,
    current_tier: str | None,
    scoring: ScoringResult,
    insider_risk: Decimal | None,
    cluster_risk: Decimal | None,
) -> tuple[str, str] | None:
    if current_tier is None:
        # A wallet's very first transition, before any score exists --
        # matches section 36's own "DISCOVERED: insufficient analysis."
        return (TIER_DISCOVERED, "first tier assignment: no prior score exists")

    if (insider_risk is not None and insider_risk >= _INSIDER_QUARANTINE_THRESHOLD) or (
        cluster_risk is not None and cluster_risk >= _CLUSTER_QUARANTINE_THRESHOLD_PCT
    ):
        new_tier = TIER_QUARANTINE
        reason = (
            f"quarantined: insider_risk={insider_risk} cluster_risk={cluster_risk} -- "
            "possible insider/common-control/manipulation evidence; no automatic live copying"
        )
    elif scoring.eligible_for_qualification:
        score = scoring.qualification_score
        if score >= _TIER_S_THRESHOLD:
            new_tier = TIER_S
        elif score >= _TIER_A_THRESHOLD:
            new_tier = TIER_A
        elif score >= _TIER_B_THRESHOLD:
            new_tier = TIER_B
        else:
            new_tier = TIER_WATCH
        reason = f"eligible for qualification: qualification_score={score} -> {new_tier}"
    else:
        score = scoring.qualification_score
        new_tier = TIER_WATCH if score >= _WATCH_THRESHOLD else TIER_DISCOVERED
        reason = (
            f"not yet eligible for qualification ({scoring.sample_gate_reason}); "
            f"qualification_score={score} -> {new_tier}"
        )

    recency = scoring.component_values.get("recency")
    if (
        new_tier not in (TIER_QUARANTINE,)
        and recency is not None
        and recency < _DORMANT_RECENCY_FLOOR
    ):
        new_tier = TIER_DORMANT
        reason = (
            f"{reason}; overridden to DORMANT (recency={recency} -- no meaningful recent activity)"
        )

    if new_tier == current_tier:
        return None
    return new_tier, reason

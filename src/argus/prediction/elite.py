"""argus.prediction.elite -- MASTER_SPEC.md Phase 11 (PREDICT INFORMED
ORDER FLOW): "elite wallet" reuses Phase 3's own
``LIVE_ELIGIBLE_CANDIDATE_TIERS`` (tier S/A) unchanged, rather than
inventing a second, competing definition of "elite" (MASTER_SPEC.md
section 36's WALLET LIFECYCLE already defines A as "Strong evidence;
potentially live eligible" and S as "Exceptional evidence").
"""

from __future__ import annotations

from argus.domain.wallet_tier_history import LIVE_ELIGIBLE_CANDIDATE_TIERS as ELITE_TIERS

__all__ = ["ELITE_TIERS"]

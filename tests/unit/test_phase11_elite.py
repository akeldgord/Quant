"""Unit test for argus.prediction.elite (MASTER_SPEC.md Phase 11): "elite
wallet" reuses Phase 3's own LIVE_ELIGIBLE_CANDIDATE_TIERS unchanged.
"""

from __future__ import annotations

from argus.domain.wallet_tier_history import LIVE_ELIGIBLE_CANDIDATE_TIERS
from argus.prediction.elite import ELITE_TIERS


def test_elite_tiers_is_exactly_phase3s_live_eligible_candidate_tiers() -> None:
    assert ELITE_TIERS == LIVE_ELIGIBLE_CANDIDATE_TIERS
    assert frozenset({"A", "S"}) == ELITE_TIERS

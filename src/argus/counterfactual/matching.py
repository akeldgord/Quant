"""argus.counterfactual.matching -- MASTER_SPEC.md Phase 9, section 55
(COUNTERFACTUAL ALPHA): matched-token-set construction and forward-return
residual computation.

Matches on market-cap bucket, liquidity bucket, token-age bucket, and
launch venue -- all point-in-time features, satisfying section 55's own
"no future variable may enter matching" rule. Scope limitation (disclosed,
not fabricated): "recent momentum," "volume," "transaction rate," and
"broad market regime" are NOT used as matching dimensions in this build
-- no cheap, non-fragile infrastructure for computing them across a full
candidate-token universe exists yet in this project (see
docs/DECISION_LOG.md).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class TokenFeatures:
    token_id: uuid.UUID
    market_cap_bucket: str
    liquidity_bucket: str
    token_age_bucket: str
    launch_venue: str | None


def is_match(wallet_token: TokenFeatures, candidate: TokenFeatures) -> bool:
    if candidate.token_id == wallet_token.token_id:
        return False
    return (
        candidate.market_cap_bucket == wallet_token.market_cap_bucket
        and candidate.liquidity_bucket == wallet_token.liquidity_bucket
        and candidate.token_age_bucket == wallet_token.token_age_bucket
        and candidate.launch_venue == wallet_token.launch_venue
    )


def select_matched_control_tokens(
    wallet_token: TokenFeatures, candidates: list[TokenFeatures], *, max_control_tokens: int
) -> list[uuid.UUID]:
    """Every candidate matching ``wallet_token`` on all four dimensions,
    deterministically capped and ordered by ``token_id`` (never by
    forward-return magnitude, which would leak future information into
    which controls get selected)."""
    matches = sorted(
        (c.token_id for c in candidates if is_match(wallet_token, c)),
        key=str,
    )
    return matches[:max_control_tokens]


def compute_forward_return(price_at_entry: Decimal, price_at_horizon: Decimal) -> Decimal | None:
    if price_at_entry <= 0:
        return None
    return (price_at_horizon / price_at_entry) - Decimal(1)


def residual_selection_alpha(
    wallet_forward_return: Decimal | None, control_forward_returns: list[Decimal]
) -> Decimal | None:
    """``wallet token forward return`` minus ``matched-universe forward
    return`` (section 55) -- ``None`` when the wallet's own return is
    unavailable or no control token produced a usable return, never a
    fabricated substitute."""
    if wallet_forward_return is None or not control_forward_returns:
        return None
    matched_universe_forward_return = sum(control_forward_returns, Decimal(0)) / Decimal(
        len(control_forward_returns)
    )
    return wallet_forward_return - matched_universe_forward_return

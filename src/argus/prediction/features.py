"""argus.prediction.features -- MASTER_SPEC.md Phase 11 (PREDICT
INFORMED ORDER FLOW): pure feature-vector construction. Reuses Phase 9's
own bucket vocabulary (``argus.counterfactual.buckets``) rather than a
second, competing bucketing scheme.

Four named feature groups mirror MASTER_SPEC's own baseline list --
"token momentum only", "wallet history only", "graph + token state" --
plus the full combined set the three real candidate models (logistic
regression, regularized logistic regression, gradient-boosted trees) use.
A feature that is unavailable for a given observation is ``None`` --
``select_features`` drops that observation for that specific feature set
rather than fabricate/impute a value.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

_BUCKET_ORDINALS: Final[dict[str, float]] = {f"BUCKET_{i}": float(i) for i in range(5)}


def bucket_ordinal(bucket: str | None) -> float | None:
    if bucket is None:
        return None
    return _BUCKET_ORDINALS.get(bucket)


@dataclass(frozen=True)
class RawFeatures:
    token_market_cap_bucket: str | None
    token_liquidity_bucket: str | None
    token_age_bucket: str | None
    token_momentum_pct: Decimal | None
    wallet_selection_alpha: Decimal | None
    wallet_consistency: Decimal | None
    wallet_forward_information: Decimal | None
    wallet_discovery_effect_size: Decimal | None


FEATURE_TOKEN_MARKET_CAP_BUCKET: Final[str] = "token_market_cap_bucket"
FEATURE_TOKEN_LIQUIDITY_BUCKET: Final[str] = "token_liquidity_bucket"
FEATURE_TOKEN_AGE_BUCKET: Final[str] = "token_age_bucket"
FEATURE_TOKEN_MOMENTUM_PCT: Final[str] = "token_momentum_pct"
FEATURE_WALLET_SELECTION_ALPHA: Final[str] = "wallet_selection_alpha"
FEATURE_WALLET_CONSISTENCY: Final[str] = "wallet_consistency"
FEATURE_WALLET_FORWARD_INFORMATION: Final[str] = "wallet_forward_information"
FEATURE_WALLET_DISCOVERY_EFFECT_SIZE: Final[str] = "wallet_discovery_effect_size"

FEATURES_TOKEN_MOMENTUM: Final[tuple[str, ...]] = (
    FEATURE_TOKEN_MARKET_CAP_BUCKET,
    FEATURE_TOKEN_LIQUIDITY_BUCKET,
    FEATURE_TOKEN_AGE_BUCKET,
    FEATURE_TOKEN_MOMENTUM_PCT,
)
FEATURES_WALLET_HISTORY: Final[tuple[str, ...]] = (
    FEATURE_WALLET_SELECTION_ALPHA,
    FEATURE_WALLET_CONSISTENCY,
    FEATURE_WALLET_FORWARD_INFORMATION,
)
FEATURES_GRAPH_TOKEN_STATE: Final[tuple[str, ...]] = (
    FEATURE_WALLET_DISCOVERY_EFFECT_SIZE,
    FEATURE_TOKEN_MARKET_CAP_BUCKET,
    FEATURE_TOKEN_LIQUIDITY_BUCKET,
    FEATURE_TOKEN_MOMENTUM_PCT,
)
FEATURES_FULL: Final[tuple[str, ...]] = tuple(
    sorted(
        set(FEATURES_TOKEN_MOMENTUM)
        | set(FEATURES_WALLET_HISTORY)
        | set(FEATURES_GRAPH_TOKEN_STATE)
    )
)


def build_feature_dict(raw: RawFeatures) -> dict[str, float | None]:
    return {
        FEATURE_TOKEN_MARKET_CAP_BUCKET: bucket_ordinal(raw.token_market_cap_bucket),
        FEATURE_TOKEN_LIQUIDITY_BUCKET: bucket_ordinal(raw.token_liquidity_bucket),
        FEATURE_TOKEN_AGE_BUCKET: bucket_ordinal(raw.token_age_bucket),
        FEATURE_TOKEN_MOMENTUM_PCT: (
            float(raw.token_momentum_pct) if raw.token_momentum_pct is not None else None
        ),
        FEATURE_WALLET_SELECTION_ALPHA: (
            float(raw.wallet_selection_alpha) if raw.wallet_selection_alpha is not None else None
        ),
        FEATURE_WALLET_CONSISTENCY: (
            float(raw.wallet_consistency) if raw.wallet_consistency is not None else None
        ),
        FEATURE_WALLET_FORWARD_INFORMATION: (
            float(raw.wallet_forward_information)
            if raw.wallet_forward_information is not None
            else None
        ),
        FEATURE_WALLET_DISCOVERY_EFFECT_SIZE: (
            float(raw.wallet_discovery_effect_size)
            if raw.wallet_discovery_effect_size is not None
            else None
        ),
    }


def select_features(
    feature_dict: dict[str, float | None], names: tuple[str, ...]
) -> list[float] | None:
    values: list[float] = []
    for name in names:
        value = feature_dict.get(name)
        if value is None:
            return None
        values.append(value)
    return values

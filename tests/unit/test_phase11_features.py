"""Unit tests for argus.prediction.features (MASTER_SPEC.md Phase 11,
PREDICT INFORMED ORDER FLOW): pure feature-vector construction.
"""

from __future__ import annotations

from decimal import Decimal

from argus.prediction.features import (
    FEATURE_TOKEN_MARKET_CAP_BUCKET,
    FEATURE_TOKEN_MOMENTUM_PCT,
    FEATURE_WALLET_SELECTION_ALPHA,
    FEATURES_FULL,
    FEATURES_GRAPH_TOKEN_STATE,
    FEATURES_TOKEN_MOMENTUM,
    FEATURES_WALLET_HISTORY,
    RawFeatures,
    bucket_ordinal,
    build_feature_dict,
    select_features,
)


def _raw(**overrides: object) -> RawFeatures:
    base = {
        "token_market_cap_bucket": "BUCKET_1",
        "token_liquidity_bucket": "BUCKET_2",
        "token_age_bucket": "BUCKET_0",
        "token_momentum_pct": Decimal("0.05"),
        "wallet_selection_alpha": Decimal("1.5"),
        "wallet_consistency": Decimal("60"),
        "wallet_forward_information": Decimal("70"),
        "wallet_discovery_effect_size": Decimal("0.3"),
    }
    base.update(overrides)
    return RawFeatures(**base)  # type: ignore[arg-type]


def test_bucket_ordinal_maps_known_buckets() -> None:
    assert bucket_ordinal("BUCKET_0") == 0.0
    assert bucket_ordinal("BUCKET_4") == 4.0


def test_bucket_ordinal_none_is_none() -> None:
    assert bucket_ordinal(None) is None


def test_bucket_ordinal_unknown_label_is_none() -> None:
    assert bucket_ordinal("NOT_A_BUCKET") is None


def test_build_feature_dict_converts_all_fields() -> None:
    feature_dict = build_feature_dict(_raw())
    assert feature_dict[FEATURE_TOKEN_MARKET_CAP_BUCKET] == 1.0
    assert feature_dict[FEATURE_TOKEN_MOMENTUM_PCT] == 0.05
    assert feature_dict[FEATURE_WALLET_SELECTION_ALPHA] == 1.5


def test_build_feature_dict_preserves_none_for_missing_values() -> None:
    feature_dict = build_feature_dict(_raw(token_momentum_pct=None, wallet_selection_alpha=None))
    assert feature_dict[FEATURE_TOKEN_MOMENTUM_PCT] is None
    assert feature_dict[FEATURE_WALLET_SELECTION_ALPHA] is None


def test_select_features_returns_values_in_order() -> None:
    feature_dict = build_feature_dict(_raw())
    selected = select_features(feature_dict, FEATURES_TOKEN_MOMENTUM)
    assert selected == [1.0, 2.0, 0.0, 0.05]


def test_select_features_drops_row_when_any_named_feature_missing() -> None:
    feature_dict = build_feature_dict(_raw(token_momentum_pct=None))
    assert select_features(feature_dict, FEATURES_TOKEN_MOMENTUM) is None


def test_select_features_full_set_unaffected_by_unused_missing_feature() -> None:
    # FEATURES_WALLET_HISTORY doesn't include token_momentum_pct, so a
    # missing momentum value must not cause that specific subset to drop.
    feature_dict = build_feature_dict(_raw(token_momentum_pct=None))
    assert select_features(feature_dict, FEATURES_WALLET_HISTORY) is not None


def test_features_full_is_the_union_of_the_three_named_subsets() -> None:
    expected = (
        set(FEATURES_TOKEN_MOMENTUM)
        | set(FEATURES_WALLET_HISTORY)
        | set(FEATURES_GRAPH_TOKEN_STATE)
    )
    assert set(FEATURES_FULL) == expected

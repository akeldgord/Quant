"""Unit tests for argus.counterfactual.matching (MASTER_SPEC.md Phase 9,
section 55 COUNTERFACTUAL ALPHA): matched-token-set construction and
forward-return residual computation.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from argus.counterfactual.matching import (
    TokenFeatures,
    compute_forward_return,
    is_match,
    residual_selection_alpha,
    select_matched_control_tokens,
)


def _features(token_id: uuid.UUID, **overrides: object) -> TokenFeatures:
    defaults = {
        "market_cap_bucket": "BUCKET_1",
        "liquidity_bucket": "BUCKET_1",
        "token_age_bucket": "BUCKET_1",
        "launch_venue": "pump.fun",
    }
    defaults.update(overrides)
    return TokenFeatures(token_id=token_id, **defaults)  # type: ignore[arg-type]


def test_identical_features_match() -> None:
    wallet_token = _features(uuid.uuid4())
    candidate = _features(uuid.uuid4())
    assert is_match(wallet_token, candidate)


def test_self_never_matches() -> None:
    token_id = uuid.uuid4()
    wallet_token = _features(token_id)
    same = _features(token_id)
    assert not is_match(wallet_token, same)


def test_differing_dimension_does_not_match() -> None:
    wallet_token = _features(uuid.uuid4())
    for field_name in ("market_cap_bucket", "liquidity_bucket", "token_age_bucket", "launch_venue"):
        candidate = _features(uuid.uuid4(), **{field_name: "DIFFERENT"})
        assert not is_match(wallet_token, candidate), field_name


def test_select_matched_control_tokens_deterministic_and_capped() -> None:
    wallet_token = _features(uuid.uuid4())
    candidates = [_features(uuid.uuid4()) for _ in range(5)]
    selected_a = select_matched_control_tokens(wallet_token, candidates, max_control_tokens=3)
    selected_b = select_matched_control_tokens(wallet_token, candidates, max_control_tokens=3)
    assert selected_a == selected_b
    assert len(selected_a) == 3
    assert selected_a == sorted(selected_a, key=str)


def test_select_matched_control_tokens_excludes_non_matches() -> None:
    wallet_token = _features(uuid.uuid4())
    non_match = _features(uuid.uuid4(), launch_venue="raydium")
    selected = select_matched_control_tokens(wallet_token, [non_match], max_control_tokens=10)
    assert selected == []


def test_compute_forward_return_basic() -> None:
    assert compute_forward_return(Decimal(100), Decimal(150)) == Decimal("0.5")
    assert compute_forward_return(Decimal(100), Decimal(50)) == Decimal("-0.5")


def test_compute_forward_return_zero_entry_price_is_none() -> None:
    assert compute_forward_return(Decimal(0), Decimal(100)) is None


def test_residual_selection_alpha_basic() -> None:
    result = residual_selection_alpha(Decimal("0.5"), [Decimal("0.1"), Decimal("0.3")])
    assert result == Decimal("0.5") - Decimal("0.2")


def test_residual_selection_alpha_none_when_wallet_return_missing() -> None:
    assert residual_selection_alpha(None, [Decimal("0.1")]) is None


def test_residual_selection_alpha_none_when_no_controls() -> None:
    assert residual_selection_alpha(Decimal("0.5"), []) is None

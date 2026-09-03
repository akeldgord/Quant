"""Unit tests for argus.counterfactual.buckets (MASTER_SPEC.md Phase 9,
section 55 COUNTERFACTUAL ALPHA): fixed, disclosed matching-dimension
bucket edges.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from argus.counterfactual.buckets import liquidity_bucket, market_cap_bucket, token_age_bucket


def test_market_cap_bucket_boundaries() -> None:
    assert market_cap_bucket(Decimal(0)) == "BUCKET_0"
    assert market_cap_bucket(Decimal(49_999)) == "BUCKET_0"
    assert market_cap_bucket(Decimal(50_000)) == "BUCKET_1"
    assert market_cap_bucket(Decimal(999_999)) == "BUCKET_2"
    assert market_cap_bucket(Decimal(1_000_000)) == "BUCKET_3"
    assert market_cap_bucket(Decimal(50_000_000)) == "BUCKET_4"


def test_liquidity_bucket_boundaries() -> None:
    assert liquidity_bucket(Decimal(0)) == "BUCKET_0"
    assert liquidity_bucket(Decimal(9_999)) == "BUCKET_0"
    assert liquidity_bucket(Decimal(10_000)) == "BUCKET_1"
    assert liquidity_bucket(Decimal(2_000_000)) == "BUCKET_4"


def test_token_age_bucket_boundaries() -> None:
    assert token_age_bucket(timedelta(minutes=1)) == "BUCKET_0"
    assert token_age_bucket(timedelta(hours=1)) == "BUCKET_1"
    assert token_age_bucket(timedelta(hours=6)) == "BUCKET_2"
    assert token_age_bucket(timedelta(days=1)) == "BUCKET_3"
    assert token_age_bucket(timedelta(days=7)) == "BUCKET_4"
    assert token_age_bucket(timedelta(days=30)) == "BUCKET_4"


def test_same_bucket_for_values_within_range() -> None:
    assert market_cap_bucket(Decimal(60_000)) == market_cap_bucket(Decimal(200_000))

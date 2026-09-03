"""argus.counterfactual.buckets -- MASTER_SPEC.md Phase 9 (COUNTERFACTUAL
ALPHA + SPECIALISTS), section 55 (COUNTERFACTUAL ALPHA): fixed, disclosed
bucket edges for the matched-token-set dimensions this build implements
(market-cap, liquidity, token age). Fixed thresholds rather than adaptive
quantiles -- a quantile scheme needs a large sample to be stable, which
this project does not yet have; fixed, disclosed edges are honest about
that limitation rather than presenting spurious precision.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Final

# Disclosed policy constants (USD), ascending. A value below the first
# edge falls in the lowest bucket; at or above the last edge, the highest.
_MARKET_CAP_EDGES: Final[tuple[Decimal, ...]] = (
    Decimal(50_000),
    Decimal(250_000),
    Decimal(1_000_000),
    Decimal(10_000_000),
)
_LIQUIDITY_EDGES: Final[tuple[Decimal, ...]] = (
    Decimal(10_000),
    Decimal(50_000),
    Decimal(250_000),
    Decimal(1_000_000),
)
_TOKEN_AGE_EDGES: Final[tuple[timedelta, ...]] = (
    timedelta(hours=1),
    timedelta(hours=6),
    timedelta(days=1),
    timedelta(days=7),
)

_BUCKET_LABELS: Final[tuple[str, ...]] = (
    "BUCKET_0",
    "BUCKET_1",
    "BUCKET_2",
    "BUCKET_3",
    "BUCKET_4",
)


def _bucket(value: Decimal, edges: tuple[Decimal, ...]) -> str:
    for index, edge in enumerate(edges):
        if value < edge:
            return _BUCKET_LABELS[index]
    return _BUCKET_LABELS[len(edges)]


def market_cap_bucket(market_cap_usd: Decimal) -> str:
    return _bucket(market_cap_usd, _MARKET_CAP_EDGES)


def liquidity_bucket(liquidity_usd: Decimal) -> str:
    return _bucket(liquidity_usd, _LIQUIDITY_EDGES)


def token_age_bucket(age: timedelta) -> str:
    age_seconds = Decimal(str(age.total_seconds()))
    edges_seconds = tuple(Decimal(str(edge.total_seconds())) for edge in _TOKEN_AGE_EDGES)
    return _bucket(age_seconds, edges_seconds)

"""Small shared arithmetic helpers used across the Phase 5 mechanics."""

from __future__ import annotations

from decimal import Decimal


def clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    if value < low:
        return low
    if value > high:
        return high
    return value

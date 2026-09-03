"""Unit tests for argus.synthetic.costs (MASTER_SPEC.md Phase 10,
SYNTHETIC SUPER-WALLET): disclosed V1 realistic-cost haircut.
"""

from __future__ import annotations

from decimal import Decimal

from argus.synthetic.costs import DEFAULT_COST_BPS, apply_entry_cost, apply_exit_cost


def test_entry_cost_raises_price() -> None:
    result = apply_entry_cost(Decimal(100), cost_bps=Decimal(100))
    assert result == Decimal(100) * Decimal("1.005")


def test_exit_cost_lowers_price() -> None:
    result = apply_exit_cost(Decimal(100), cost_bps=Decimal(100))
    assert result == Decimal(100) * Decimal("0.995")


def test_zero_cost_is_identity() -> None:
    assert apply_entry_cost(Decimal(100), cost_bps=Decimal(0)) == Decimal(100)
    assert apply_exit_cost(Decimal(100), cost_bps=Decimal(0)) == Decimal(100)


def test_default_cost_bps_is_disclosed_constant() -> None:
    assert Decimal(100) == DEFAULT_COST_BPS


def test_round_trip_cost_reduces_return() -> None:
    entry = apply_entry_cost(Decimal(100), cost_bps=DEFAULT_COST_BPS)
    exit_price = apply_exit_cost(Decimal(110), cost_bps=DEFAULT_COST_BPS)
    net_return = (exit_price / entry) - Decimal(1)
    gross_return = (Decimal(110) / Decimal(100)) - Decimal(1)
    assert net_return < gross_return

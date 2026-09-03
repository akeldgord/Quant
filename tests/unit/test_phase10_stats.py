"""Unit tests for argus.synthetic.stats (MASTER_SPEC.md Phase 10,
SYNTHETIC SUPER-WALLET): win rate, profit factor, max drawdown, capital
utilization, failure rate.
"""

from __future__ import annotations

from decimal import Decimal

from argus.synthetic.stats import (
    TradeOutcome,
    compute_capital_utilization,
    compute_max_drawdown,
    compute_strategy_summary,
)


def test_max_drawdown_empty_is_none() -> None:
    assert compute_max_drawdown([]) is None


def test_max_drawdown_monotonic_gains_is_zero() -> None:
    assert compute_max_drawdown([Decimal("0.1"), Decimal("0.1"), Decimal("0.1")]) == Decimal(0)


def test_max_drawdown_peak_to_trough() -> None:
    # cumulative: 0.3, 0.1 (drawdown 0.2), 0.4 (new peak), 0.0 (drawdown 0.4)
    returns = [Decimal("0.3"), Decimal("-0.2"), Decimal("0.3"), Decimal("-0.4")]
    assert compute_max_drawdown(returns) == Decimal("0.4")


def test_capital_utilization_empty_is_none() -> None:
    assert compute_capital_utilization([], max_concurrent_positions=10) is None


def test_capital_utilization_basic() -> None:
    result = compute_capital_utilization([2, 4, 6], max_concurrent_positions=10)
    assert result == Decimal(4) / Decimal(10)


def test_capital_utilization_zero_cap_is_none() -> None:
    assert compute_capital_utilization([1, 2], max_concurrent_positions=0) is None


def test_strategy_summary_all_failures() -> None:
    trades = [
        TradeOutcome(outcome="FAILURE_NO_ENTRY_PRICE", net_return=None, exit_at_ordinal=0),
        TradeOutcome(outcome="FAILURE_NO_EXIT_TRIGGER", net_return=None, exit_at_ordinal=1),
    ]
    summary = compute_strategy_summary(trades, concurrency_samples=[], max_concurrent_positions=10)
    assert summary.trade_count == 2
    assert summary.resolved_count == 0
    assert summary.failure_count == 2
    assert summary.failure_rate == Decimal(1)
    assert summary.win_rate is None
    assert summary.profit_factor is None
    assert summary.max_drawdown is None


def test_strategy_summary_mixed_wins_and_losses() -> None:
    trades = [
        TradeOutcome(outcome="RESOLVED", net_return=Decimal("0.2"), exit_at_ordinal=0),
        TradeOutcome(outcome="RESOLVED", net_return=Decimal("-0.1"), exit_at_ordinal=1),
        TradeOutcome(outcome="RESOLVED", net_return=Decimal("0.1"), exit_at_ordinal=2),
        TradeOutcome(outcome="FAILURE_NO_EXIT_PRICE", net_return=None, exit_at_ordinal=3),
    ]
    summary = compute_strategy_summary(
        trades, concurrency_samples=[1, 2], max_concurrent_positions=4
    )
    assert summary.trade_count == 4
    assert summary.resolved_count == 3
    assert summary.failure_count == 1
    assert summary.failure_rate == Decimal(1) / Decimal(4)
    assert summary.win_rate == Decimal(2) / Decimal(3)
    assert summary.profit_factor == (Decimal("0.3") / Decimal("0.1"))
    assert summary.capital_utilization == Decimal("1.5") / Decimal(4)


def test_strategy_summary_no_losses_profit_factor_none() -> None:
    trades = [
        TradeOutcome(outcome="RESOLVED", net_return=Decimal("0.2"), exit_at_ordinal=0),
        TradeOutcome(outcome="RESOLVED", net_return=Decimal("0.1"), exit_at_ordinal=1),
    ]
    summary = compute_strategy_summary(trades, concurrency_samples=[1], max_concurrent_positions=1)
    assert summary.profit_factor is None
    assert summary.win_rate == Decimal(1)


def test_strategy_summary_median_odd_and_even() -> None:
    odd = [
        TradeOutcome(outcome="RESOLVED", net_return=Decimal(v), exit_at_ordinal=i)
        for i, v in enumerate(["1", "2", "3"])
    ]
    summary_odd = compute_strategy_summary(odd, concurrency_samples=[1], max_concurrent_positions=1)
    assert summary_odd.median_net_return == Decimal(2)

    even = [
        TradeOutcome(outcome="RESOLVED", net_return=Decimal(v), exit_at_ordinal=i)
        for i, v in enumerate(["1", "2", "3", "4"])
    ]
    summary_even = compute_strategy_summary(
        even, concurrency_samples=[1], max_concurrent_positions=1
    )
    assert summary_even.median_net_return == Decimal("2.5")

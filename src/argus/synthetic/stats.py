"""argus.synthetic.stats -- MASTER_SPEC.md Phase 10 (SYNTHETIC
SUPER-WALLET), PHASE 10's own required comparison list: executable
return, drawdown, win rate, profit factor, capital utilization, failure
rate.

``max_drawdown`` is computed on a simple additive (non-compounding),
unit-normalized equity curve -- cumulative net return in chronological
exit order -- a disclosed V1 simplification versus true dollar-weighted
portfolio compounding, since this backtest does not model real position
sizing in dollars. ``capital_utilization`` is the mean of the
concurrent-open-position count sampled at each entry event, divided by
the run's own concurrency cap -- a disclosed proxy for true
time-integrated utilization, not an exact continuous-time computation.
A metric that is undefined for a given run (e.g. ``profit_factor`` with
zero losing trades) is ``None`` -- never a fabricated infinity or zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class TradeOutcome:
    outcome: str
    net_return: Decimal | None
    exit_at_ordinal: int  # a monotonic ordering key for chronological exit order


@dataclass(frozen=True)
class StrategySummary:
    trade_count: int
    resolved_count: int
    failure_count: int
    failure_rate: Decimal | None
    win_rate: Decimal | None
    profit_factor: Decimal | None
    max_drawdown: Decimal | None
    capital_utilization: Decimal | None
    mean_net_return: Decimal | None
    median_net_return: Decimal | None


def compute_max_drawdown(returns_in_exit_order: list[Decimal]) -> Decimal | None:
    if not returns_in_exit_order:
        return None
    cumulative = Decimal(0)
    peak = Decimal(0)
    max_drawdown = Decimal(0)
    for r in returns_in_exit_order:
        cumulative += r
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    return max_drawdown


def compute_capital_utilization(
    concurrency_samples: list[int], *, max_concurrent_positions: int
) -> Decimal | None:
    if not concurrency_samples or max_concurrent_positions <= 0:
        return None
    mean_concurrency = Decimal(sum(concurrency_samples)) / Decimal(len(concurrency_samples))
    return mean_concurrency / Decimal(max_concurrent_positions)


def compute_strategy_summary(
    trades: list[TradeOutcome], *, concurrency_samples: list[int], max_concurrent_positions: int
) -> StrategySummary:
    trade_count = len(trades)
    resolved = [t for t in trades if t.outcome == "RESOLVED" and t.net_return is not None]
    resolved.sort(key=lambda t: t.exit_at_ordinal)
    failure_count = trade_count - len(resolved)

    failure_rate = Decimal(failure_count) / Decimal(trade_count) if trade_count > 0 else None

    if resolved:
        wins = sum(1 for t in resolved if t.net_return is not None and t.net_return > 0)
        win_rate = Decimal(wins) / Decimal(len(resolved))
        returns = [t.net_return for t in resolved if t.net_return is not None]
        gains = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]
        gross_loss = abs(sum(losses, Decimal(0)))
        profit_factor = (sum(gains, Decimal(0)) / gross_loss) if gross_loss > 0 else None
        mean_net_return = sum(returns, Decimal(0)) / Decimal(len(returns))
        sorted_returns = sorted(returns)
        mid = len(sorted_returns) // 2
        median_net_return = (
            sorted_returns[mid]
            if len(sorted_returns) % 2 == 1
            else (sorted_returns[mid - 1] + sorted_returns[mid]) / Decimal(2)
        )
        max_drawdown = compute_max_drawdown(returns)
    else:
        win_rate = None
        profit_factor = None
        mean_net_return = None
        median_net_return = None
        max_drawdown = None

    capital_utilization = compute_capital_utilization(
        concurrency_samples, max_concurrent_positions=max_concurrent_positions
    )

    return StrategySummary(
        trade_count=trade_count,
        resolved_count=len(resolved),
        failure_count=failure_count,
        failure_rate=failure_rate,
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        capital_utilization=capital_utilization,
        mean_net_return=mean_net_return,
        median_net_return=median_net_return,
    )

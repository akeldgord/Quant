"""Portfolio construction: volatility-targeted sizing and aggregation.

The scaling logic the whole program rests on:
  * Each (strategy, symbol) sleeve is sized so one unit of signal risks a
    fixed dollar amount per trade (risk parity across instruments — a 6J
    signal and an ES signal contribute equal $ risk).
  * Sleeve weights are then combined; total portfolio heat is capped.
  * To scale up, you raise `risk_per_trade` — nothing else changes, which
    is exactly what "easy continuous scaling" requires.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .contracts import ContractSpec, get_spec
from .engine import BacktestResult, run_backtest


@dataclass
class SleeveConfig:
    strategy: str
    symbol: str
    params: dict
    weight: float = 1.0


def contracts_for_risk(df: pd.DataFrame, spec: ContractSpec,
                       risk_per_trade: float, stop_atr: float = 2.0,
                       max_contracts: int = 20,
                       min_contracts: int = 1) -> pd.Series:
    """Contracts such that (stop_atr * ATR) * point_value * n ~= risk_per_trade.

    Uses the prior session's median ATR so sizing never peeks at today.
    `min_contracts=1` always trades at least one contract when signaled;
    set 0 for strict mode (skip if a single contract risks more than the
    budget — appropriate once you trade micros for the small accounts).
    """
    sess_atr = df.groupby("session")["atr"].median()
    prior_atr = sess_atr.shift(1)
    atr_map = df["session"].map(prior_atr)
    dollar_stop = stop_atr * atr_map * spec.point_value
    n = (risk_per_trade / dollar_stop.replace(0, np.nan)).fillna(0.0).round()
    return n.clip(min_contracts, max_contracts).astype(float)


def run_sleeve(df: pd.DataFrame, strategy_fn, spec: ContractSpec,
               params: dict | None = None, risk_per_trade: float = 250.0,
               stop_atr: float = 2.0) -> BacktestResult:
    """Run one strategy on one instrument with ATR stops and $-risk sizing."""
    from .engine import apply_stops

    params = params or {}
    unit = strategy_fn(df, **params)
    unit = apply_stops(df, unit, spec, stop_atr=stop_atr)
    size = contracts_for_risk(df, spec, risk_per_trade, stop_atr)
    return run_backtest(df, unit * size, spec)


def combine(results: list[BacktestResult],
            weights: list[float] | None = None) -> pd.Series:
    """Sum sleeve PnL on a union index (the portfolio equity driver)."""
    if weights is None:
        weights = [1.0] * len(results)
    series = [r.pnl * w for r, w in zip(results, weights)]
    out = pd.concat(series, axis=1).fillna(0.0).sum(axis=1)
    out.name = "portfolio_pnl"
    return out.sort_index()


def correlation_matrix(results: list[BacktestResult]) -> pd.DataFrame:
    """Daily PnL correlations across sleeves — keep pairwise corr < ~0.4."""
    daily = {}
    for r in results:
        key = f"{r.meta.get('strategy', '?')}/{r.symbol}"
        daily[key] = r.pnl.groupby(r.pnl.index.date).sum()
    return pd.DataFrame(daily).fillna(0.0).corr()

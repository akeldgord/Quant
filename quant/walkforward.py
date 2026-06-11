"""Walk-forward validation — the gate every sleeve must pass before money.

Protocol (anchored, rolling):
  * Split the 5 years into folds: train `train_months`, test `test_months`,
    roll forward by `test_months` (no overlap of test windows).
  * In each fold, pick the parameter set with the best train-window score
    (Sharpe penalized by drawdown), then run it untouched on the test window.
  * The concatenated test segments are the only numbers you are allowed to
    believe. If walk-forward Sharpe < ~60% of in-sample Sharpe, the sleeve
    is overfit — reject it.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .contracts import ContractSpec
from .metrics import summarize
from .portfolio import run_sleeve


def param_grid(grid: dict) -> list[dict]:
    keys = list(grid)
    return [dict(zip(keys, combo)) for combo in itertools.product(*grid.values())]


def score(stats: dict) -> float:
    """Train-selection score: Sharpe, penalized if MAR ratio is weak."""
    s = stats.get("sharpe", 0.0)
    mar = stats.get("pnl_to_maxdd", 0.0)
    if not np.isfinite(mar):
        mar = 10.0
    return s * min(1.0, mar / 1.5)


@dataclass
class FoldResult:
    train_start: object
    test_start: object
    test_end: object
    best_params: dict
    train_stats: dict
    test_stats: dict
    test_pnl: pd.Series


def walk_forward(df: pd.DataFrame, strategy_fn, spec: ContractSpec,
                 grid: dict, train_months: int = 12, test_months: int = 3,
                 risk_per_trade: float = 250.0) -> list[FoldResult]:
    sessions = pd.to_datetime(pd.Series(sorted(df["session"].unique())))
    start, end = sessions.iloc[0], sessions.iloc[-1]
    combos = param_grid(grid)

    folds: list[FoldResult] = []
    t0 = start
    while True:
        train_end = t0 + pd.DateOffset(months=train_months)
        test_end = train_end + pd.DateOffset(months=test_months)
        if train_end >= end:
            break
        d = pd.to_datetime(df["session"])
        train_df = df[(d >= t0) & (d < train_end)]
        test_df = df[(d >= train_end) & (d < min(test_end, end + pd.Timedelta(days=1)))]
        if len(train_df) == 0 or len(test_df) == 0:
            break

        best, best_s, best_stats = None, -np.inf, None
        for params in combos:
            r = run_sleeve(train_df, strategy_fn, spec, params, risk_per_trade)
            st = summarize(r.pnl, r.trades)
            sc = score(st)
            if sc > best_s:
                best, best_s, best_stats = params, sc, st

        r = run_sleeve(test_df, strategy_fn, spec, best, risk_per_trade)
        folds.append(FoldResult(t0, train_end, test_end, best,
                                best_stats, summarize(r.pnl, r.trades), r.pnl))
        t0 = t0 + pd.DateOffset(months=test_months)
    return folds


def stitch_oos(folds: list[FoldResult]) -> pd.Series:
    """Concatenate out-of-sample PnL across folds (the honest equity curve)."""
    return pd.concat([f.test_pnl for f in folds]).sort_index()

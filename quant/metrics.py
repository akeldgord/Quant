"""Performance metrics for intraday strategies."""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def daily_pnl(pnl: pd.Series) -> pd.Series:
    """Aggregate bar-level $ PnL to daily."""
    return pnl.groupby(pnl.index.date).sum()


def summarize(pnl: pd.Series, trades: pd.Series | None = None,
              capital: float = 100_000.0) -> dict:
    """Compute the metrics that matter for a scale-up program.

    pnl   : bar-level $ PnL series (DatetimeIndex)
    trades: bar-level series of trade-entry counts (optional)
    """
    d = daily_pnl(pnl)
    n_days = max(len(d), 1)
    equity = d.cumsum()
    peak = equity.cummax()
    dd = equity - peak
    ret = d / capital

    gross_win = d[d > 0].sum()
    gross_loss = -d[d < 0].sum()

    out = {
        "days": n_days,
        "total_pnl": float(d.sum()),
        "avg_daily_pnl": float(d.mean()) if n_days else 0.0,
        "daily_vol": float(d.std(ddof=0)),
        "sharpe": float(np.sqrt(TRADING_DAYS) * ret.mean() / ret.std(ddof=0))
                  if ret.std(ddof=0) > 0 else 0.0,
        "max_drawdown": float(dd.min()),
        "max_dd_pct_capital": float(dd.min() / capital),
        "win_days_pct": float((d > 0).mean()),
        "profit_factor": float(gross_win / gross_loss) if gross_loss > 0 else np.inf,
        "worst_day": float(d.min()) if n_days else 0.0,
        "best_day": float(d.max()) if n_days else 0.0,
    }
    # MAR-style ratio: annualized return over max DD — the key scaling metric.
    ann_pnl = out["avg_daily_pnl"] * TRADING_DAYS
    out["pnl_to_maxdd"] = float(ann_pnl / abs(out["max_drawdown"])) \
        if out["max_drawdown"] < 0 else np.inf
    if trades is not None:
        td = trades.groupby(trades.index.date).sum()
        out["total_trades"] = int(td.sum())
        out["trades_per_day"] = float(td.reindex(d.index, fill_value=0).mean())
    return out


def format_summary(stats: dict) -> str:
    lines = []
    fmt = {
        "days": "{:d}", "total_trades": "{:d}",
        "win_days_pct": "{:.1%}", "max_dd_pct_capital": "{:.2%}",
    }
    for k, v in stats.items():
        f = fmt.get(k, "{:,.2f}")
        try:
            lines.append(f"  {k:<20} {f.format(v)}")
        except (ValueError, TypeError):
            lines.append(f"  {k:<20} {v}")
    return "\n".join(lines)

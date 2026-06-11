"""Synthetic 1-minute data generator.

Lets you smoke-test the entire pipeline before wiring in your real 5-year
files. Produces plausible RTH bars: U-shaped intraday volume/volatility,
occasional trend days, mean-reverting chop days. NOT for measuring edge —
only for verifying plumbing, costs, and trade mechanics.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .contracts import get_spec
from .data import ET, add_session_features, filter_rth

BASE_PRICE = {"ES": 5000.0, "NQ": 18000.0, "RTY": 2100.0,
              "GC": 2300.0, "6E": 1.08, "6J": 0.0066}
DAILY_VOL = {"ES": 0.011, "NQ": 0.015, "RTY": 0.015,
             "GC": 0.010, "6E": 0.005, "6J": 0.006}


def generate_symbol(symbol: str, years: float = 1.0, seed: int = 7) -> pd.DataFrame:
    spec = get_spec(symbol)
    rng = np.random.default_rng(seed + hash(symbol) % 1000)

    days = pd.bdate_range("2021-01-04", periods=int(252 * years), tz=ET)
    start_m = spec.rth_start.hour * 60 + spec.rth_start.minute
    end_m = spec.rth_end.hour * 60 + spec.rth_end.minute
    n = end_m - start_m

    price = BASE_PRICE[symbol]
    bar_vol = DAILY_VOL[symbol] / np.sqrt(390)
    # U-shaped intraday vol multiplier.
    x = np.linspace(0, 1, n)
    smile = 0.7 + 1.2 * (np.abs(x - 0.5) * 2) ** 2

    frames = []
    for day in days:
        trend_day = rng.random() < 0.25
        drift = rng.normal(0, 2.5 * bar_vol) if trend_day else 0.0
        rets = rng.normal(drift, bar_vol * smile, n)
        if not trend_day:                       # mild mean reversion in chop
            for i in range(1, n):
                rets[i] -= 0.12 * rets[i - 1]
        closes = price * np.exp(np.cumsum(rets))
        opens = np.r_[price, closes[:-1]]
        spread = np.abs(rng.normal(0, bar_vol, n)) * closes
        highs = np.maximum(opens, closes) + spread
        lows = np.minimum(opens, closes) - spread
        vol = (rng.lognormal(8, 0.5, n) * smile).astype(int)

        idx = day.normalize() + pd.to_timedelta(np.arange(start_m, end_m), unit="m")
        frames.append(pd.DataFrame({"open": opens, "high": highs,
                                    "low": lows, "close": closes,
                                    "volume": vol}, index=idx))
        price = closes[-1] * np.exp(rng.normal(0, DAILY_VOL[symbol] * 0.3))

    df = pd.concat(frames)
    df.index = df.index.tz_convert(ET) if df.index.tz else df.index.tz_localize(ET)
    # Round to tick.
    for c in ("open", "high", "low", "close"):
        df[c] = (df[c] / spec.tick_size).round() * spec.tick_size
    return df


def prepare_synthetic(symbol: str, years: float = 1.0, seed: int = 7) -> pd.DataFrame:
    spec = get_spec(symbol)
    df = generate_symbol(symbol, years, seed)
    return add_session_features(filter_rth(df, spec))

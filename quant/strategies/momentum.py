"""Trend-day pullback momentum.

Trades WITH the intraday trend, entering on pullbacks instead of breakouts:
  * Trend filter: fast EMA vs slow EMA of 1-min closes, and price on the
    trend side of VWAP (both must agree -> avoids chop).
  * Entry: pullback of at least `pull_atr` ATRs from the running session
    extreme, then resumption (close back above fast EMA).
  * Exit: trend filter flips, or end of trade window.

This complements ORB (different entry geometry, later in the session) and
is the workhorse for the 3+ trades/day target because pullbacks recur all
session on trend days.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def trend_pullback(df: pd.DataFrame,
                   fast: int = 20,
                   slow: int = 120,
                   pull_atr: float = 1.0,
                   start_minute: int = 30,
                   end_minute: int = 360) -> pd.Series:
    m = df["minute_of_session"]
    g = df.groupby("session", sort=False)

    ema_f = g["close"].transform(lambda s: s.ewm(span=fast, adjust=False).mean())
    ema_s = g["close"].transform(lambda s: s.ewm(span=slow, adjust=False).mean())
    run_hi = g["high"].cummax()
    run_lo = g["low"].cummin()

    up = (ema_f > ema_s) & (df["close"] > df["vwap"])
    dn = (ema_f < ema_s) & (df["close"] < df["vwap"])

    pulled_back_long = (run_hi - df["low"]) >= pull_atr * df["atr"]
    pulled_back_short = (df["high"] - run_lo) >= pull_atr * df["atr"]
    resume_long = df["close"] > ema_f
    resume_short = df["close"] < ema_f

    live = (m >= start_minute) & (m < end_minute)
    long_entry = live & up & pulled_back_long & resume_long
    short_entry = live & dn & pulled_back_short & resume_short

    raw = np.where(long_entry, 1.0, np.where(short_entry, -1.0, np.nan))
    tgt = pd.Series(raw, index=df.index).groupby(df["session"]).ffill().fillna(0.0)

    # Hard exit when the trend filter flips against the position.
    tgt = tgt.where(~((tgt > 0) & dn) & ~((tgt < 0) & up), 0.0)
    return tgt.where(m < end_minute, 0.0)

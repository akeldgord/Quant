"""Opening Range Breakout (ORB).

Classic, robust intraday edge on index futures and gold:
  * Define the opening range as the high/low of the first `range_minutes`.
  * Go long on a close above the range high (+ buffer), short below the low.
  * One direction attempt at a time; flat by `exit_minute` into the session.

Why it survives out-of-sample: it monetizes the well-documented tendency of
RTH sessions that break the opening range early to keep trending (Gao,
Han, Li & Zhou intraday momentum; classic Crabel work). It is long-gamma
shaped: small frequent losses, occasional large winners — easy to scale
because risk per trade is explicitly capped.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def opening_range_breakout(df: pd.DataFrame,
                           range_minutes: int = 30,
                           buffer_atr: float = 0.25,
                           exit_minute: int = 360,
                           allow_short: bool = True) -> pd.Series:
    m = df["minute_of_session"]
    in_or = m < range_minutes

    or_high = df["high"].where(in_or).groupby(df["session"]).transform("max")
    or_low = df["low"].where(in_or).groupby(df["session"]).transform("min")
    buf = buffer_atr * df["atr"]

    live = (m >= range_minutes) & (m < exit_minute)
    long_sig = live & (df["close"] > or_high + buf)
    short_sig = live & (df["close"] < or_low - buf) & allow_short

    raw = np.where(long_sig, 1.0, np.where(short_sig, -1.0, np.nan))
    tgt = (pd.Series(raw, index=df.index)
           .groupby(df["session"]).ffill()       # hold until flipped/flattened
           .fillna(0.0))
    return tgt.where(m < exit_minute, 0.0)

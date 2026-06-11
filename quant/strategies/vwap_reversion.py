"""VWAP mean reversion.

Fades stretched moves away from the session-anchored VWAP:
  * Entry: close more than `entry_atr` ATRs below (long) / above (short) VWAP,
    with a falling-knife guard (last bar must already turn back toward VWAP).
  * Exit: price tags VWAP, or the position has been held `max_hold` minutes.

This is the natural diversifier to ORB: it is short-vol shaped and pays on
chop days when breakouts bleed. Works best on ES/GC/6E; use a wider entry
band on NQ/RTY. Run it only in the midday window where reversion dominates.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def vwap_reversion(df: pd.DataFrame,
                   entry_atr: float = 3.0,
                   start_minute: int = 45,
                   end_minute: int = 330,
                   max_hold: int = 60) -> pd.Series:
    m = df["minute_of_session"]
    dist = df["close"] - df["vwap"]
    stretch = dist / df["atr"].replace(0, np.nan)
    turning_up = df["close"] > df["close"].shift(1)
    turning_dn = df["close"] < df["close"].shift(1)
    live = (m >= start_minute) & (m < end_minute)

    long_entry = live & (stretch < -entry_atr) & turning_up
    short_entry = live & (stretch > entry_atr) & turning_dn

    sess = df["session"].to_numpy()
    le, se = long_entry.to_numpy(), short_entry.to_numpy()
    d = dist.to_numpy(float)
    mm = m.to_numpy()

    out = np.zeros(len(df))
    cur, held = 0.0, 0
    for i in range(len(df)):
        if i > 0 and sess[i] != sess[i - 1]:
            cur, held = 0.0, 0
        if cur != 0:
            held += 1
            tagged = (cur > 0 and d[i] >= 0) or (cur < 0 and d[i] <= 0)
            if tagged or held >= max_hold or mm[i] >= end_minute:
                cur, held = 0.0, 0
        if cur == 0:
            if le[i]:
                cur, held = 1.0, 0
            elif se[i]:
                cur, held = -1.0, 0
        out[i] = cur
    return pd.Series(out, index=df.index, name="target")

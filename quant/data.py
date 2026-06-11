"""Loading and preparing 1-minute futures data.

Expected input: one CSV (or parquet) per symbol with columns
    timestamp, open, high, low, close, volume
where timestamp is either tz-aware or assumed US/Eastern.

Drop your real 5-year files into ./data as e.g. ES.csv, NQ.csv, ...
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .contracts import ContractSpec, get_spec

ET = "America/New_York"
REQUIRED_COLS = ["open", "high", "low", "close", "volume"]


def load_minute_bars(path: str | Path, tz: str = ET) -> pd.DataFrame:
    """Load 1-minute OHLCV bars and normalize the index to US/Eastern."""
    path = Path(path)
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)
    cols = {c.lower().strip(): c for c in df.columns}
    ts_col = next((cols[k] for k in ("timestamp", "datetime", "date", "time")
                   if k in cols), None)
    if ts_col is not None:
        df[ts_col] = pd.to_datetime(df[ts_col])
        df = df.set_index(ts_col)
    df.columns = [c.lower().strip() for c in df.columns]
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} missing columns: {missing}")
    if df.index.tz is None:
        df.index = df.index.tz_localize(tz)
    else:
        df.index = df.index.tz_convert(tz)
    df = df[REQUIRED_COLS].sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def filter_rth(df: pd.DataFrame, spec: ContractSpec) -> pd.DataFrame:
    """Keep only bars inside the contract's liquid RTH window (ET)."""
    t = df.index.time
    mask = (t >= spec.rth_start) & (t < spec.rth_end)
    out = df[mask].copy()
    out["session"] = out.index.date
    return out


def add_session_features(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorized per-session features used by the strategies.

    Adds: minute_of_session, session_open, vwap (session-anchored),
    atr (rolling 20-bar true range EMA), prev_close.
    """
    df = df.copy()
    g = df.groupby("session", sort=False)

    df["minute_of_session"] = g.cumcount()
    df["session_open"] = g["open"].transform("first")

    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = tp * df["volume"]
    cum_pv = pv.groupby(df["session"]).cumsum()
    cum_v = df["volume"].groupby(df["session"]).cumsum().replace(0, np.nan)
    df["vwap"] = cum_pv / cum_v

    prev_close = df["close"].shift(1)
    tr = np.maximum.reduce([
        (df["high"] - df["low"]).to_numpy(),
        (df["high"] - prev_close).abs().to_numpy(),
        (df["low"] - prev_close).abs().to_numpy(),
    ])
    df["atr"] = pd.Series(tr, index=df.index).ewm(span=20, adjust=False).mean()
    df["prev_close"] = prev_close
    return df


def prepare_symbol(path: str | Path, symbol: str) -> pd.DataFrame:
    """Full pipeline: load -> RTH filter -> session features."""
    spec = get_spec(symbol)
    df = load_minute_bars(path)
    df = filter_rth(df, spec)
    return add_session_features(df)

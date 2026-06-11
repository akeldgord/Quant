"""Vectorized bar-replay backtest engine.

Execution model (deliberately conservative):
  * A strategy emits a target position (in contracts, signed) for each bar,
    computed using ONLY information available at that bar's close.
  * The engine executes the position change at the NEXT bar's open.
  * Slippage is charged per side in ticks; commission per round turn.
  * All positions are force-flattened on the last bar of each session —
    no overnight risk, which is what keeps drawdowns scalable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .contracts import ContractSpec


@dataclass
class BacktestResult:
    symbol: str
    pnl: pd.Series                 # bar-level net $ PnL
    position: pd.Series            # held position per bar
    trades: pd.Series              # entry count per bar (round-turn starts)
    costs: pd.Series               # $ friction per bar
    meta: dict = field(default_factory=dict)


def run_backtest(df: pd.DataFrame, target: pd.Series,
                 spec: ContractSpec) -> BacktestResult:
    """Replay `target` positions over `df` (RTH bars with 'session' column)."""
    target = target.reindex(df.index).fillna(0.0)

    # Force flat on the last bar of every session.
    last_bar = df.groupby("session", sort=False).cumcount(ascending=False) == 0
    target = target.where(~last_bar, 0.0)

    # Position held during bar t = target decided at close of t-1,
    # but never carry across sessions.
    same_session = df["session"].eq(df["session"].shift(1))
    pos = target.shift(1).where(same_session, 0.0).fillna(0.0)

    open_px = df["open"].to_numpy(float)
    close_px = df["close"].to_numpy(float)
    p = pos.to_numpy(float)

    # Bar PnL: position held over (open_t -> close_t) plus the carry of the
    # previous close -> this open for unchanged positions. Equivalent and
    # simpler: mark position to market close-to-close, except fills happen
    # at the open. Split into two legs:
    prev_close = np.r_[close_px[0], close_px[:-1]]
    prev_pos = np.r_[0.0, p[:-1]]
    carried = np.where(same_session.to_numpy(), prev_pos, 0.0)
    gap_pnl = carried * (open_px - prev_close)          # held through the gap
    intrabar_pnl = p * (close_px - open_px)             # held open -> close
    gross = (gap_pnl + intrabar_pnl) * spec.point_value

    # Friction on every contract traded (position change), priced per side.
    delta = np.abs(p - np.where(same_session.to_numpy(), prev_pos, 0.0))
    per_side = spec.commission_rt / 2.0 + spec.slippage_ticks * spec.tick_value
    costs = delta * per_side

    # Trade entries: flat->nonflat or sign flip.
    sign, prev_sign = np.sign(p), np.sign(np.where(same_session.to_numpy(), prev_pos, 0.0))
    entries = ((sign != 0) & (sign != prev_sign)).astype(int)

    idx = df.index
    return BacktestResult(
        symbol=spec.symbol,
        pnl=pd.Series(gross - costs, index=idx, name="pnl"),
        position=pd.Series(p, index=idx, name="position"),
        trades=pd.Series(entries, index=idx, name="trades"),
        costs=pd.Series(costs, index=idx, name="costs"),
    )


def apply_stops(df: pd.DataFrame, target: pd.Series, spec: ContractSpec,
                stop_atr: float = 2.0, take_atr: float = 0.0) -> pd.Series:
    """Overlay a per-entry ATR stop (and optional target) on a target series.

    Iterates sessions; once stopped, stays flat until the strategy signal
    goes flat or flips (prevents instant re-entry into the same losing idea).
    Conservative: assumes the stop fills at the stop level only if the bar's
    range touched it, else at the close.
    """
    tgt = target.reindex(df.index).fillna(0.0).to_numpy(float).copy()
    close = df["close"].to_numpy(float)
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    atr = df["atr"].to_numpy(float)
    session = df["session"].to_numpy()

    out = np.zeros_like(tgt)
    entry_px, cur, stopped_sign = np.nan, 0.0, 0.0
    for i in range(len(tgt)):
        if i > 0 and session[i] != session[i - 1]:
            cur, entry_px, stopped_sign = 0.0, np.nan, 0.0
        want = tgt[i]
        if stopped_sign != 0 and np.sign(want) != stopped_sign:
            stopped_sign = 0.0      # signal reset; re-arm
        if stopped_sign != 0:
            want = 0.0
        if np.sign(want) != np.sign(cur) or (cur == 0 and want != 0):
            entry_px = close[i] if want != 0 else np.nan
        cur = want
        if cur != 0 and np.isfinite(entry_px) and np.isfinite(atr[i]) and atr[i] > 0:
            stop = entry_px - np.sign(cur) * stop_atr * atr[i]
            hit_stop = low[i] <= stop if cur > 0 else high[i] >= stop
            hit_take = False
            if take_atr > 0:
                take = entry_px + np.sign(cur) * take_atr * atr[i]
                hit_take = high[i] >= take if cur > 0 else low[i] <= take
            if hit_stop:
                stopped_sign = np.sign(cur)
                cur, entry_px = 0.0, np.nan
            elif hit_take:
                cur, entry_px = 0.0, np.nan
        out[i] = cur
    return pd.Series(out, index=df.index, name="target")

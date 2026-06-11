# Intraday Futures Quant Portfolio — ES / NQ / RTY / GC / 6E / 6J

A research framework plus a trading playbook for an RTH-only intraday futures
program: **3+ trades/day on average, consistently profitable, low drawdown,
built for continuous scaling.** Designed around 5 years of clean 1-minute data.

> Note: "NY" in the original brief is interpreted as **NQ** (E-mini Nasdaq-100).
> If you meant something else, only `quant/contracts.py` needs editing.

---

## 1. The advisor's view: what actually works for this brief

Your constraints (intraday RTH, high frequency-of-opportunity, low drawdown,
scalable) point to a specific design, not a single magic strategy:

1. **No overnight positions, ever.** The engine force-flattens at the session
   close. Overnight gaps are the #1 source of unscalable tail risk.
2. **Edge comes from the portfolio, not one system.** Three uncorrelated
   strategy families x six instruments = many small, independent bets. That is
   what compresses drawdown relative to return (the MAR ratio), which is the
   metric that determines how fast you can scale.
3. **Fixed dollar risk per trade, ATR-sized.** Every entry risks the same
   dollars whether it's 6J or NQ. Scaling up = raising one number
   (`risk_per_trade`). Nothing else changes. That is "easy continuous scaling."
4. **Walk-forward or it didn't happen.** With 1-minute data it is trivially
   easy to overfit. Only stitched out-of-sample results count.

### The three strategy families

| Strategy | Shape | Instruments | Why it earns |
|---|---|---|---|
| **Opening Range Breakout** (`orb`) | Long-vol: many small losses, few big wins | ES, NQ, RTY, GC | Early-session range breaks tend to extend (documented intraday momentum). Risk per trade is hard-capped by the ATR stop. |
| **VWAP Mean Reversion** (`vwap_reversion`) | Short-vol: many small wins | ES, GC, 6E | Stretched moves away from session VWAP revert in the midday window. Pays exactly on the chop days where ORB bleeds — the key diversifier. |
| **Trend-Day Pullback** (`trend_pullback`) | Trend-following, multiple entries/day | ES, NQ, GC, 6E, 6J | On trend days, pullbacks to the fast EMA recur all session. This sleeve is the workhorse for the 3+ trades/day target. |

Session windows (ET, defined in `quant/contracts.py`): equity indices
09:30–16:00, GC 08:20–13:30 (COMEX pit liquidity), 6E/6J 08:00–15:00
(London/NY overlap). FX futures have most of their tradable intraday movement
in that overlap, not in the official 23-hour session.

### Cost honesty

Every backtest charges commission (~$4 RT) plus per-side slippage (0.75 tick
ES up to 1.25 ticks RTY/6J). At 3+ trades/day, friction is the silent killer:
a strategy that looks great frictionless and dies with 1-tick slippage was
never a strategy. RTY and 6J books are thin — never assume better than 1 tick
there.

---

## 2. Repository layout

```
quant/
  contracts.py        # tick sizes, point values, sessions, cost model
  data.py             # 1-min loader, RTH filter, VWAP/ATR session features
  engine.py           # vectorized backtester: next-bar-open fills, ATR stops,
                      #   forced session-close flatten
  metrics.py          # Sharpe, max DD, MAR (pnl_to_maxdd), trades/day, ...
  portfolio.py        # $-risk sizing, sleeve runner, combiner, correlations
  walkforward.py      # rolling train/test parameter selection + OOS stitching
  synth.py            # synthetic data generator (plumbing tests ONLY)
  strategies/
    orb.py            # opening range breakout
    vwap_reversion.py # VWAP fade
    momentum.py       # trend-day pullback
scripts/
  run_backtest.py     # full book across the universe
  run_walkforward.py  # validation gate for one (strategy, symbol) sleeve
```

## 3. Quick start

```bash
pip install -r requirements.txt

# Smoke-test the plumbing (synthetic data — numbers are meaningless):
python3 scripts/run_backtest.py --synthetic --years 1
python3 scripts/run_walkforward.py --strategy orb --symbol ES --synthetic --years 2

# With your real 5-year files (data/ES.csv ... data/6J.csv with columns
# timestamp,open,high,low,close,volume; timestamps tz-aware or US/Eastern):
python3 scripts/run_backtest.py --data-dir data --risk-per-trade 250
python3 scripts/run_walkforward.py --strategy orb --symbol ES --data-dir data
```

Data note: use **back-adjusted continuous contracts** (volume-rolled).
Unadjusted splices create phantom gaps that fake or destroy edges.

## 4. The validation gate (non-negotiable)

A sleeve goes live only if, on **stitched walk-forward out-of-sample** results
(12-month train / 3-month test, rolled across all 5 years):

- OOS Sharpe ≥ 1.0 **and** ≥ 60% of in-sample Sharpe (else: overfit, reject)
- OOS profit factor ≥ 1.25 after costs
- OOS max drawdown ≤ 12x average winning day
- Parameter stability: best params shouldn't lurch fold-to-fold; a flat
  performance plateau around the optimum beats a sharp peak every time
- Edge survives doubling the slippage assumption

Expect roughly half the (strategy, symbol) cells in the book to fail this.
That's the gate working. Trade only the survivors.

## 5. Portfolio risk rules

- **Per-trade risk:** start at 0.25% of capital (e.g. $250 on $100k), 2-ATR stop.
- **Daily loss limit:** 1% of capital → flat, done for the day. Hard rule.
- **Portfolio heat cap:** max 3 concurrent positions' worth of open risk.
- **Correlation budget:** monitor `portfolio.correlation_matrix`; if two
  sleeves' daily PnL correlate > 0.5, halve the weaker one. (ES/NQ/RTY sleeves
  of the same strategy will correlate — that's why each strategy runs on a
  *subset* of the universe in `scripts/run_backtest.py`.)

## 6. Scaling protocol

1. Run live at base size for 60+ trading days. Compare realized slippage and
   trades/day to the backtest assumptions; recalibrate the cost model.
2. If realized MAR ratio ≥ 70% of OOS backtest: raise `risk_per_trade` by 25%.
3. Repeat. **Never scale during a drawdown**; resume only after a new equity high.
4. Cut sleeve size 50% if its rolling 60-day OOS-vs-live PnL gap exceeds 2
   standard deviations (edge decay detector); retire after another 60 bad days.
5. Capacity is not your problem until well past $5k risk/trade on ES/NQ/GC;
   RTY and 6J will hit slippage walls first — cap their sleeves earlier.

## 7. Honest expectations

After costs, a well-run program of this type plausibly delivers a **portfolio
Sharpe of 1.5–2.5 with max drawdowns in the 5–10% region** — not the absurd
numbers a frictionless 1-minute backtest (or the synthetic smoke test) prints.
Any single-strategy backtest on 5 years of minute data showing Sharpe > 3
after costs is almost certainly a bug, lookahead, or overfit. The framework's
execution model (next-bar-open fills, forced flatten, conservative slippage,
prior-session sizing) is built to make those mistakes hard, but the
walk-forward gate is the only real defense.

#!/usr/bin/env python3
"""Run the three-strategy portfolio across the universe.

With real data:
    python scripts/run_backtest.py --data-dir data
    (expects data/ES.csv, data/NQ.csv, ... with timestamp,open,high,low,close,volume)

Smoke test with synthetic data (plumbing check only, NOT edge measurement):
    python scripts/run_backtest.py --synthetic --years 1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant.contracts import UNIVERSE, get_spec
from quant.data import prepare_symbol
from quant.metrics import format_summary, summarize
from quant.portfolio import combine, run_sleeve
from quant.strategies import STRATEGIES

# Which strategies run on which instruments (see README for rationale).
BOOK = {
    "orb": ["ES", "NQ", "RTY", "GC"],
    "vwap_reversion": ["ES", "GC", "6E"],
    "trend_pullback": ["ES", "NQ", "GC", "6E", "6J"],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--symbols", nargs="*", default=UNIVERSE)
    ap.add_argument("--risk-per-trade", type=float, default=250.0)
    ap.add_argument("--capital", type=float, default=100_000.0)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--years", type=float, default=1.0)
    args = ap.parse_args()

    data = {}
    for sym in args.symbols:
        if args.synthetic:
            from quant.synth import prepare_synthetic
            data[sym] = prepare_synthetic(sym, years=args.years)
        else:
            path = None
            for ext in (".csv", ".parquet"):
                p = Path(args.data_dir) / f"{sym}{ext}"
                if p.exists():
                    path = p
                    break
            if path is None:
                print(f"[skip] no data file for {sym} in {args.data_dir}/")
                continue
            data[sym] = prepare_symbol(path, sym)

    if not data:
        print("No data loaded. Use --synthetic for a smoke test.")
        return 1

    results = []
    for strat, syms in BOOK.items():
        fn = STRATEGIES[strat]
        for sym in syms:
            if sym not in data:
                continue
            r = run_sleeve(data[sym], fn, get_spec(sym),
                           risk_per_trade=args.risk_per_trade)
            r.meta["strategy"] = strat
            results.append(r)
            st = summarize(r.pnl, r.trades, args.capital)
            print(f"\n=== {strat} / {sym} ===")
            print(format_summary(st))

    import pandas as pd

    port = combine(results)
    trades = pd.concat([r.trades for r in results], axis=1).fillna(0).sum(axis=1)
    print("\n========== PORTFOLIO ==========")
    print(format_summary(summarize(port, trades, args.capital)))

    if args.synthetic:
        print("\n[note] Synthetic data: numbers above validate plumbing only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

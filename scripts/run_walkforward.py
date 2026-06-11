#!/usr/bin/env python3
"""Walk-forward validation for one (strategy, symbol) sleeve.

Example (real data):
    python scripts/run_walkforward.py --strategy orb --symbol ES --data-dir data

Smoke test:
    python scripts/run_walkforward.py --strategy orb --symbol ES --synthetic --years 2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant.contracts import get_spec
from quant.data import prepare_symbol
from quant.metrics import format_summary, summarize
from quant.strategies import STRATEGIES
from quant.walkforward import stitch_oos, walk_forward

GRIDS = {
    "orb": {"range_minutes": [15, 30, 60], "buffer_atr": [0.0, 0.25, 0.5]},
    "vwap_reversion": {"entry_atr": [2.5, 3.0, 3.5], "max_hold": [45, 60, 90]},
    "trend_pullback": {"fast": [15, 20, 30], "pull_atr": [0.75, 1.0, 1.5]},
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True, choices=list(STRATEGIES))
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--train-months", type=int, default=12)
    ap.add_argument("--test-months", type=int, default=3)
    ap.add_argument("--risk-per-trade", type=float, default=250.0)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--years", type=float, default=2.0)
    args = ap.parse_args()

    if args.synthetic:
        from quant.synth import prepare_synthetic
        df = prepare_synthetic(args.symbol, years=args.years)
    else:
        path = None
        for ext in (".csv", ".parquet"):
            p = Path(args.data_dir) / f"{args.symbol}{ext}"
            if p.exists():
                path = p
                break
        if path is None:
            print(f"No data file for {args.symbol} in {args.data_dir}/")
            return 1
        df = prepare_symbol(path, args.symbol)

    folds = walk_forward(df, STRATEGIES[args.strategy], get_spec(args.symbol),
                         GRIDS[args.strategy], args.train_months,
                         args.test_months, args.risk_per_trade)
    if not folds:
        print("Not enough data for the requested train/test windows.")
        return 1

    for i, f in enumerate(folds):
        print(f"\n--- fold {i}: test {f.test_start.date()} -> {f.test_end.date()}"
              f"  params={f.best_params} ---")
        print(f"  train sharpe={f.train_stats['sharpe']:.2f}  "
              f"test sharpe={f.test_stats['sharpe']:.2f}  "
              f"test pnl=${f.test_stats['total_pnl']:,.0f}")

    oos = stitch_oos(folds)
    print("\n========== STITCHED OUT-OF-SAMPLE ==========")
    print(format_summary(summarize(oos)))
    if args.synthetic:
        print("\n[note] Synthetic data: validates plumbing only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run the strategy backtest and print an honest report.

Usage:
  python scripts/run_backtest.py                 # synthetic demo data
  python scripts/run_backtest.py --csv trades.csv  # real data (columns: price,outcome[,market_id])
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from polymarket_strategy.backtest import run_backtest
from polymarket_strategy.data import generate_synthetic_trades, load_trades_csv
from polymarket_strategy.strategy import StrategyConfig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", help="path to a CSV of historical trades (price,outcome[,market_id])")
    parser.add_argument("--min-delta", type=float, default=0.02)
    parser.add_argument("--min-price", type=float, default=0.80)
    parser.add_argument("--max-price", type=float, default=0.99)
    parser.add_argument("--kelly-fraction", type=float, default=0.25, help="fractional Kelly cap")
    parser.add_argument("--train-frac", type=float, default=0.5)
    parser.add_argument("--starting-bankroll", type=float, default=100.0)
    parser.add_argument("--n-synthetic", type=int, default=20000)
    args = parser.parse_args()

    if args.csv:
        trades = load_trades_csv(args.csv)
        source = args.csv
    else:
        trades = generate_synthetic_trades(n=args.n_synthetic)
        source = f"SYNTHETIC demo data (n={args.n_synthetic}) -- not real Polymarket history"

    config = StrategyConfig(
        min_delta=args.min_delta,
        min_price=args.min_price,
        max_price=args.max_price,
        kelly_fraction_cap=args.kelly_fraction,
    )

    report = run_backtest(
        trades,
        config=config,
        train_frac=args.train_frac,
        starting_bankroll=args.starting_bankroll,
    )

    print(f"data source: {source}")
    print(f"price range traded: [{args.min_price}, {args.max_price}], min_delta={args.min_delta}")
    print(f"train_frac={args.train_frac} (calibration fit on train, all results below are held-out test)")
    print()
    print(report.summary())
    if report.n_taken == 0:
        print("\nNo trades were taken -- no priced edge cleared min_delta after the train/test split.")


if __name__ == "__main__":
    main()

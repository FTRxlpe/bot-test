#!/usr/bin/env python3
"""Run the BTC cross-market arbitrage backtest and print an honest report.

Usage:
  python scripts/run_btc_backtest.py                    # synthetic demo data
  python scripts/run_btc_backtest.py --csv quotes.csv    # real data (columns: timestamp_ms,market,price)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from btc_arbitrage.backtest import run_backtest
from btc_arbitrage.data import generate_synthetic_snapshots, load_snapshots_csv
from btc_arbitrage.strategy import StrategyConfig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", help="path to a CSV of timestamped quotes (timestamp_ms,market,price)")
    parser.add_argument("--latency-ms", type=int, default=250, help="round-trip time to detect + place both legs")
    parser.add_argument("--taker-fee-bps", type=float, default=10.0)
    parser.add_argument("--slippage-bps-per-leg", type=float, default=5.0)
    parser.add_argument("--kelly-fraction", type=float, default=0.25, help="fractional Kelly cap")
    parser.add_argument("--train-frac", type=float, default=0.5)
    parser.add_argument("--starting-bankroll", type=float, default=10_000.0)
    parser.add_argument("--n-synthetic-steps", type=int, default=200_000)
    args = parser.parse_args()

    if args.csv:
        snapshots = load_snapshots_csv(args.csv)
        source = args.csv
    else:
        snapshots = generate_synthetic_snapshots(n_steps=args.n_synthetic_steps)
        source = f"SYNTHETIC demo data (n_steps={args.n_synthetic_steps}) -- not real exchange history"

    config = StrategyConfig(
        latency_ms=args.latency_ms,
        taker_fee_bps=args.taker_fee_bps,
        slippage_bps_per_leg=args.slippage_bps_per_leg,
        kelly_fraction_cap=args.kelly_fraction,
    )

    report = run_backtest(
        snapshots,
        config=config,
        train_frac=args.train_frac,
        starting_bankroll=args.starting_bankroll,
    )

    print(f"data source: {source}")
    print(
        f"latency_ms={args.latency_ms} taker_fee_bps={args.taker_fee_bps} "
        f"slippage_bps_per_leg={args.slippage_bps_per_leg}"
    )
    print(f"train_frac={args.train_frac} (calibration fit on train, all results below are held-out test)")
    print()
    print(report.summary())
    if report.n_taken == 0:
        print(
            "\nNo trades were taken -- no gap-size bucket cleared costs+latency after "
            "the train/test split, or there wasn't enough train data to calibrate one."
        )


if __name__ == "__main__":
    main()

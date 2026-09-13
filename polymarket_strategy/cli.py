#!/usr/bin/env python3
"""Unified command-line entry point.

  backtest       single train/test split (see polymarket_strategy.backtest.run_backtest)
  walk-forward   multi-fold expanding-window backtest with the risk manager wired in
  paper          poll live Polymarket markets and paper-trade (no real orders, default)
  live           poll live Polymarket markets and place REAL orders -- requires
                 --live plus POLYMARKET_LIVE_TRADING=true plus POLYMARKET_PRIVATE_KEY

`paper` and `live` both require a calibration CSV (the output of
scripts/fetch_polymarket_data.py) to fit the calibration curve they trade
against -- there is no live recalibration loop; refit periodically offline
and restart with a fresh CSV.
"""
from __future__ import annotations

import argparse
import sys
import time

from .backtest import run_backtest, run_walk_forward_backtest
from .data import generate_synthetic_trades, load_trades_csv
from .executor import LiveTradingNotConfirmed, make_broker
from .pricing import calibration_curve
from .risk_manager import RiskLimits
from .strategy import StrategyConfig


def _add_strategy_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--min-delta", type=float, default=0.02)
    parser.add_argument("--min-price", type=float, default=0.80)
    parser.add_argument("--max-price", type=float, default=0.99)
    parser.add_argument("--kelly-fraction", type=float, default=0.25, help="fractional Kelly cap")


def _add_risk_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-daily-loss-fraction", type=float, default=0.05)
    parser.add_argument("--max-consecutive-losses", type=int, default=4)
    parser.add_argument("--cooldown-trades", type=int, default=5)
    parser.add_argument("--hard-max-stake-fraction", type=float, default=0.02)


def _strategy_config_from_args(args) -> StrategyConfig:
    return StrategyConfig(
        min_delta=args.min_delta,
        min_price=args.min_price,
        max_price=args.max_price,
        kelly_fraction_cap=args.kelly_fraction,
    )


def _risk_limits_from_args(args) -> RiskLimits:
    return RiskLimits(
        max_daily_loss_fraction=args.max_daily_loss_fraction,
        max_consecutive_losses=args.max_consecutive_losses,
        cooldown_trades=args.cooldown_trades,
        hard_max_stake_fraction=args.hard_max_stake_fraction,
    )


def cmd_backtest(args) -> None:
    trades = load_trades_csv(args.csv) if args.csv else generate_synthetic_trades(n=args.n_synthetic)
    source = args.csv or f"SYNTHETIC demo data (n={args.n_synthetic}) -- not real Polymarket history"
    config = _strategy_config_from_args(args)

    report = run_backtest(trades, config=config, train_frac=args.train_frac, starting_bankroll=args.starting_bankroll)

    print(f"data source: {source}")
    print(f"price range traded: [{args.min_price}, {args.max_price}], min_delta={args.min_delta}")
    print(f"train_frac={args.train_frac} (calibration fit on train, all results below are held-out test)")
    print()
    print(report.summary())
    if report.n_taken == 0:
        print("\nNo trades were taken -- no priced edge cleared min_delta after the train/test split.")


def cmd_walk_forward(args) -> None:
    trades = load_trades_csv(args.csv) if args.csv else generate_synthetic_trades(n=args.n_synthetic)
    source = args.csv or f"SYNTHETIC demo data (n={args.n_synthetic}) -- not real Polymarket history"
    config = _strategy_config_from_args(args)
    risk_limits = _risk_limits_from_args(args)

    report = run_walk_forward_backtest(
        trades,
        config=config,
        risk_limits=risk_limits,
        n_folds=args.n_folds,
        starting_bankroll=args.starting_bankroll,
    )

    print(f"data source: {source}")
    print(f"price range traded: [{args.min_price}, {args.max_price}], min_delta={args.min_delta}, folds={args.n_folds}")
    print(
        f"risk limits: daily_loss<={args.max_daily_loss_fraction:.0%} of starting bankroll, "
        f"cooldown after {args.max_consecutive_losses} consecutive losses "
        f"({args.cooldown_trades} candidate trades), hard stake cap {args.hard_max_stake_fraction:.1%}"
    )
    print()
    for fold in report.folds:
        print(
            f"  fold {fold.fold_index}: train={fold.train_size} test={fold.test_size} "
            f"candidates={fold.n_candidates} taken={fold.n_taken} "
            f"wins={fold.n_wins} losses={fold.n_losses} "
            f"skipped_by_risk={fold.n_skipped_by_risk_manager}"
        )
    print()
    print(report.summary())
    if report.n_taken == 0:
        print("\nNo trades were taken across any fold -- no priced edge cleared min_delta out-of-sample.")


def _load_calibration_buckets(args):
    trades = load_trades_csv(args.calibration_csv)
    return calibration_curve(
        [t.price for t in trades],
        [t.outcome for t in trades],
        bucket_width=args.bucket_width,
        min_trades_per_bucket=args.min_trades_per_bucket,
    )


def _run_trading_loop(args, live: bool) -> None:
    from .live_loop import fetch_open_markets, run_once
    from .risk_manager import RiskManager

    buckets = _load_calibration_buckets(args)
    if not buckets:
        print("No calibration buckets survived --min-trades-per-bucket on this CSV; aborting.", file=sys.stderr)
        sys.exit(1)
    print(f"Loaded {len(buckets)} calibration bucket(s) from {args.calibration_csv}:")
    for b in buckets:
        print(f"  [{b.low:.2f}, {b.high:.2f}) n={b.n_trades} actual_win_rate={b.actual_win_rate:.3f} delta={b.delta:+.3f}")

    config = _strategy_config_from_args(args)
    risk_manager = RiskManager(_risk_limits_from_args(args), starting_bankroll=args.starting_bankroll)

    try:
        broker = make_broker(live=live, ledger_path=args.ledger)
    except LiveTradingNotConfirmed as e:
        print(f"Refusing to start live trading: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Broker: {type(broker).__name__} (ledger={args.ledger})" if not live else "Broker: LiveBroker -- REAL ORDERS WILL BE PLACED")

    cycle = 0
    while True:
        cycle += 1
        day_key = int(time.time() // 86400)
        try:
            markets = fetch_open_markets(category=args.category, limit=args.limit)
        except Exception as e:  # network errors etc. -- log and keep the loop alive
            print(f"[cycle {cycle}] fetch_open_markets failed: {e}", file=sys.stderr)
            markets = []

        decisions = run_once(
            markets, buckets, config, risk_manager, broker, bankroll=args.starting_bankroll, day_key=day_key
        )
        placed = sum(1 for d in decisions if d.placed)
        print(f"[cycle {cycle}] scanned={len(markets)} signals={len(decisions)} placed={placed}")

        if args.once:
            return
        time.sleep(args.interval)


def cmd_paper(args) -> None:
    _run_trading_loop(args, live=False)


def cmd_live(args) -> None:
    _run_trading_loop(args, live=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_backtest = sub.add_parser("backtest", help="single train/test split backtest")
    p_backtest.add_argument("--csv", help="path to a CSV of historical trades (price,outcome[,market_id,timestamp])")
    p_backtest.add_argument("--train-frac", type=float, default=0.5)
    p_backtest.add_argument("--starting-bankroll", type=float, default=100.0)
    p_backtest.add_argument("--n-synthetic", type=int, default=20000)
    _add_strategy_args(p_backtest)
    p_backtest.set_defaults(func=cmd_backtest)

    p_wf = sub.add_parser("walk-forward", help="multi-fold walk-forward backtest with risk manager")
    p_wf.add_argument("--csv", help="path to a CSV of historical trades (price,outcome[,market_id,timestamp])")
    p_wf.add_argument("--n-folds", type=int, default=5)
    p_wf.add_argument("--starting-bankroll", type=float, default=100.0)
    p_wf.add_argument("--n-synthetic", type=int, default=20000)
    _add_strategy_args(p_wf)
    _add_risk_args(p_wf)
    p_wf.set_defaults(func=cmd_walk_forward)

    for name, help_text, func in [
        ("paper", "poll live markets and paper-trade (default, no real orders)", cmd_paper),
        ("live", "poll live markets and place REAL orders (requires explicit opt-in)", cmd_live),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--calibration-csv", required=True, help="resolved-trades CSV to fit the calibration curve from")
        p.add_argument("--bucket-width", type=float, default=0.05)
        p.add_argument("--min-trades-per-bucket", type=int, default=30)
        p.add_argument("--category", default=None, help='e.g. "tennis"')
        p.add_argument("--limit", type=int, default=100, help="max open markets to scan per cycle")
        p.add_argument("--starting-bankroll", type=float, default=100.0)
        p.add_argument("--interval", type=int, default=60, help="seconds between polling cycles")
        p.add_argument("--once", action="store_true", help="run a single cycle and exit")
        p.add_argument("--ledger", default="paper_trades.jsonl", help="paper trade ledger path (paper mode only)")
        _add_strategy_args(p)
        _add_risk_args(p)
        p.set_defaults(func=func)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

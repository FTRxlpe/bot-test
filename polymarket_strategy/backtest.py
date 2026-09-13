"""Out-of-sample backtest: fit the calibration curve on a train split, then
trade the test split using only what the train split could have told you.

Fitting the calibration curve and evaluating it on the SAME trades is a
classic backtest bug -- it lets the "edge" be sampling noise the model just
memorized. Every number in the report below comes from the held-out test
split only.
"""
from __future__ import annotations

from dataclasses import dataclass

from .data import Trade
from .ev import expected_value
from .kelly import kelly_fraction
from .pricing import PriceBucket, calibration_curve, mispricing
from .risk_manager import RiskLimits, RiskManager
from .strategy import StrategyConfig


@dataclass
class TradeResult:
    price: float
    outcome: int
    calibrated_win_probability: float
    delta: float
    ev: float
    stake: float
    pnl: float


@dataclass
class BacktestReport:
    n_candidates: int          # test-set trades in the target price range
    n_taken: int                # trades the strategy actually entered
    n_wins: int
    n_losses: int
    win_rate: float             # n_wins / n_taken
    total_pnl: float
    starting_bankroll: float
    ending_bankroll: float
    roi: float                  # total_pnl / starting_bankroll
    max_drawdown: float         # as a fraction of peak bankroll
    avg_return_per_trade: float  # mean pnl / stake across taken trades -- the
                                  # realistic per-bet edge, independent of how
                                  # many trades happened to compound together
    trades: list[TradeResult]

    def summary(self) -> str:
        return (
            f"candidates={self.n_candidates} taken={self.n_taken} "
            f"wins={self.n_wins} losses={self.n_losses} "
            f"win_rate={self.win_rate:.2%} "
            f"avg_return_per_trade={self.avg_return_per_trade:.2%} "
            f"total_pnl=${self.total_pnl:.2f} roi={self.roi:.2%} "
            f"max_drawdown={self.max_drawdown:.2%} "
            f"ending_bankroll=${self.ending_bankroll:.2f}"
        )


def _bucket_for_price(buckets: list[PriceBucket], price: float) -> PriceBucket | None:
    for b in buckets:
        if b.low <= price < b.high:
            return b
    return None


def run_backtest(
    trades: list[Trade],
    config: StrategyConfig | None = None,
    train_frac: float = 0.5,
    starting_bankroll: float = 100.0,
    bucket_width: float = 0.05,
    min_trades_per_bucket: int = 30,
) -> BacktestReport:
    config = config or StrategyConfig()

    ordered = sorted(trades, key=lambda t: (t.timestamp if t.timestamp else t.index, t.index))
    cut = int(len(ordered) * train_frac)
    train, test = ordered[:cut], ordered[cut:]
    if not train or not test:
        raise ValueError("need trades in both the train and test splits")

    buckets = calibration_curve(
        [t.price for t in train],
        [t.outcome for t in train],
        bucket_width=bucket_width,
        min_trades_per_bucket=min_trades_per_bucket,
    )

    bankroll = starting_bankroll
    peak = starting_bankroll
    max_drawdown = 0.0
    results: list[TradeResult] = []
    n_candidates = 0

    for t in test:
        if not (config.min_price <= t.price <= config.max_price):
            continue
        n_candidates += 1

        bucket = _bucket_for_price(buckets, t.price)
        if bucket is None:
            continue  # not enough train data near this price to trust a signal

        calibrated_p = bucket.actual_win_rate
        delta = mispricing(calibrated_p, t.price)
        ev = expected_value(calibrated_p, t.price) - config.fee_rate
        if not (delta >= config.min_delta and ev > 0):
            continue

        size_frac = kelly_fraction(calibrated_p, t.price, fraction=config.kelly_fraction_cap)
        if size_frac <= 0:
            continue

        max_stake = starting_bankroll * config.max_stake_fraction_of_starting_bankroll
        stake = min(bankroll * size_frac, max_stake)
        stake = max(0.0, min(stake, bankroll))  # never stake more than you have
        if stake <= 0:
            continue
        shares = stake / t.price
        if t.outcome == 1:
            pnl = shares * (1.0 - t.price)  # profit
        else:
            pnl = -stake

        bankroll += pnl
        peak = max(peak, bankroll)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - bankroll) / peak)

        results.append(
            TradeResult(
                price=t.price,
                outcome=t.outcome,
                calibrated_win_probability=calibrated_p,
                delta=delta,
                ev=ev,
                stake=stake,
                pnl=pnl,
            )
        )

    n_wins = sum(1 for r in results if r.outcome == 1)
    n_losses = len(results) - n_wins
    total_pnl = bankroll - starting_bankroll
    avg_return_per_trade = (
        sum(r.pnl / r.stake for r in results) / len(results) if results else 0.0
    )

    return BacktestReport(
        n_candidates=n_candidates,
        n_taken=len(results),
        n_wins=n_wins,
        n_losses=n_losses,
        win_rate=(n_wins / len(results)) if results else 0.0,
        total_pnl=total_pnl,
        starting_bankroll=starting_bankroll,
        ending_bankroll=bankroll,
        roi=(total_pnl / starting_bankroll) if starting_bankroll else 0.0,
        max_drawdown=max_drawdown,
        avg_return_per_trade=avg_return_per_trade,
        trades=results,
    )


@dataclass
class FoldReport:
    fold_index: int
    train_size: int
    test_size: int
    n_candidates: int
    n_taken: int
    n_wins: int
    n_losses: int
    n_skipped_by_risk_manager: int


@dataclass
class WalkForwardReport:
    """Multi-fold walk-forward result: fold 1 trains on chunk 0 and tests on
    chunk 1, fold 2 trains on chunks 0-1 and tests on chunk 2, etc. (expanding
    window). Every fold's calibration curve is fit ONLY on trades chronologically
    before that fold's test chunk -- no fold ever sees its own test data, or any
    future data, while fitting. Bankroll, drawdown, and risk-manager state
    (loss streaks, cooldowns, daily caps) all carry forward continuously across
    fold boundaries, exactly as they would in live sequential trading.
    """

    folds: list[FoldReport]
    n_candidates: int
    n_taken: int
    n_wins: int
    n_losses: int
    win_rate: float
    total_pnl: float
    starting_bankroll: float
    ending_bankroll: float
    roi: float
    max_drawdown: float
    avg_return_per_trade: float
    n_skipped_by_risk_manager: int
    trades: list[TradeResult]

    def summary(self) -> str:
        return (
            f"[walk-forward, {len(self.folds)} folds] "
            f"candidates={self.n_candidates} taken={self.n_taken} "
            f"wins={self.n_wins} losses={self.n_losses} "
            f"win_rate={self.win_rate:.2%} "
            f"avg_return_per_trade={self.avg_return_per_trade:.2%} "
            f"total_pnl=${self.total_pnl:.2f} roi={self.roi:.2%} "
            f"max_drawdown={self.max_drawdown:.2%} "
            f"skipped_by_risk_manager={self.n_skipped_by_risk_manager} "
            f"ending_bankroll=${self.ending_bankroll:.2f}"
        )


def _day_key_for(t: Trade, trades_per_day: int) -> int:
    if t.timestamp:
        return int(t.timestamp // 86400)
    return t.index // max(1, trades_per_day)


def _simulate_sequential(
    test_trades: list[Trade],
    buckets: list[PriceBucket],
    config: StrategyConfig,
    risk_manager: RiskManager,
    bankroll: float,
    peak: float,
    max_drawdown: float,
    trades_per_day: int,
) -> tuple[list[TradeResult], float, float, float, int, int]:
    """Trades one chronologically-ordered test period against a FIXED,
    already-fit calibration curve, applying the risk manager to every
    candidate in order. Shared by run_walk_forward_backtest (one call per
    fold) and run_last_n_days_backtest (one call for the whole window) so
    both use identical trade-execution logic.

    Returns (results, bankroll, peak, max_drawdown, n_candidates, n_skipped_by_risk).
    """
    results: list[TradeResult] = []
    n_candidates = 0
    n_skipped = 0

    for t in test_trades:
        if not (config.min_price <= t.price <= config.max_price):
            continue
        n_candidates += 1

        day_key = _day_key_for(t, trades_per_day)
        decision = risk_manager.check(day_key)
        if not decision.allowed:
            n_skipped += 1
            risk_manager.record_skip_during_cooldown()
            continue

        bucket = _bucket_for_price(buckets, t.price)
        if bucket is None:
            continue

        calibrated_p = bucket.actual_win_rate
        delta = mispricing(calibrated_p, t.price)
        ev = expected_value(calibrated_p, t.price) - config.fee_rate
        if not (delta >= config.min_delta and ev > 0):
            continue

        size_frac = kelly_fraction(calibrated_p, t.price, fraction=config.kelly_fraction_cap)
        if size_frac <= 0:
            continue

        desired_stake = bankroll * size_frac
        stake = risk_manager.cap_stake(desired_stake)
        stake = max(0.0, min(stake, bankroll))
        if stake <= 0:
            continue

        shares = stake / t.price
        pnl = shares * (1.0 - t.price) if t.outcome == 1 else -stake

        bankroll += pnl
        peak = max(peak, bankroll)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - bankroll) / peak)

        risk_manager.record_result(day_key, pnl)

        results.append(
            TradeResult(
                price=t.price,
                outcome=t.outcome,
                calibrated_win_probability=calibrated_p,
                delta=delta,
                ev=ev,
                stake=stake,
                pnl=pnl,
            )
        )

    return results, bankroll, peak, max_drawdown, n_candidates, n_skipped


def run_walk_forward_backtest(
    trades: list[Trade],
    config: StrategyConfig | None = None,
    risk_limits: RiskLimits | None = None,
    n_folds: int = 5,
    starting_bankroll: float = 100.0,
    bucket_width: float = 0.05,
    min_trades_per_bucket: int = 30,
    trades_per_day: int = 50,
) -> WalkForwardReport:
    """Walk-forward backtest with an expanding training window and a live
    risk manager applied sequentially across the whole test period.

    Unlike `run_backtest` (a single train/test split), this fits a fresh
    calibration curve before EACH fold using only the trades chronologically
    preceding it, so the reported edge cannot come from a calibration curve
    that "saw the future" relative to any test trade -- including trades in
    later folds, which still only ever get a curve fit on data strictly
    before them.
    """
    config = config or StrategyConfig()
    risk_limits = risk_limits or RiskLimits()
    if n_folds < 1:
        raise ValueError("n_folds must be >= 1")

    ordered = sorted(trades, key=lambda t: (t.timestamp if t.timestamp else t.index, t.index))
    n = len(ordered)
    n_chunks = n_folds + 1  # 1 seed chunk (train-only) + n_folds test chunks
    if n < n_chunks:
        raise ValueError("not enough trades for the requested number of folds")

    chunk_size = n // n_chunks
    chunks = [ordered[i * chunk_size : (i + 1) * chunk_size] for i in range(n_chunks - 1)]
    chunks.append(ordered[(n_chunks - 1) * chunk_size :])  # last chunk absorbs the remainder

    risk_manager = RiskManager(risk_limits, starting_bankroll)
    bankroll = starting_bankroll
    peak = starting_bankroll
    max_drawdown = 0.0
    all_results: list[TradeResult] = []
    fold_reports: list[FoldReport] = []
    total_candidates = 0
    total_skipped_by_risk = 0

    train_chunks: list[Trade] = list(chunks[0])
    for fold_index, test_chunk in enumerate(chunks[1:], start=1):
        buckets = calibration_curve(
            [t.price for t in train_chunks],
            [t.outcome for t in train_chunks],
            bucket_width=bucket_width,
            min_trades_per_bucket=min_trades_per_bucket,
        )

        fold_results, bankroll, peak, max_drawdown, fold_candidates, fold_skipped = _simulate_sequential(
            test_chunk, buckets, config, risk_manager, bankroll, peak, max_drawdown, trades_per_day
        )
        total_candidates += fold_candidates
        total_skipped_by_risk += fold_skipped
        all_results.extend(fold_results)
        fold_wins = sum(1 for r in fold_results if r.outcome == 1)

        fold_reports.append(
            FoldReport(
                fold_index=fold_index,
                train_size=len(train_chunks),
                test_size=len(test_chunk),
                n_candidates=fold_candidates,
                n_taken=len(fold_results),
                n_wins=fold_wins,
                n_losses=len(fold_results) - fold_wins,
                n_skipped_by_risk_manager=fold_skipped,
            )
        )
        train_chunks = train_chunks + list(test_chunk)  # expand the window for the next fold

    n_wins = sum(1 for r in all_results if r.outcome == 1)
    n_losses = len(all_results) - n_wins
    total_pnl = bankroll - starting_bankroll
    avg_return_per_trade = (
        sum(r.pnl / r.stake for r in all_results) / len(all_results) if all_results else 0.0
    )

    return WalkForwardReport(
        folds=fold_reports,
        n_candidates=total_candidates,
        n_taken=len(all_results),
        n_wins=n_wins,
        n_losses=n_losses,
        win_rate=(n_wins / len(all_results)) if all_results else 0.0,
        total_pnl=total_pnl,
        starting_bankroll=starting_bankroll,
        ending_bankroll=bankroll,
        roi=(total_pnl / starting_bankroll) if starting_bankroll else 0.0,
        max_drawdown=max_drawdown,
        avg_return_per_trade=avg_return_per_trade,
        n_skipped_by_risk_manager=total_skipped_by_risk,
        trades=all_results,
    )


@dataclass
class RecentPeriodReport:
    """Result of simulating trading over only the most recent `n_days` of a
    real trade history, calibrated exclusively on data strictly before that
    window -- answers "if I'd started trading this strategy n_days ago with
    only the data available at that point, what would have happened?"
    """

    n_days: int
    period_start: float  # unix seconds
    period_end: float
    train_size: int
    test_size: int
    n_candidates: int
    n_taken: int
    n_wins: int
    n_losses: int
    win_rate: float
    total_pnl: float
    starting_bankroll: float
    ending_bankroll: float
    roi: float
    max_drawdown: float
    avg_return_per_trade: float
    n_skipped_by_risk_manager: int
    trades: list[TradeResult]

    def summary(self) -> str:
        return (
            f"[last {self.n_days} days] "
            f"candidates={self.n_candidates} taken={self.n_taken} "
            f"wins={self.n_wins} losses={self.n_losses} "
            f"win_rate={self.win_rate:.2%} "
            f"avg_return_per_trade={self.avg_return_per_trade:.2%} "
            f"total_pnl=${self.total_pnl:.2f} roi={self.roi:.2%} "
            f"max_drawdown={self.max_drawdown:.2%} "
            f"skipped_by_risk_manager={self.n_skipped_by_risk_manager} "
            f"starting_bankroll=${self.starting_bankroll:.2f} "
            f"ending_bankroll=${self.ending_bankroll:.2f}"
        )


def run_last_n_days_backtest(
    trades: list[Trade],
    n_days: int = 30,
    config: StrategyConfig | None = None,
    risk_limits: RiskLimits | None = None,
    starting_bankroll: float = 200.0,
    bucket_width: float = 0.05,
    min_trades_per_bucket: int = 30,
    trades_per_day: int = 50,
    reference_time: float | None = None,
) -> RecentPeriodReport:
    """Simulates trading only the most recent `n_days` of real resolved-trade
    history, with the calibration curve fit EXCLUSIVELY on everything
    strictly before the cutoff -- the test window never leaks into its own
    calibration, same no-lookahead guarantee as the walk-forward engine, just
    windowed by calendar time instead of fold count.

    Requires every trade to carry a real, nonzero timestamp (as written by
    scripts/fetch_polymarket_data.py) -- a calendar-time question like "the
    last 30 days" is meaningless on index-only/synthetic ordering, so this
    raises rather than silently guessing at day boundaries from row order.
    """
    config = config or StrategyConfig()
    risk_limits = risk_limits or RiskLimits()
    if n_days <= 0:
        raise ValueError("n_days must be positive")
    if not trades:
        raise ValueError("no trades provided")
    if any(t.timestamp <= 0 for t in trades):
        raise ValueError(
            "run_last_n_days_backtest requires every trade to carry a real timestamp "
            "(e.g. from fetch_polymarket_data.py's CSV output) -- synthetic or "
            "index-only trades have no calendar time to window by"
        )

    ordered = sorted(trades, key=lambda t: t.timestamp)
    end_time = reference_time if reference_time is not None else ordered[-1].timestamp
    cutoff = end_time - n_days * 86400

    train = [t for t in ordered if t.timestamp < cutoff]
    test = [t for t in ordered if cutoff <= t.timestamp <= end_time]
    if not train:
        raise ValueError(
            f"no trade history before the {n_days}-day cutoff to fit a calibration curve on -- "
            "need data older than the test window"
        )
    if not test:
        raise ValueError(f"no trades found in the last {n_days} days of this dataset")

    buckets = calibration_curve(
        [t.price for t in train],
        [t.outcome for t in train],
        bucket_width=bucket_width,
        min_trades_per_bucket=min_trades_per_bucket,
    )

    risk_manager = RiskManager(risk_limits, starting_bankroll)
    results, bankroll, peak, max_drawdown, n_candidates, n_skipped = _simulate_sequential(
        test, buckets, config, risk_manager, starting_bankroll, starting_bankroll, 0.0, trades_per_day
    )

    n_wins = sum(1 for r in results if r.outcome == 1)
    n_losses = len(results) - n_wins
    total_pnl = bankroll - starting_bankroll
    avg_return_per_trade = sum(r.pnl / r.stake for r in results) / len(results) if results else 0.0

    return RecentPeriodReport(
        n_days=n_days,
        period_start=cutoff,
        period_end=end_time,
        train_size=len(train),
        test_size=len(test),
        n_candidates=n_candidates,
        n_taken=len(results),
        n_wins=n_wins,
        n_losses=n_losses,
        win_rate=(n_wins / len(results)) if results else 0.0,
        total_pnl=total_pnl,
        starting_bankroll=starting_bankroll,
        ending_bankroll=bankroll,
        roi=(total_pnl / starting_bankroll) if starting_bankroll else 0.0,
        max_drawdown=max_drawdown,
        avg_return_per_trade=avg_return_per_trade,
        n_skipped_by_risk_manager=n_skipped,
        trades=results,
    )

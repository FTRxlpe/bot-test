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

    ordered = sorted(trades, key=lambda t: t.index)
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

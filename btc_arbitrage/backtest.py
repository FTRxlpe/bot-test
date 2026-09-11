"""Out-of-sample backtest: detect gaps and simulate realistic execution
across the full snapshot history, split the resulting opportunities
chronologically, fit the gap-size calibration curve on the train half only,
then trade the test half using only what the train half could have told you.

This mirrors polymarket_strategy/backtest.py's out-of-sample discipline for
the same reason: fitting and evaluating a calibration curve on the same data
lets a strategy "discover" an edge that is really just memorized noise.
Every number in the report is computed on the held-out test split, using the
REAL realized net edge (post-latency, post-cost) for P&L -- never the
calibrated estimate used to decide whether to take the trade.
"""
from __future__ import annotations

from dataclasses import dataclass

from .calibration import GapBucket, calibration_curve
from .costs import RoundTripCosts
from .data import Snapshot
from .execution import Opportunity, realize_opportunity
from .pricing import detect_gap
from .sizing import kelly_fraction
from .strategy import StrategyConfig


@dataclass
class TradeResult:
    timestamp_ms: int
    buy_market: str
    sell_market: str
    raw_gap_fraction: float
    realized_net_edge: float
    stake: float
    pnl: float


@dataclass
class BacktestReport:
    n_snapshots: int
    n_candidates: int   # gaps detected+realized in the test split, before calibration filtering
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
    trades: list[TradeResult]

    def summary(self) -> str:
        return (
            f"snapshots={self.n_snapshots} candidates={self.n_candidates} taken={self.n_taken} "
            f"wins={self.n_wins} losses={self.n_losses} win_rate={self.win_rate:.2%} "
            f"avg_return_per_trade={self.avg_return_per_trade:.2%} "
            f"total_pnl=${self.total_pnl:.2f} roi={self.roi:.2%} "
            f"max_drawdown={self.max_drawdown:.2%} ending_bankroll=${self.ending_bankroll:.2f}"
        )


def _bucket_for_gap(buckets: list[GapBucket], raw_gap_fraction: float) -> GapBucket | None:
    for b in buckets:
        if b.low <= raw_gap_fraction < b.high:
            return b
    return None


def _steps_per_latency(snapshots: list[Snapshot], latency_ms: int) -> int:
    if len(snapshots) < 2:
        return 1
    tick_ms = snapshots[1].timestamp_ms - snapshots[0].timestamp_ms
    if tick_ms <= 0:
        return 1
    return max(1, round(latency_ms / tick_ms))


def _build_opportunities(
    snapshots: list[Snapshot], costs: RoundTripCosts, latency_ms: int
) -> list[Opportunity]:
    step = _steps_per_latency(snapshots, latency_ms)
    opportunities = []
    for i, snap in enumerate(snapshots):
        gap = detect_gap(snap)
        if gap is None:
            continue
        exec_index = i + step
        if exec_index >= len(snapshots):
            continue
        opp = realize_opportunity(gap, snapshots[exec_index], costs, latency_ms)
        if opp is not None:
            opportunities.append(opp)
    return opportunities


def run_backtest(
    snapshots: list[Snapshot],
    config: StrategyConfig | None = None,
    train_frac: float = 0.5,
    starting_bankroll: float = 10_000.0,
) -> BacktestReport:
    config = config or StrategyConfig()
    costs = RoundTripCosts(
        taker_fee_bps=config.taker_fee_bps,
        slippage_bps_per_leg=config.slippage_bps_per_leg,
    )

    ordered = sorted(snapshots, key=lambda s: s.index)
    cut = int(len(ordered) * train_frac)
    train, test = ordered[:cut], ordered[cut:]
    if not train or not test:
        raise ValueError("need snapshots in both the train and test splits")

    train_opportunities = _build_opportunities(train, costs, config.latency_ms)
    buckets = calibration_curve(
        train_opportunities,
        bucket_width=config.bucket_width,
        min_per_bucket=config.min_trades_per_bucket,
    )

    test_opportunities = _build_opportunities(test, costs, config.latency_ms)

    bankroll = starting_bankroll
    peak = starting_bankroll
    max_drawdown = 0.0
    results: list[TradeResult] = []

    for opp in test_opportunities:
        bucket = _bucket_for_gap(buckets, opp.detected.raw_gap_fraction)
        if bucket is None:
            continue  # not enough train data at this gap size to trust a signal

        calibrated_edge = bucket.win_rate * bucket.avg_win + (1 - bucket.win_rate) * bucket.avg_loss
        if calibrated_edge <= config.min_calibrated_edge:
            continue

        size_frac = kelly_fraction(bucket, fraction=config.kelly_fraction_cap)
        if size_frac <= 0:
            continue

        max_stake = starting_bankroll * config.max_stake_fraction_of_starting_bankroll
        stake = min(bankroll * size_frac, max_stake)
        stake = max(0.0, min(stake, bankroll))  # never stake more than you have
        if stake <= 0:
            continue

        pnl = stake * opp.net_edge  # the REAL realized edge, not the calibrated estimate
        bankroll += pnl
        peak = max(peak, bankroll)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - bankroll) / peak)

        results.append(
            TradeResult(
                timestamp_ms=opp.detected.timestamp_ms,
                buy_market=opp.detected.buy_market,
                sell_market=opp.detected.sell_market,
                raw_gap_fraction=opp.detected.raw_gap_fraction,
                realized_net_edge=opp.net_edge,
                stake=stake,
                pnl=pnl,
            )
        )

    n_wins = sum(1 for r in results if r.pnl > 0)
    n_losses = len(results) - n_wins
    total_pnl = bankroll - starting_bankroll
    avg_return_per_trade = (
        sum(r.pnl / r.stake for r in results) / len(results) if results else 0.0
    )

    return BacktestReport(
        n_snapshots=len(ordered),
        n_candidates=len(test_opportunities),
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

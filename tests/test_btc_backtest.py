import pytest

from btc_arbitrage.backtest import run_backtest
from btc_arbitrage.data import Snapshot, generate_synthetic_snapshots
from btc_arbitrage.strategy import StrategyConfig


def test_backtest_on_lagging_markets_finds_a_real_but_modest_edge():
    # Stale-quote lag creates genuine, transient cross-market gaps.
    snapshots = generate_synthetic_snapshots(n_steps=200000, seed=1)
    report = run_backtest(snapshots, config=StrategyConfig(), train_frac=0.5, starting_bankroll=10_000.0)

    assert report.n_taken > 0, "strategy should find and take some trades when real desyncs exist"
    # A real edge in a competitive, low-latency market is real because it's
    # small. This should look nothing like "the bot wins every time":
    assert 0.5 < report.win_rate < 0.95
    assert 0.0 < report.avg_return_per_trade < 0.03  # a few percent per trade, not "no risk"


def test_backtest_on_efficient_market_finds_no_edge():
    # No stale-quote lag at all -- markets only differ by zero-mean
    # microstructure noise, i.e. there is no real mispricing to find.
    snapshots = generate_synthetic_snapshots(n_steps=200000, seed=7, lag_probability_per_step=0.0)
    report = run_backtest(snapshots, config=StrategyConfig(), train_frac=0.5, starting_bankroll=10_000.0)

    # An honest engine should take ~nothing: apparent gaps here are just
    # noise, and noise doesn't clear real trading costs after the
    # train/test split.
    take_rate = report.n_taken / report.n_candidates if report.n_candidates else 0
    assert take_rate < 0.05


def test_higher_latency_erodes_the_edge():
    # The pitch claims the bot "spots price errors before humans notice" --
    # if that were true regardless of speed, latency shouldn't matter. In
    # reality, the whole edge comes from being fast: slower execution lets
    # the gap close (or reverse) before both legs fill.
    snapshots = generate_synthetic_snapshots(n_steps=200000, seed=1)

    fast = run_backtest(
        snapshots, config=StrategyConfig(latency_ms=250), train_frac=0.5, starting_bankroll=10_000.0
    )
    slow = run_backtest(
        snapshots, config=StrategyConfig(latency_ms=3000), train_frac=0.5, starting_bankroll=10_000.0
    )

    assert fast.total_pnl > slow.total_pnl
    assert fast.n_taken > slow.n_taken


def test_realistic_costs_can_erase_edge_that_exists_at_zero_cost():
    # Same market, same latency: raising round-trip costs from 0 to a
    # realistic level for cross-exchange arbitrage should hurt total
    # profit, not help it -- even though fewer (larger, cost-surviving)
    # trades can look better on a per-trade average.
    snapshots = generate_synthetic_snapshots(n_steps=200000, seed=1)

    cheap = run_backtest(
        snapshots,
        config=StrategyConfig(taker_fee_bps=0.0, slippage_bps_per_leg=0.0),
        train_frac=0.5,
        starting_bankroll=10_000.0,
    )
    realistic = run_backtest(
        snapshots,
        config=StrategyConfig(taker_fee_bps=10.0, slippage_bps_per_leg=5.0),
        train_frac=0.5,
        starting_bankroll=10_000.0,
    )

    assert realistic.total_pnl < cheap.total_pnl
    assert realistic.n_taken < cheap.n_taken


def test_backtest_requires_both_splits_nonempty():
    snapshots = [Snapshot(timestamp_ms=0, prices={"a": 100.0, "b": 100.5}, index=0)]
    with pytest.raises(ValueError):
        run_backtest(snapshots, train_frac=0.5)


def test_backtest_report_summary_is_a_string():
    snapshots = generate_synthetic_snapshots(n_steps=5000, seed=2)
    report = run_backtest(snapshots)
    assert isinstance(report.summary(), str)
    assert "win_rate" in report.summary()

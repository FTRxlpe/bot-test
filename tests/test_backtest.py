import random

import pytest

from polymarket_strategy.backtest import run_backtest, run_walk_forward_backtest
from polymarket_strategy.data import Trade, generate_synthetic_trades
from polymarket_strategy.risk_manager import RiskLimits
from polymarket_strategy.strategy import StrategyConfig


def test_backtest_on_synthetic_favorite_longshot_bias_finds_a_real_but_modest_edge():
    trades = generate_synthetic_trades(n=30000, favorite_longshot_bias=0.05, seed=1)
    config = StrategyConfig(min_delta=0.02, min_price=0.80, max_price=0.99, kelly_fraction_cap=0.25)
    report = run_backtest(trades, config=config, train_frac=0.5, starting_bankroll=100.0)

    assert report.n_taken > 0, "strategy should find and take some trades in the biased data"
    # The synthetic bias tops out around +0.05 at price=0.99 -> true win rate near
    # price + 0.05, not anywhere near the pitch's claimed 99.3%.
    assert 0.75 < report.win_rate < 0.97
    assert report.win_rate < 0.98  # explicitly: this does NOT reproduce the marketing claim


def test_backtest_on_efficient_market_finds_no_edge():
    # No favorite-longshot bias: prices ARE the true probabilities.
    # An honest engine should take ~nothing, because delta should be ~0 everywhere.
    rng = random.Random(7)
    trades = []
    for i in range(20000):
        price = rng.uniform(0.80, 0.99)
        outcome = 1 if rng.random() < price else 0
        trades.append(Trade(price=price, outcome=outcome, index=i))

    config = StrategyConfig(min_delta=0.02, min_price=0.80, max_price=0.99)
    report = run_backtest(trades, config=config, train_frac=0.5, starting_bankroll=100.0)

    # Some buckets will clear the noise threshold by chance, but it should be
    # a small minority of candidates, not a systematic strategy.
    take_rate = report.n_taken / report.n_candidates if report.n_candidates else 0
    assert take_rate < 0.35


def test_backtest_requires_both_splits_nonempty():
    trades = [Trade(price=0.9, outcome=1, index=0)]
    with pytest.raises(ValueError):
        run_backtest(trades, train_frac=0.5)


def test_backtest_report_summary_is_a_string():
    trades = generate_synthetic_trades(n=5000, seed=2)
    report = run_backtest(trades)
    assert isinstance(report.summary(), str)
    assert "win_rate" in report.summary()


def _exactly_calibrated_trades(n_repeats: int = 100) -> list[Trade]:
    """Deterministic (no RNG) trades where the empirical win rate in every
    price bucket equals that bucket's implied probability EXACTLY -- an
    efficient market by construction, with zero sampling noise. Used to prove
    the walk-forward engine doesn't invent an edge when there provably isn't
    one, rather than relying on "unlikely by chance" statistical language.
    """
    # (price == bucket midpoint, trades per bucket-cycle, wins per bucket-cycle)
    # e.g. 0.825 = 33/40 exactly, so 33 wins out of every 40 trades at that
    # price reproduces the bucket's implied probability with no rounding error.
    bucket_defs = [(0.825, 40, 33), (0.875, 40, 35), (0.925, 40, 37), (0.975, 40, 39)]
    trades = []
    idx = 0
    for _ in range(n_repeats):
        for price, denom, wins in bucket_defs:
            for i in range(denom):
                # Evenly distributes the `wins` winning trades across the
                # block instead of clustering them, so even a chunk boundary
                # that cuts a block in half sees close to the true ratio.
                outcome = 1 if (i * wins) % denom < wins else 0
                trades.append(Trade(price=price, outcome=outcome, index=idx))
                idx += 1
    return trades


def test_walk_forward_stays_at_zero_trades_with_exactly_calibrated_market():
    trades = _exactly_calibrated_trades(n_repeats=100)
    config = StrategyConfig(min_delta=0.02, min_price=0.80, max_price=0.99)
    report = run_walk_forward_backtest(trades, config=config, n_folds=5, starting_bankroll=100.0)

    assert report.n_candidates > 0  # the data does reach the strategy's price range
    assert report.n_taken == 0, (
        "an exactly-calibrated market (delta == 0 in every bucket, every fold) "
        "must never clear min_delta -- any trade here is a false positive"
    )
    assert report.total_pnl == 0.0
    assert report.ending_bankroll == report.starting_bankroll


def test_walk_forward_detects_a_real_injected_bias_out_of_sample():
    trades = generate_synthetic_trades(n=40000, favorite_longshot_bias=0.06, seed=3)
    config = StrategyConfig(min_delta=0.02, min_price=0.80, max_price=0.99, kelly_fraction_cap=0.25)
    report = run_walk_forward_backtest(trades, config=config, n_folds=5, starting_bankroll=100.0)

    assert report.n_taken > 0, "a real, injected favorite-longshot bias must be detected out-of-sample"
    assert 0.75 < report.win_rate < 0.99  # a real edge, not the marketing pitch's 99.3%
    assert len(report.folds) == 5
    assert all(f.n_candidates >= 0 for f in report.folds)
    # every fold that took trades should show a plausible, non-degenerate win rate
    for f in report.folds:
        if f.n_taken > 0:
            assert 0.0 <= f.n_wins / f.n_taken <= 1.0


def test_walk_forward_risk_manager_halts_after_a_loss_streak():
    # A biased-but-noisy market that still loses individual bets, so a losing
    # streak is possible even though the strategy has a real long-run edge.
    trades = generate_synthetic_trades(n=40000, favorite_longshot_bias=0.06, seed=3)
    config = StrategyConfig(min_delta=0.02, min_price=0.80, max_price=0.99, kelly_fraction_cap=0.25)
    tight_limits = RiskLimits(max_consecutive_losses=1, cooldown_trades=1000000, max_daily_loss_fraction=1.0)

    report = run_walk_forward_backtest(
        trades, config=config, risk_limits=tight_limits, n_folds=5, starting_bankroll=100.0
    )

    # With a 1-loss trigger and a huge cooldown, the very first loss should
    # freeze trading for effectively the rest of the run.
    assert report.n_skipped_by_risk_manager > 0
    assert report.n_losses <= 1


def test_walk_forward_rejects_too_few_trades_for_requested_folds():
    trades = [Trade(price=0.9, outcome=1, index=i) for i in range(5)]
    with pytest.raises(ValueError):
        run_walk_forward_backtest(trades, n_folds=5)

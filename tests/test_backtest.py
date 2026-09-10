import random

import pytest

from polymarket_strategy.backtest import run_backtest
from polymarket_strategy.data import Trade, generate_synthetic_trades
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

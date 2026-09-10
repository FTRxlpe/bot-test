from polymarket_strategy.pricing import PriceBucket
from polymarket_strategy.strategy import StrategyConfig, generate_signals


def test_generate_signals_takes_only_priced_edges_in_range():
    buckets = [
        PriceBucket(low=0.80, high=0.85, n_trades=200, actual_win_rate=0.95, implied_probability=0.825),
        PriceBucket(low=0.30, high=0.35, n_trades=200, actual_win_rate=0.32, implied_probability=0.325),
        PriceBucket(low=0.90, high=0.95, n_trades=200, actual_win_rate=0.91, implied_probability=0.925),
    ]
    config = StrategyConfig(min_delta=0.02, min_price=0.80, max_price=0.99)
    signals = generate_signals(buckets, config)

    assert len(signals) == 2  # the 0.30-0.35 bucket is outside [0.80, 0.99]
    taken = [s for s in signals if s.take]
    assert len(taken) == 1
    assert taken[0].price == 0.825  # the genuinely mispriced bucket
    assert taken[0].kelly_size > 0


def test_generate_signals_skips_when_edge_below_threshold():
    buckets = [
        PriceBucket(low=0.85, high=0.90, n_trades=200, actual_win_rate=0.875, implied_probability=0.875),
    ]
    config = StrategyConfig(min_delta=0.02)
    signals = generate_signals(buckets, config)
    assert len(signals) == 1
    assert signals[0].take is False
    assert signals[0].kelly_size == 0.0

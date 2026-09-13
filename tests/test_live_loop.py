from polymarket_strategy.live_loop import Decision, MarketSignal, OpenMarket, evaluate_market, run_once
from polymarket_strategy.pricing import PriceBucket
from polymarket_strategy.risk_manager import RiskLimits, RiskManager
from polymarket_strategy.strategy import StrategyConfig


class FakeBroker:
    def __init__(self):
        self.orders = []

    def place_order(self, token_id, side, price, size):
        order = {"token_id": token_id, "side": side, "price": price, "size": size}
        self.orders.append(order)
        return order


BUCKETS = [
    PriceBucket(low=0.80, high=0.85, n_trades=200, actual_win_rate=0.95, implied_probability=0.825),
    PriceBucket(low=0.90, high=0.95, n_trades=200, actual_win_rate=0.91, implied_probability=0.925),
]
CONFIG = StrategyConfig(min_delta=0.02, min_price=0.80, max_price=0.99, kelly_fraction_cap=0.25)


def test_evaluate_market_takes_a_real_edge():
    market = OpenMarket(market_id="m1", token_id="tok-1", price=0.825)
    signal = evaluate_market(market, BUCKETS, CONFIG)
    assert signal is not None
    assert signal.take is True
    assert signal.kelly_size > 0


def test_evaluate_market_skips_price_outside_any_bucket():
    market = OpenMarket(market_id="m2", token_id="tok-2", price=0.60)
    assert evaluate_market(market, BUCKETS, CONFIG) is None


def test_evaluate_market_skips_price_outside_config_range():
    market = OpenMarket(market_id="m3", token_id="tok-3", price=0.10)
    assert evaluate_market(market, BUCKETS, CONFIG) is None


def test_evaluate_market_no_take_when_calibrated_rate_matches_price():
    fair_bucket = [PriceBucket(low=0.90, high=0.95, n_trades=200, actual_win_rate=0.925, implied_probability=0.925)]
    market = OpenMarket(market_id="m4", token_id="tok-4", price=0.925)
    signal = evaluate_market(market, fair_bucket, CONFIG)
    assert signal is not None
    assert signal.take is False
    assert signal.kelly_size == 0.0


def test_run_once_places_orders_for_taken_signals():
    markets = [
        OpenMarket(market_id="m1", token_id="tok-1", price=0.825),  # real edge
        OpenMarket(market_id="m2", token_id="tok-2", price=0.60),  # no bucket coverage
    ]
    broker = FakeBroker()
    risk_manager = RiskManager(RiskLimits(), starting_bankroll=100.0)

    decisions = run_once(
        markets, BUCKETS, CONFIG, risk_manager, broker, bankroll=100.0, day_key=1
    )

    assert len(decisions) == 1
    assert decisions[0].placed is True
    assert len(broker.orders) == 1
    assert broker.orders[0]["token_id"] == "tok-1"


def test_run_once_respects_risk_manager_cooldown():
    markets = [OpenMarket(market_id="m1", token_id="tok-1", price=0.825)]
    broker = FakeBroker()
    limits = RiskLimits(max_daily_loss_fraction=0.01, hard_max_stake_fraction=0.02)
    risk_manager = RiskManager(limits, starting_bankroll=100.0)
    risk_manager.record_result(day_key=1, pnl=-5.0)  # blows through the 1% daily cap

    decisions = run_once(markets, BUCKETS, CONFIG, risk_manager, broker, bankroll=100.0, day_key=1)

    assert len(decisions) == 1
    assert decisions[0].placed is False
    assert "daily loss cap" in decisions[0].reason
    assert broker.orders == []


def test_run_once_caps_stake_via_hard_limit():
    markets = [OpenMarket(market_id="m1", token_id="tok-1", price=0.825)]
    broker = FakeBroker()
    limits = RiskLimits(hard_max_stake_fraction=0.01)  # 1% of 100 = $1 max
    risk_manager = RiskManager(limits, starting_bankroll=100.0)

    run_once(markets, BUCKETS, CONFIG, risk_manager, broker, bankroll=100.0, day_key=1)

    assert len(broker.orders) == 1
    stake = broker.orders[0]["size"] * broker.orders[0]["price"]
    assert stake <= 1.0 + 1e-9

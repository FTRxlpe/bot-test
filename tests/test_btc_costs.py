from btc_arbitrage.costs import RoundTripCosts


def test_total_cost_fraction_combines_both_legs():
    costs = RoundTripCosts(taker_fee_bps=10.0, slippage_bps_per_leg=5.0)
    # (10 + 5) bps per leg * 2 legs = 30 bps = 0.003
    assert costs.total_cost_fraction() == 0.003


def test_zero_costs_is_zero():
    costs = RoundTripCosts(taker_fee_bps=0.0, slippage_bps_per_leg=0.0)
    assert costs.total_cost_fraction() == 0.0

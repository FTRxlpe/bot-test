from btc_arbitrage.costs import RoundTripCosts
from btc_arbitrage.data import Snapshot
from btc_arbitrage.execution import realize_opportunity
from btc_arbitrage.pricing import detect_gap


def test_realized_edge_uses_execution_time_prices_not_detection_time():
    detection_snap = Snapshot(timestamp_ms=0, prices={"a": 100.0, "b": 102.0}, index=0)
    gap = detect_gap(detection_snap)
    assert gap is not None

    # By execution time, market "a" (the cheap one) has caught up almost
    # fully to market "b" -- the gap has largely closed, as it would in
    # reality once the stale quote refreshes.
    execution_snap = Snapshot(timestamp_ms=250, prices={"a": 101.9, "b": 102.0}, index=1)
    costs = RoundTripCosts(taker_fee_bps=0.0, slippage_bps_per_leg=0.0)
    opp = realize_opportunity(gap, execution_snap, costs, latency_ms=250)

    assert opp is not None
    assert opp.executed_gap_fraction == (102.0 - 101.9) / 101.9
    # Realized edge should be much smaller than the raw gap seen at detection.
    assert opp.net_edge < gap.raw_gap_fraction


def test_costs_reduce_net_edge():
    detection_snap = Snapshot(timestamp_ms=0, prices={"a": 100.0, "b": 102.0}, index=0)
    gap = detect_gap(detection_snap)
    assert gap is not None
    execution_snap = Snapshot(timestamp_ms=250, prices={"a": 100.0, "b": 102.0}, index=1)

    free = realize_opportunity(gap, execution_snap, RoundTripCosts(0.0, 0.0), latency_ms=250)
    costly = realize_opportunity(gap, execution_snap, RoundTripCosts(50.0, 50.0), latency_ms=250)
    assert free is not None and costly is not None
    assert costly.net_edge < free.net_edge


def test_returns_none_if_a_leg_market_disappears_by_execution_time():
    detection_snap = Snapshot(timestamp_ms=0, prices={"a": 100.0, "b": 102.0}, index=0)
    gap = detect_gap(detection_snap)
    assert gap is not None
    execution_snap = Snapshot(timestamp_ms=250, prices={"b": 102.0}, index=1)
    opp = realize_opportunity(gap, execution_snap, RoundTripCosts(), latency_ms=250)
    assert opp is None

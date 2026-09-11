from btc_arbitrage.calibration import calibration_curve
from btc_arbitrage.costs import RoundTripCosts
from btc_arbitrage.data import Snapshot
from btc_arbitrage.execution import realize_opportunity
from btc_arbitrage.pricing import detect_gap


def _opportunity(raw_gap_fraction: float, realized_gap_fraction: float, costs: RoundTripCosts):
    buy_price = 100.0
    detection = Snapshot(
        timestamp_ms=0, prices={"a": buy_price, "b": buy_price * (1 + raw_gap_fraction)}, index=0
    )
    gap = detect_gap(detection)
    execution = Snapshot(
        timestamp_ms=250,
        prices={"a": buy_price, "b": buy_price * (1 + realized_gap_fraction)},
        index=1,
    )
    return realize_opportunity(gap, execution, costs, latency_ms=250)


def test_buckets_below_min_count_are_dropped():
    costs = RoundTripCosts(taker_fee_bps=0.0, slippage_bps_per_leg=0.0)
    opportunities = [_opportunity(0.001, 0.001, costs) for _ in range(5)]
    buckets = calibration_curve(opportunities, bucket_width=0.0005, min_per_bucket=30)
    assert buckets == []


def test_bucket_reports_correct_win_rate_and_averages():
    costs = RoundTripCosts(taker_fee_bps=0.0, slippage_bps_per_leg=0.0)
    # 20 opportunities that stay net-positive (win), 10 that fully close (loss)
    opportunities = [_opportunity(0.001, 0.001, costs) for _ in range(20)]
    opportunities += [_opportunity(0.001, -0.0005, costs) for _ in range(10)]

    buckets = calibration_curve(opportunities, bucket_width=0.0005, min_per_bucket=10)
    assert len(buckets) == 1
    bucket = buckets[0]
    assert bucket.n == 30
    assert bucket.win_rate == 20 / 30
    assert bucket.avg_win > 0
    assert bucket.avg_loss < 0

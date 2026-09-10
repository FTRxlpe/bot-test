import pytest

from polymarket_strategy.pricing import calibration_curve, mispricing


def test_mispricing_positive_edge():
    assert mispricing(actual_win_rate=0.95, implied_probability=0.90) == pytest.approx(0.05)


def test_mispricing_negative_edge():
    assert mispricing(actual_win_rate=0.80, implied_probability=0.90) == pytest.approx(-0.10)


def test_mispricing_zero_when_calibrated():
    assert mispricing(actual_win_rate=0.5, implied_probability=0.5) == 0.0


def test_calibration_curve_basic():
    # 100 trades at price 0.90 that all resolve YES -> delta of +0.10 in that bucket
    prices = [0.90] * 100
    outcomes = [1] * 100
    buckets = calibration_curve(prices, outcomes, bucket_width=0.05, min_trades_per_bucket=30)
    assert len(buckets) == 1
    b = buckets[0]
    assert b.n_trades == 100
    assert b.actual_win_rate == pytest.approx(1.0)
    assert b.delta > 0


def test_calibration_curve_drops_sparse_buckets():
    prices = [0.90] * 5  # below min_trades_per_bucket
    outcomes = [1] * 5
    buckets = calibration_curve(prices, outcomes, bucket_width=0.05, min_trades_per_bucket=30)
    assert buckets == []


def test_calibration_curve_mismatched_lengths_raises():
    with pytest.raises(ValueError):
        calibration_curve([0.5, 0.6], [1], bucket_width=0.05)

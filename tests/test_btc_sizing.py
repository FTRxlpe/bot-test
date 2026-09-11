import pytest

from btc_arbitrage.calibration import GapBucket
from btc_arbitrage.sizing import kelly_fraction


def test_favorable_bucket_gets_positive_size():
    bucket = GapBucket(low=0.001, high=0.0015, n=100, win_rate=0.8, avg_win=0.002, avg_loss=-0.001)
    size = kelly_fraction(bucket, fraction=1.0)
    assert size > 0


def test_unfavorable_bucket_gets_zero_size():
    bucket = GapBucket(low=0.001, high=0.0015, n=100, win_rate=0.2, avg_win=0.001, avg_loss=-0.002)
    size = kelly_fraction(bucket, fraction=1.0)
    assert size == 0.0


def test_no_observed_losses_refuses_to_size():
    bucket = GapBucket(low=0.001, high=0.0015, n=100, win_rate=1.0, avg_win=0.002, avg_loss=0.0)
    assert kelly_fraction(bucket) == 0.0


def test_fractional_kelly_scales_down_full_kelly():
    bucket = GapBucket(low=0.001, high=0.0015, n=100, win_rate=0.8, avg_win=0.002, avg_loss=-0.001)
    full = kelly_fraction(bucket, fraction=1.0)
    quarter = kelly_fraction(bucket, fraction=0.25)
    assert quarter == pytest.approx(full * 0.25)


def test_invalid_fraction_raises():
    bucket = GapBucket(low=0.001, high=0.0015, n=100, win_rate=0.8, avg_win=0.002, avg_loss=-0.001)
    with pytest.raises(ValueError):
        kelly_fraction(bucket, fraction=0.0)
    with pytest.raises(ValueError):
        kelly_fraction(bucket, fraction=1.5)

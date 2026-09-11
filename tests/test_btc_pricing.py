from btc_arbitrage.data import Snapshot
from btc_arbitrage.pricing import detect_gap


def test_detect_gap_picks_cheapest_and_most_expensive_market():
    snap = Snapshot(timestamp_ms=0, prices={"a": 100.0, "b": 101.0, "c": 99.5}, index=0)
    gap = detect_gap(snap)
    assert gap is not None
    assert gap.buy_market == "c"
    assert gap.sell_market == "b"
    assert gap.buy_price == 99.5
    assert gap.sell_price == 101.0
    assert gap.raw_gap_fraction == (101.0 - 99.5) / 99.5


def test_detect_gap_returns_none_for_single_market():
    snap = Snapshot(timestamp_ms=0, prices={"a": 100.0}, index=0)
    assert detect_gap(snap) is None


def test_detect_gap_returns_none_when_all_prices_equal():
    snap = Snapshot(timestamp_ms=0, prices={"a": 100.0, "b": 100.0}, index=0)
    assert detect_gap(snap) is None

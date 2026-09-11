"""Formula 1: cross-market price-gap detection.

At a single synchronized snapshot (one timestamp, one quote per market), the
raw gap is the spread between the cheapest and most expensive quoted price,
as a fraction of the cheap price -- the theoretical maximum capturable by
buying on the cheap market and selling on the expensive one, before any
costs or execution delay.
"""
from __future__ import annotations

from dataclasses import dataclass

from .data import Snapshot


@dataclass(frozen=True)
class Gap:
    timestamp_ms: int
    buy_market: str
    sell_market: str
    buy_price: float
    sell_price: float
    raw_gap_fraction: float  # (sell_price - buy_price) / buy_price
    index: int = 0


def detect_gap(snapshot: Snapshot) -> Gap | None:
    if len(snapshot.prices) < 2:
        return None
    buy_market = min(snapshot.prices, key=snapshot.prices.get)
    sell_market = max(snapshot.prices, key=snapshot.prices.get)
    if buy_market == sell_market:
        return None
    buy_price = snapshot.prices[buy_market]
    sell_price = snapshot.prices[sell_market]
    return Gap(
        timestamp_ms=snapshot.timestamp_ms,
        buy_market=buy_market,
        sell_market=sell_market,
        buy_price=buy_price,
        sell_price=sell_price,
        raw_gap_fraction=(sell_price - buy_price) / buy_price,
        index=snapshot.index,
    )

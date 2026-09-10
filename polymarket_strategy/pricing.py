"""Price-error correction: bucket historical (price, outcome) pairs and compare
the empirical win rate in each bucket to the market-implied probability.

delta = actual_win_rate - implied_probability

A positive delta means contracts in that price bucket resolved YES more often
than their price implied -- i.e. the market underpriced them (or, equivalently,
overpriced the NO side).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PriceBucket:
    low: float
    high: float
    n_trades: int
    actual_win_rate: float
    implied_probability: float

    @property
    def delta(self) -> float:
        return self.actual_win_rate - self.implied_probability

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2


def calibration_curve(
    prices: list[float],
    outcomes: list[int],
    bucket_width: float = 0.05,
    min_trades_per_bucket: int = 30,
) -> list[PriceBucket]:
    """Build an empirical calibration curve from historical resolved trades.

    prices: entry price paid for a YES share, in (0, 1).
    outcomes: 1 if the market resolved YES, 0 otherwise.
    Buckets with fewer than min_trades_per_bucket observations are dropped --
    a win rate estimated from a handful of trades is noise, not edge.
    """
    if len(prices) != len(outcomes):
        raise ValueError("prices and outcomes must be the same length")

    n_buckets = int(round(1.0 / bucket_width))
    sums = [0.0] * n_buckets
    counts = [0] * n_buckets

    for price, outcome in zip(prices, outcomes):
        if not 0.0 < price < 1.0:
            continue
        idx = min(int(price / bucket_width), n_buckets - 1)
        sums[idx] += outcome
        counts[idx] += 1

    buckets = []
    for idx in range(n_buckets):
        if counts[idx] < min_trades_per_bucket:
            continue
        low = idx * bucket_width
        high = low + bucket_width
        buckets.append(
            PriceBucket(
                low=low,
                high=high,
                n_trades=counts[idx],
                actual_win_rate=sums[idx] / counts[idx],
                implied_probability=(low + high) / 2,
            )
        )
    return buckets


def mispricing(actual_win_rate: float, implied_probability: float) -> float:
    """delta = actual_win_rate - implied_probability"""
    return actual_win_rate - implied_probability

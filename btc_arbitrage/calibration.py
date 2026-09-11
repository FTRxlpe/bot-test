"""Calibration curve: for opportunities bucketed by their RAW gap size at
detection time, what actually happened to the net edge once realistic
execution latency and costs were applied?

Fit only on the train split (see backtest.py) -- this is what lets the
strategy make an out-of-sample decision on the test split instead of peeking
at outcomes it couldn't have known about at the time. Mirrors
polymarket_strategy/pricing.py's per-price-bucket calibration_curve, applied
to gap size instead of contract price.
"""
from __future__ import annotations

from dataclasses import dataclass

from .execution import Opportunity


@dataclass(frozen=True)
class GapBucket:
    low: float
    high: float
    n: int
    win_rate: float   # fraction of opportunities in this bucket with net_edge > 0
    avg_win: float    # mean net_edge among winners (> 0)
    avg_loss: float   # mean net_edge among losers (<= 0), i.e. a negative number

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2


def calibration_curve(
    opportunities: list[Opportunity],
    bucket_width: float = 0.0005,
    min_per_bucket: int = 30,
) -> list[GapBucket]:
    """Buckets with fewer than min_per_bucket observations are dropped -- a
    win rate estimated from a handful of opportunities is noise, not edge."""
    if not opportunities:
        return []
    max_gap = max(o.detected.raw_gap_fraction for o in opportunities)
    n_buckets = max(1, int(max_gap / bucket_width) + 1)

    buckets = []
    for i in range(n_buckets):
        low, high = i * bucket_width, (i + 1) * bucket_width
        members = [o for o in opportunities if low <= o.detected.raw_gap_fraction < high]
        if len(members) < min_per_bucket:
            continue
        wins = [o.net_edge for o in members if o.net_edge > 0]
        losses = [o.net_edge for o in members if o.net_edge <= 0]
        buckets.append(
            GapBucket(
                low=low,
                high=high,
                n=len(members),
                win_rate=len(wins) / len(members),
                avg_win=(sum(wins) / len(wins)) if wins else 0.0,
                avg_loss=(sum(losses) / len(losses)) if losses else 0.0,
            )
        )
    return buckets

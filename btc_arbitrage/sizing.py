"""Formula 3: Kelly position sizing from the calibrated win/loss profile of a
gap-size bucket -- the same criterion used for any bet with empirically
estimated odds:

    f* = (p * b - q) / b

p: calibrated probability the trade nets a positive edge after latency + costs
q: 1 - p
b: payout ratio actually observed in this bucket, avg_win / |avg_loss|
"""
from __future__ import annotations

from .calibration import GapBucket


def kelly_fraction(bucket: GapBucket, fraction: float = 0.25) -> float:
    """Fractional-Kelly stake as a fraction of bankroll, clamped to [0, 1].

    `fraction` applies a fractional-Kelly discount (e.g. 0.25 for
    quarter-Kelly) since full Kelly assumes the calibrated win probability is
    exact, which it never is. Returns 0 if the bucket has no observed losses
    to price risk against, or the edge is not favorable.
    """
    if not 0.0 < fraction <= 1.0:
        raise ValueError("fraction must be in (0, 1]")
    if bucket.avg_loss == 0.0:
        return 0.0  # can't price the downside -- refuse to size a bet on it

    p = bucket.win_rate
    q = 1.0 - p
    b = bucket.avg_win / abs(bucket.avg_loss)
    if b <= 0:
        return 0.0

    f_star = (p * b - q) / b
    f_star *= fraction
    return max(0.0, min(1.0, f_star))

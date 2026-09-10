"""Kelly criterion position sizing.

f* = (p * b - q) / b

p: probability of winning
q: probability of losing (1 - p)
b: net odds received on the bet (profit per unit staked if it wins)

For a Polymarket YES share bought at `price`, a $1 stake buys 1/price shares,
each paying $1 on a win, so the net profit per unit staked is:
  b = (1 - price) / price
"""
from __future__ import annotations


def kelly_fraction(win_probability: float, price: float, fraction: float = 1.0) -> float:
    """Returns the fraction of bankroll to stake (clamped to [0, 1]).

    `fraction` applies a fractional-Kelly discount (e.g. 0.25 for quarter-Kelly)
    to reduce variance versus full Kelly, which is standard practice since full
    Kelly assumes the win-probability estimate is exact -- it never is.
    """
    if not 0.0 <= win_probability <= 1.0:
        raise ValueError("win_probability must be in [0, 1]")
    if not 0.0 < price < 1.0:
        raise ValueError("price must be in (0, 1)")
    if not 0.0 < fraction <= 1.0:
        raise ValueError("fraction must be in (0, 1]")

    p = win_probability
    q = 1.0 - p
    b = (1.0 - price) / price

    f_star = (p * b - q) / b
    f_star *= fraction
    return max(0.0, min(1.0, f_star))

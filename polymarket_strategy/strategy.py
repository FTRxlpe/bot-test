"""Combines the three formulas into a trade signal:

  price error (delta) -> expected value (EV) -> Kelly position size -> entry
"""
from __future__ import annotations

from dataclasses import dataclass

from .ev import expected_value
from .kelly import kelly_fraction
from .pricing import PriceBucket, mispricing


@dataclass(frozen=True)
class StrategyConfig:
    min_delta: float = 0.02       # ignore edges smaller than this (fees/slippage buffer)
    min_price: float = 0.80       # focus range from the pitch: 0.80-0.99
    max_price: float = 0.99
    kelly_fraction_cap: float = 0.25  # quarter-Kelly, not full Kelly
    fee_rate: float = 0.0         # Polymarket charges no explicit taker fee as of writing;
                                   # set >0 to stress-test the edge against a hypothetical fee
    max_stake_fraction_of_starting_bankroll: float = 0.02
    # Caps every single trade's stake at this fraction of the STARTING bankroll
    # (not the current, possibly-compounded bankroll). Real order books have
    # finite depth at a given price -- you cannot keep deploying an
    # ever-growing bankroll into one contract without slippage eating the
    # edge. Without this cap, a real edge compounded via Kelly across
    # thousands of trades produces fantastical, unrealistic total returns.


@dataclass(frozen=True)
class Signal:
    price: float
    calibrated_win_probability: float
    delta: float
    ev: float
    kelly_size: float
    take: bool


def generate_signals(buckets: list[PriceBucket], config: StrategyConfig) -> list[Signal]:
    signals = []
    for bucket in buckets:
        price = bucket.midpoint
        if not (config.min_price <= price <= config.max_price):
            continue

        delta = mispricing(bucket.actual_win_rate, bucket.implied_probability)
        win_prob = bucket.actual_win_rate
        ev = expected_value(win_prob, price) - config.fee_rate
        size = kelly_fraction(win_prob, price, fraction=config.kelly_fraction_cap)

        take = delta >= config.min_delta and ev > 0 and size > 0
        signals.append(
            Signal(
                price=price,
                calibrated_win_probability=win_prob,
                delta=delta,
                ev=ev,
                kelly_size=size if take else 0.0,
                take=take,
            )
        )
    return signals

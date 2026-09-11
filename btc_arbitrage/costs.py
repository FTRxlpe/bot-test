"""Round-trip trading costs for a two-leg arbitrage (buy on one market, sell
on another).

Every detected price gap must clear BOTH legs' costs to be worth taking.
Modeled in basis points so they compose directly with the gap fraction
computed in pricing.py.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoundTripCosts:
    taker_fee_bps: float = 10.0        # Binance-style spot taker fee, ~0.10% per leg
    slippage_bps_per_leg: float = 5.0  # price impact of actually filling market orders on real depth

    def total_cost_fraction(self) -> float:
        """Combined cost of BOTH legs (buy + sell), as a fraction of price."""
        per_leg = (self.taker_fee_bps + self.slippage_bps_per_leg) / 10_000.0
        return per_leg * 2

"""Strategy configuration: how the three formulas (gap detection ->
calibrated net-edge -> Kelly sizing) are wired together in backtest.py.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyConfig:
    latency_ms: int = 250              # time to detect a gap and place both legs
    taker_fee_bps: float = 10.0
    slippage_bps_per_leg: float = 5.0
    min_calibrated_edge: float = 0.0   # require calibrated p*avg_win + q*avg_loss > this
    kelly_fraction_cap: float = 0.25   # quarter-Kelly, not full Kelly
    max_stake_fraction_of_starting_bankroll: float = 0.02
    # Caps every single trade's stake at this fraction of the STARTING
    # bankroll (not the current, possibly-compounded bankroll) -- real order
    # books have finite depth at a given price, so you cannot keep deploying
    # an ever-growing bankroll into one gap without slippage eating the edge.
    bucket_width: float = 0.0005
    min_trades_per_bucket: int = 30

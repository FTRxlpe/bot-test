"""Formula 2: what a detected gap is actually worth once execution latency
and round-trip trading costs are accounted for.

A detected gap is not a free amount of money sitting there: by the time both
legs of the trade actually fill, `latency_ms` has passed (network transit +
exchange order processing), and the gap can have partially closed, fully
closed, or reversed -- because the lagging market's price catches up, or a
faster competitor already took it. The REALIZED edge uses the actual price
gap at execution time, not the gap at detection time. This is what turns
"spots price errors before humans notice" into an honest number instead of a
marketing claim.
"""
from __future__ import annotations

from dataclasses import dataclass

from .costs import RoundTripCosts
from .data import Snapshot
from .pricing import Gap


@dataclass(frozen=True)
class Opportunity:
    detected: Gap
    executed_gap_fraction: float  # actual (sell - buy) / buy at execution time
    net_edge: float               # executed_gap_fraction - round-trip costs; the real, realized P&L fraction
    latency_ms: int


def realize_opportunity(
    gap: Gap,
    snapshot_at_execution: Snapshot,
    costs: RoundTripCosts,
    latency_ms: int,
) -> Opportunity | None:
    if gap.buy_market not in snapshot_at_execution.prices:
        return None
    if gap.sell_market not in snapshot_at_execution.prices:
        return None
    buy_price = snapshot_at_execution.prices[gap.buy_market]
    sell_price = snapshot_at_execution.prices[gap.sell_market]
    executed_gap_fraction = (sell_price - buy_price) / buy_price
    net_edge = executed_gap_fraction - costs.total_cost_fraction()
    return Opportunity(
        detected=gap,
        executed_gap_fraction=executed_gap_fraction,
        net_edge=net_edge,
        latency_ms=latency_ms,
    )

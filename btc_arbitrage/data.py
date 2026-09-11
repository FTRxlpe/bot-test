"""BTC multi-market price data.

Two sources:
  - load_snapshots_csv: real, timestamped multi-exchange quotes exported by
    the user (long-format columns: timestamp_ms, market, price). This
    sandbox has no network access to Binance or any exchange API from this
    environment (outbound requests to api.binance.com are rejected by the
    network policy -- confirmed empirically, not assumed), so it cannot
    fetch real data itself.
  - generate_synthetic_snapshots: a labeled, illustrative multi-market
    dataset used so the detection/backtest engine is runnable and testable
    without external data. It is NOT a claim about real Binance/exchange
    mispricing. It models a shared BTC "true price" random walk plus
    occasional stale-quote lag on one market at a time -- the actual
    physical mechanism behind real cross-exchange price gaps -- rather than
    fabricating a "bot finds free money everywhere" edge.
"""
from __future__ import annotations

import csv
import random
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class Snapshot:
    timestamp_ms: int
    prices: dict[str, float]
    index: int = 0


def load_snapshots_csv(path: str) -> list[Snapshot]:
    """Load long-format rows (timestamp_ms, market, price) into one Snapshot
    per distinct timestamp, sorted chronologically."""
    by_ts: dict[int, dict[str, float]] = defaultdict(dict)
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = int(row["timestamp_ms"])
            by_ts[ts][row["market"]] = float(row["price"])

    snapshots = []
    for i, ts in enumerate(sorted(by_ts)):
        snapshots.append(Snapshot(timestamp_ms=ts, prices=by_ts[ts], index=i))
    return snapshots


def generate_synthetic_snapshots(
    n_steps: int = 20000,
    markets: tuple[str, ...] = ("binance", "coinbase", "kraken", "okx", "bybit"),
    tick_ms: int = 250,
    start_price: float = 60000.0,
    step_vol: float = 0.0008,
    lag_probability_per_step: float = 0.004,
    lag_duration_steps: tuple[int, int] = (2, 20),
    microstructure_noise_bps: float = 2.0,
    seed: int = 42,
) -> list[Snapshot]:
    """Simulate synchronized quotes across several BTC markets.

    Mechanism modeled (the real physical source of cross-exchange BTC price
    gaps, not a fabricated one):
      - one shared "true" mid-price follows a random walk.
      - at each step, any market not currently lagging can independently
        start "lagging" (stale order book / slow price feed) for a random
        number of steps. Its quoted price freezes at the true price at the
        moment the lag started, while the true price keeps moving -- then it
        snaps back to tracking the true price when the lag ends. This is
        what actually creates a transient, closable price gap between
        markets.
      - every market's quote also carries small, zero-mean microstructure
        noise (bid/ask bounce) on top, so apparent gaps exist even without a
        lag, but they average out to ~0 edge without one.
    """
    rng = random.Random(seed)
    true_price = start_price
    lag_until = {m: -1 for m in markets}
    frozen_price = {m: start_price for m in markets}

    snapshots = []
    for i in range(n_steps):
        true_price *= 1.0 + rng.gauss(0.0, step_vol)
        ts = i * tick_ms

        prices = {}
        for m in markets:
            if i <= lag_until[m]:
                base = frozen_price[m]
            else:
                base = true_price
                if rng.random() < lag_probability_per_step:
                    dur = rng.randint(*lag_duration_steps)
                    lag_until[m] = i + dur
                    frozen_price[m] = true_price
                    base = frozen_price[m]
            noise = base * rng.gauss(0.0, microstructure_noise_bps / 10_000.0)
            prices[m] = base + noise

        snapshots.append(Snapshot(timestamp_ms=ts, prices=prices, index=i))

    return snapshots

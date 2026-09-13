"""Trade data loading.

Two sources:
  - load_trades_csv: real historical trades exported from Polymarket
    (columns: price, outcome[, market_id, timestamp]). Use this for a real
    result -- this sandbox has no network access to Polymarket's API, so it
    cannot fetch that data itself.
  - generate_synthetic_trades: a labeled, illustrative dataset used so the
    backtest engine is runnable and testable without external data. It is
    NOT a claim about real Polymarket mispricing, and it deliberately does
    NOT hit a 99% win rate -- it models a modest, plausible favorite-longshot
    bias (a well-documented, real phenomenon in prediction markets) so the
    strategy has *some* honest edge to find without fabricating the pitch's
    numbers.
"""
from __future__ import annotations

import csv
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Trade:
    price: float
    outcome: int  # 1 if resolved YES, 0 if resolved NO
    market_id: str = ""
    index: int = 0  # chronological order
    timestamp: float = 0.0  # unix seconds; 0.0 means "unknown" (index-only ordering)


def load_trades_csv(path: str) -> list[Trade]:
    trades = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            timestamp = row.get("timestamp", "")
            trades.append(
                Trade(
                    price=float(row["price"]),
                    outcome=int(row["outcome"]),
                    market_id=row.get("market_id", ""),
                    index=i,
                    timestamp=float(timestamp) if timestamp else 0.0,
                )
            )
    return trades


def generate_synthetic_trades(
    n: int = 20000,
    favorite_longshot_bias: float = 0.05,
    seed: int = 42,
) -> list[Trade]:
    """Simulate resolved binary-contract trades across the full price range.

    True win probability for a contract priced at `price` is modeled as:
        true_p = price + bias(price)
    where bias(price) is 0 for price <= 0.5 and rises toward
    `favorite_longshot_bias` as price approaches 1.0 -- i.e. the market
    slightly underprices near-certain outcomes, which is the mechanism the
    pitch describes. Below 0.5 the market is modeled as fair (no edge), so
    the backtest has to find the edge rather than being handed one everywhere.
    """
    rng = random.Random(seed)
    trades = []
    for i in range(n):
        price = rng.uniform(0.01, 0.99)
        if price > 0.5:
            bias = favorite_longshot_bias * ((price - 0.5) / 0.5)
        else:
            bias = 0.0
        true_p = min(0.999, price + bias)
        outcome = 1 if rng.random() < true_p else 0
        trades.append(Trade(price=price, outcome=outcome, market_id=f"synthetic-{i}", index=i))
    return trades


def generate_synthetic_trades_with_timestamps(
    n: int = 20000,
    days: int = 120,
    favorite_longshot_bias: float = 0.05,
    seed: int = 42,
    end_time: float | None = None,
) -> list[Trade]:
    """Same generative model as generate_synthetic_trades, but with each
    trade also assigned a real timestamp spread evenly over the last `days`
    days (ending at `end_time`, or now if not given). Needed to exercise
    run_last_n_days_backtest, which requires real timestamps -- it has no
    concept of a "day" for index-only synthetic data.

    Labeled, illustrative data only -- NOT a claim about real Polymarket
    activity or trade volume.
    """
    import time as _time

    rng = random.Random(seed)
    end_time = end_time if end_time is not None else _time.time()
    start_time = end_time - days * 86400
    trades = []
    for i in range(n):
        price = rng.uniform(0.01, 0.99)
        if price > 0.5:
            bias = favorite_longshot_bias * ((price - 0.5) / 0.5)
        else:
            bias = 0.0
        true_p = min(0.999, price + bias)
        outcome = 1 if rng.random() < true_p else 0
        timestamp = start_time + rng.uniform(0.0, 1.0) * (end_time - start_time)
        trades.append(
            Trade(price=price, outcome=outcome, market_id=f"synthetic-{i}", index=i, timestamp=timestamp)
        )
    return trades

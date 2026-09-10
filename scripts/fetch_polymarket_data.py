#!/usr/bin/env python3
"""Fetch real resolved-market price history from Polymarket's public APIs and
write it to a CSV usable by scripts/run_backtest.py --csv.

For each closed market, we take the resolved outcome (from the market's final
outcomePrices, which settle to ~1 for the winning outcome and ~0 for the
losing one) and pair it with a sample of historical prices the winning
token traded at before resolution. Each (price, outcome) pair approximates
"if you had bought this contract at this price, did it resolve YES?" --
exactly what the strategy's calibration curve needs.

Requires network access to gamma-api.polymarket.com and clob.polymarket.com
(this script does NOT work from a sandbox with those hosts blocked -- run it
from an environment with normal internet access, e.g. a GitHub Codespace).

Usage:
  python scripts/fetch_polymarket_data.py --out real_trades.csv --n-markets 300
  python scripts/run_backtest.py --csv real_trades.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request

GAMMA_URL = "https://gamma-api.polymarket.com/markets"
CLOB_HISTORY_URL = "https://clob.polymarket.com/prices-history"


def _get_json(url: str, params: dict, retries: int = 3, timeout: int = 20):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    full_url = f"{url}?{query}"
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(full_url, headers={"User-Agent": "bot-test-research/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            last_err = f"HTTP {e.code}: {body}"
            if e.code < 500:
                break  # a 4xx won't fix itself on retry -- fail fast with the body
            time.sleep(1.5 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = str(e)
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {full_url}: {last_err}")


def fetch_closed_markets(n_markets: int, batch_size: int = 100):
    markets = []
    offset = 0
    while len(markets) < n_markets:
        page = _get_json(
            GAMMA_URL,
            {"closed": "true", "limit": min(batch_size, n_markets - len(markets)), "offset": offset},
        )
        if not page:
            break
        markets.extend(page)
        offset += len(page)
        if len(page) < batch_size:
            break
    return markets[:n_markets]


def resolved_outcome_for_first_token(market: dict) -> tuple[str, int] | None:
    """Always tracks the FIRST outcome token (index 0, typically "Yes") so
    both wins and losses show up in the sample -- returns (token_id, outcome)
    where outcome is 1 if that token ended up winning, 0 if it lost.

    Sampling only the winning token's price history (regardless of which
    side it is) would give outcome=1 on every row and destroy the
    calibration signal entirely -- there'd be no losses to compare against.
    """
    try:
        prices = [float(p) for p in json.loads(market["outcomePrices"])]
        token_ids = json.loads(market["clobTokenIds"])
    except (KeyError, ValueError, TypeError):
        return None
    if len(prices) != 2 or len(token_ids) != 2:
        return None
    # Winning outcome settles near 1.0, losing near 0.0.
    if prices[0] > 0.9 and prices[1] < 0.1:
        return token_ids[0], 1
    if prices[1] > 0.9 and prices[0] < 0.1:
        return token_ids[0], 0
    return None  # not cleanly resolved (e.g. still ambiguous) -- skip


def fetch_price_history(token_id: str, fidelity_minutes: int = 60):
    # startTs=0 asks for the token's full history; some CLOB deployments
    # default to a short recent window if startTs/endTs are omitted.
    data = _get_json(
        CLOB_HISTORY_URL,
        {"market": token_id, "fidelity": fidelity_minutes, "startTs": 0, "endTs": int(time.time())},
    )
    return data.get("history", [])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="real_trades.csv")
    parser.add_argument("--n-markets", type=int, default=300)
    parser.add_argument("--samples-per-market", type=int, default=20)
    parser.add_argument("--fidelity-minutes", type=int, default=60)
    args = parser.parse_args()

    print(f"Fetching up to {args.n_markets} closed markets from Gamma API...", file=sys.stderr)
    markets = fetch_closed_markets(args.n_markets)
    print(f"Got {len(markets)} closed markets.", file=sys.stderr)

    rows_written = 0
    with open(args.out, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["price", "outcome", "market_id"])

        for i, market in enumerate(markets):
            resolved = resolved_outcome_for_first_token(market)
            if resolved is None:
                continue
            token_id, outcome = resolved
            market_id = market.get("conditionId", market.get("id", f"market-{i}"))

            try:
                history = fetch_price_history(token_id, args.fidelity_minutes)
            except RuntimeError as e:
                print(f"  skip {market_id}: {e}", file=sys.stderr)
                continue

            if not history:
                continue

            # Sample evenly across this token's price history, paired with
            # the ACTUAL final outcome (1 if it won, 0 if it lost) -- this is
            # what lets the calibration curve see real losses, not just wins.
            step = max(1, len(history) // args.samples_per_market)
            sampled = history[::step][: args.samples_per_market]
            for point in sampled:
                price = float(point.get("p", 0))
                if 0.0 < price < 1.0:
                    writer.writerow([price, outcome, market_id])
                    rows_written += 1

            if (i + 1) % 25 == 0:
                print(f"  processed {i + 1}/{len(markets)} markets, {rows_written} rows so far", file=sys.stderr)
            time.sleep(0.1)  # be polite to the public API

    print(f"Wrote {rows_written} rows to {args.out}", file=sys.stderr)
    if rows_written == 0:
        print(
            "No rows written -- check network access to gamma-api.polymarket.com "
            "and clob.polymarket.com from this environment.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()

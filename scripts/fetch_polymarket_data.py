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
import datetime
import json
import sys
import time
import urllib.error
import urllib.request

GAMMA_URL = "https://gamma-api.polymarket.com/markets"
CLOB_HISTORY_URL = "https://clob.polymarket.com/prices-history"

MAX_WINDOW_SECONDS = 14 * 86400  # the CLOB API rejects startTs/endTs spans
                                  # that are "too long" -- 30 days already
                                  # tripped it empirically, so stay well
                                  # under with 14 days of hourly candles


def _parse_iso_ts(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


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


def fetch_price_history(token_id: str, start_ts: int, end_ts: int, fidelity_minutes: int = 60):
    data = _get_json(
        CLOB_HISTORY_URL,
        {"market": token_id, "fidelity": fidelity_minutes, "startTs": start_ts, "endTs": end_ts},
    )
    return data.get("history", [])


def market_window(market: dict) -> tuple[int, int]:
    """Returns (start_ts, end_ts) clipped to at most MAX_WINDOW_SECONDS,
    anchored on the market's actual close time so we sample its real
    price history rather than an arbitrary recent window.
    """
    end_ts = (
        _parse_iso_ts(market.get("closedTime"))
        or _parse_iso_ts(market.get("endDate"))
        or int(time.time())
    )
    start_ts = _parse_iso_ts(market.get("startDate")) or _parse_iso_ts(market.get("createdAt"))
    # Some markets carry inconsistent/templated date fields (e.g. a reused
    # startDate from a recurring series) where startDate ends up AFTER
    # closedTime. Guard against that as well as an overly long window.
    if start_ts is None or start_ts >= end_ts or end_ts - start_ts > MAX_WINDOW_SECONDS:
        start_ts = end_ts - MAX_WINDOW_SECONDS
    return start_ts, end_ts


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
    n_unresolved = 0
    n_empty_history = 0
    n_fetch_errors = 0
    with open(args.out, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["price", "outcome", "market_id"])

        for i, market in enumerate(markets):
            resolved = resolved_outcome_for_first_token(market)
            if resolved is None:
                n_unresolved += 1
                if n_unresolved <= 2:
                    print(
                        f"  unresolved sample: outcomePrices={market.get('outcomePrices')!r} "
                        f"clobTokenIds={market.get('clobTokenIds')!r}",
                        file=sys.stderr,
                    )
                continue
            token_id, outcome = resolved
            market_id = market.get("conditionId", market.get("id", f"market-{i}"))
            start_ts, end_ts = market_window(market)

            try:
                history = fetch_price_history(token_id, start_ts, end_ts, args.fidelity_minutes)
            except RuntimeError as e:
                n_fetch_errors += 1
                print(f"  skip {market_id}: {e}", file=sys.stderr)
                continue

            if not history:
                n_empty_history += 1
                if n_empty_history <= 2:
                    print(f"  empty history for {market_id} (token {token_id}), window=[{start_ts},{end_ts}]", file=sys.stderr)
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

    print(
        f"Wrote {rows_written} rows to {args.out} "
        f"(unresolved={n_unresolved} empty_history={n_empty_history} fetch_errors={n_fetch_errors} "
        f"out of {len(markets)} markets)",
        file=sys.stderr,
    )
    if rows_written == 0:
        print(
            "No rows written -- see the unresolved/empty_history counts above "
            "for which stage is filtering everything out.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()

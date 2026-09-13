"""Live/paper trading loop: polls currently open Polymarket markets, applies
a pre-fitted calibration curve through EV + Kelly, routes every candidate
through the risk manager, and places orders via a Broker (paper by default,
live only through executor.py's triple opt-in).

`fetch_open_markets` is the only network-touching function here, kept as a
thin, mockable seam so `evaluate_market` and `run_once` -- the actual
decision logic -- are fully unit-testable without network access. This
matters because gamma-api.polymarket.com is unreachable from this sandbox
(see README): the trading LOGIC is tested here, but `fetch_open_markets`
itself has not been exercised against the live API from this environment.

Lifecycle note: this loop only handles ENTRIES. `risk_manager.record_result`
must be called separately once a placed order's market actually resolves --
a settlement poller that checks resolved outcomes and feeds P&L back into the
same RiskManager instance is a separate, not-yet-built component. Running
this loop without one means the loss-streak/daily-cap breakers never fire in
live/paper mode (they work correctly in the backtest, which knows outcomes
immediately). Do not rely on this loop's risk manager wiring alone for live
trading until a settlement poller is wired in.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

from .ev import expected_value
from .kelly import kelly_fraction
from .pricing import PriceBucket, mispricing
from .risk_manager import RiskManager
from .strategy import StrategyConfig

GAMMA_URL = "https://gamma-api.polymarket.com/markets"


@dataclass(frozen=True)
class OpenMarket:
    market_id: str
    token_id: str  # the outcome token this price/signal applies to
    price: float  # current price for that token, in (0, 1)
    question: str = ""


def _searchable_text(market: dict) -> str:
    parts = [str(market.get("category", "")), str(market.get("question", "")), str(market.get("slug", ""))]
    for tag in market.get("tags") or []:
        parts.append(str(tag.get("label", "")) if isinstance(tag, dict) else str(tag))
    return " ".join(parts).lower()


def fetch_open_markets(category: str | None = None, limit: int = 100) -> list[OpenMarket]:
    """Fetches currently open markets from Gamma API. Requires network access
    to gamma-api.polymarket.com, which this sandbox's egress policy blocks --
    this function has not been run against the live API from here.
    """
    params = {"closed": "false", "active": "true", "limit": limit}
    query = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(f"{GAMMA_URL}?{query}", headers={"User-Agent": "bot-test/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        markets = json.loads(resp.read().decode("utf-8"))

    results = []
    for m in markets:
        if category and category.lower() not in _searchable_text(m):
            continue
        try:
            prices = [float(p) for p in json.loads(m["outcomePrices"])]
            token_ids = json.loads(m["clobTokenIds"])
        except (KeyError, ValueError, TypeError):
            continue
        if len(prices) != 2 or len(token_ids) != 2:
            continue
        price = prices[0]
        if not 0.0 < price < 1.0:
            continue
        results.append(
            OpenMarket(
                market_id=str(m.get("conditionId", m.get("id", ""))),
                token_id=token_ids[0],
                price=price,
                question=str(m.get("question", "")),
            )
        )
    return results


@dataclass(frozen=True)
class MarketSignal:
    market: OpenMarket
    calibrated_win_probability: float
    delta: float
    ev: float
    kelly_size: float
    take: bool


def evaluate_market(
    market: OpenMarket, buckets: list[PriceBucket], config: StrategyConfig
) -> MarketSignal | None:
    """Applies a pre-fit calibration curve to one open market's current
    price. Returns None if no bucket covers this price or it's outside the
    configured trading range -- never invents a probability for a price the
    training data didn't cover.
    """
    if not (config.min_price <= market.price <= config.max_price):
        return None
    bucket = next((b for b in buckets if b.low <= market.price < b.high), None)
    if bucket is None:
        return None

    calibrated_p = bucket.actual_win_rate
    delta = mispricing(calibrated_p, market.price)
    ev = expected_value(calibrated_p, market.price) - config.fee_rate
    size = kelly_fraction(calibrated_p, market.price, fraction=config.kelly_fraction_cap)
    take = delta >= config.min_delta and ev > 0 and size > 0

    return MarketSignal(
        market=market,
        calibrated_win_probability=calibrated_p,
        delta=delta,
        ev=ev,
        kelly_size=size if take else 0.0,
        take=take,
    )


@dataclass(frozen=True)
class Decision:
    signal: MarketSignal
    placed: bool
    reason: str = ""
    order: object = None


def run_once(
    markets: list[OpenMarket],
    buckets: list[PriceBucket],
    config: StrategyConfig,
    risk_manager: RiskManager,
    broker,
    bankroll: float,
    day_key,
) -> list[Decision]:
    """One polling cycle: evaluate every open market, and for every signal
    that clears the strategy AND the risk manager, place an order through
    `broker` (a PaperBroker or LiveBroker from executor.py).
    """
    decisions = []
    for market in markets:
        signal = evaluate_market(market, buckets, config)
        if signal is None or not signal.take:
            continue

        risk_decision = risk_manager.check(day_key)
        if not risk_decision.allowed:
            risk_manager.record_skip_during_cooldown()
            decisions.append(Decision(signal=signal, placed=False, reason=risk_decision.reason))
            continue

        desired_stake = bankroll * signal.kelly_size
        stake = risk_manager.cap_stake(desired_stake)
        if stake <= 0:
            decisions.append(Decision(signal=signal, placed=False, reason="stake capped to zero"))
            continue

        size_shares = stake / market.price
        order = broker.place_order(
            token_id=market.token_id, side="BUY", price=market.price, size=size_shares
        )
        decisions.append(Decision(signal=signal, placed=True, order=order))
    return decisions

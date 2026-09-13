"""Order execution: paper trading by default, live trading only behind an
explicit triple opt-in on a dedicated wallet.

Paper mode (default, always available, no keys needed):
  `PaperBroker` simulates a fill at the quoted price and appends the trade to
  a local JSON-lines ledger. It never touches the network for order placement
  (market data reads are separate, in `scripts/fetch_polymarket_data.py` /
  a future live market-data poller).

Live mode (opt-in, real money):
  `LiveBroker` places real orders on Polymarket's CLOB via `py-clob-client`
  (the official Python client -- this module deliberately does not
  reimplement EIP-712 order signing itself). It refuses to construct unless
  ALL THREE of the following hold, mirroring the double-opt-in pattern this
  project's sibling stock-trading bot uses for Alpaca live trading:

    1. The caller explicitly passes `live=True` (i.e. a `--live` CLI flag,
       never a config default).
    2. Environment variable `POLYMARKET_LIVE_TRADING=true` is set.
    3. Environment variable `POLYMARKET_PRIVATE_KEY` is set, naming the
       dedicated wallet to trade from. This should NOT be a wallet holding
       unrelated funds -- see the README's live-trading section.

  Missing any one of the three raises `LiveTradingNotConfirmed` rather than
  silently falling back to paper mode -- an operator who typed `--live` and
  gets silently downgraded to paper trading might believe real orders were
  placed when none were.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass


class LiveTradingNotConfirmed(RuntimeError):
    """Raised when live trading is requested but the triple opt-in is incomplete."""


@dataclass
class OrderResult:
    mode: str  # "paper" or "live"
    side: str  # "BUY" or "SELL"
    token_id: str
    price: float
    size: float
    status: str
    order_id: str = ""
    raw_response: dict | None = None


class PaperBroker:
    """Simulated execution: fills instantly and fully at the quoted price.
    No slippage or partial-fill modeling -- this is for strategy-loop testing
    and paper-trading dashboards, not a substitute for the backtest engine's
    honest out-of-sample accounting.
    """

    def __init__(self, ledger_path: str = "paper_trades.jsonl"):
        self.ledger_path = ledger_path

    def place_order(self, token_id: str, side: str, price: float, size: float) -> OrderResult:
        result = OrderResult(
            mode="paper",
            side=side,
            token_id=token_id,
            price=price,
            size=size,
            status="filled",
            order_id=f"paper-{int(time.time() * 1000)}",
        )
        self._append_ledger(result)
        return result

    def _append_ledger(self, result: OrderResult) -> None:
        record = asdict(result)
        record["timestamp"] = time.time()
        with open(self.ledger_path, "a") as f:
            f.write(json.dumps(record) + "\n")


def _check_live_trading_confirmed(live: bool) -> str:
    """Returns the confirmed private key, or raises LiveTradingNotConfirmed."""
    if not live:
        raise LiveTradingNotConfirmed(
            "live=True was not passed -- pass --live explicitly to trade with real funds"
        )
    if os.environ.get("POLYMARKET_LIVE_TRADING", "").lower() != "true":
        raise LiveTradingNotConfirmed(
            "POLYMARKET_LIVE_TRADING=true is not set -- refusing to place real orders"
        )
    private_key = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
    if not private_key:
        raise LiveTradingNotConfirmed(
            "POLYMARKET_PRIVATE_KEY is not set -- refusing to place real orders without a "
            "signing key for the dedicated trading wallet"
        )
    return private_key


class LiveBroker:
    """Places real orders on Polymarket's CLOB. Constructing this class talks
    to no network until `place_order` is called; construction itself only
    validates the triple opt-in and lazily imports `py-clob-client` (an
    optional dependency -- paper trading and backtesting never need it).
    """

    def __init__(
        self,
        live: bool,
        host: str = "https://clob.polymarket.com",
        chain_id: int = 137,
        funder_address: str | None = None,
    ):
        private_key = _check_live_trading_confirmed(live)

        try:
            from py_clob_client.client import ClobClient  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "Live trading requires the 'py-clob-client' package. Install it with "
                "`pip install py-clob-client` -- it is intentionally NOT a hard dependency "
                "of this repo so paper trading and backtesting work without it."
            ) from e

        funder = funder_address or os.environ.get("POLYMARKET_FUNDER_ADDRESS")
        self._client = ClobClient(host, key=private_key, chain_id=chain_id, funder=funder)
        self._client.set_api_creds(self._client.create_or_derive_api_creds())

    def place_order(self, token_id: str, side: str, price: float, size: float) -> OrderResult:
        from py_clob_client.clob_types import OrderArgs, OrderType  # type: ignore

        order_args = OrderArgs(price=price, size=size, side=side, token_id=token_id)
        signed_order = self._client.create_order(order_args)
        response = self._client.post_order(signed_order, OrderType.GTC)

        return OrderResult(
            mode="live",
            side=side,
            token_id=token_id,
            price=price,
            size=size,
            status=response.get("status", "unknown") if isinstance(response, dict) else "unknown",
            order_id=response.get("orderID", "") if isinstance(response, dict) else "",
            raw_response=response if isinstance(response, dict) else None,
        )


def make_broker(live: bool, ledger_path: str = "paper_trades.jsonl"):
    """Single entry point the CLI uses: returns a PaperBroker unless `live`
    is True AND the full opt-in is present, in which case it returns a
    LiveBroker. Never silently downgrades a `--live` request -- an
    incomplete opt-in raises instead of returning a paper broker, so a
    misconfigured live run fails loudly rather than trading fake money while
    the operator believes it's real.
    """
    if not live:
        return PaperBroker(ledger_path=ledger_path)
    return LiveBroker(live=True)

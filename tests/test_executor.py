import json

import pytest

from polymarket_strategy.executor import (
    LiveBroker,
    LiveTradingNotConfirmed,
    PaperBroker,
    make_broker,
)


def test_paper_broker_fills_instantly_and_logs_ledger(tmp_path):
    ledger = tmp_path / "trades.jsonl"
    broker = PaperBroker(ledger_path=str(ledger))

    result = broker.place_order(token_id="tok-1", side="BUY", price=0.85, size=10.0)

    assert result.mode == "paper"
    assert result.status == "filled"
    assert result.order_id.startswith("paper-")

    lines = ledger.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["token_id"] == "tok-1"
    assert record["price"] == 0.85
    assert record["size"] == 10.0


def test_make_broker_defaults_to_paper(tmp_path):
    ledger = tmp_path / "trades.jsonl"
    broker = make_broker(live=False, ledger_path=str(ledger))
    assert isinstance(broker, PaperBroker)


def test_live_broker_refuses_without_live_flag(monkeypatch):
    monkeypatch.delenv("POLYMARKET_LIVE_TRADING", raising=False)
    monkeypatch.delenv("POLYMARKET_PRIVATE_KEY", raising=False)
    with pytest.raises(LiveTradingNotConfirmed, match="live=True was not passed"):
        LiveBroker(live=False)


def test_live_broker_refuses_without_env_flag(monkeypatch):
    monkeypatch.delenv("POLYMARKET_LIVE_TRADING", raising=False)
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "0xdeadbeef")
    with pytest.raises(LiveTradingNotConfirmed, match="POLYMARKET_LIVE_TRADING"):
        LiveBroker(live=True)


def test_live_broker_refuses_without_private_key(monkeypatch):
    monkeypatch.setenv("POLYMARKET_LIVE_TRADING", "true")
    monkeypatch.delenv("POLYMARKET_PRIVATE_KEY", raising=False)
    with pytest.raises(LiveTradingNotConfirmed, match="POLYMARKET_PRIVATE_KEY"):
        LiveBroker(live=True)


def test_make_broker_never_silently_downgrades_an_incomplete_live_request(monkeypatch):
    # Requesting live=True with an incomplete opt-in must raise, not quietly
    # hand back a PaperBroker -- an operator who typed --live must know their
    # order was NOT placed, rather than believe paper fills were real trades.
    monkeypatch.delenv("POLYMARKET_LIVE_TRADING", raising=False)
    monkeypatch.delenv("POLYMARKET_PRIVATE_KEY", raising=False)
    with pytest.raises(LiveTradingNotConfirmed):
        make_broker(live=True)


def test_live_broker_with_full_opt_in_but_missing_dependency_fails_loudly(monkeypatch):
    # All three gates satisfied, but py-clob-client isn't installed in this
    # environment -- must fail with a clear, actionable error, not a bare
    # ImportError or (worse) a silent no-op.
    monkeypatch.setenv("POLYMARKET_LIVE_TRADING", "true")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "0xdeadbeef")
    try:
        import py_clob_client  # noqa: F401

        pytest.skip("py-clob-client is installed in this environment; gating-only test not applicable")
    except ImportError:
        pass
    with pytest.raises(RuntimeError, match="py-clob-client"):
        LiveBroker(live=True)

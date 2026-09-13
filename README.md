# bot-test — Polymarket mispricing / EV / Kelly strategy bot

An implementation and honest backtest of the three formulas behind a
"copy-trading" pitch that circulated for a Polymarket wallet, claiming a
99.3% win rate and $805k P&L across 27,000 predictions, backed by a
"72 million transaction" backtest.

**Read this before trusting that pitch, or any bot claiming a near-100% win
rate with "no risk":** a real edge in a liquid market is real because it's
small — the moment it's large and easy, arbitrageurs compete it away.
"No risk, 99% win rate" describes a marketing funnel, not a trading
strategy: Kelly sizing (formula #3 in the pitch, correctly stated below)
exists specifically because *you can and will lose individual bets* — a
strategy with no losses doesn't need position sizing at all. This repo does
not connect to the wallet or copy-trading service linked in that pitch, and
does not recommend doing so based on unverifiable performance claims.

What this repo does instead: implement the three formulas as described,
correctly; run them through a real walk-forward, out-of-sample backtest so
any reported win rate is earned, not asserted; gate every trade through a
risk manager; and default to paper trading, with live trading requiring an
explicit, three-part opt-in on a dedicated wallet.

## ⚠️ On the "real tennis data" result

**This environment's egress policy blocks all of `*.polymarket.com`
(`gamma-api`, `clob`, `data-api`, `strapi-matic`, and the main site) with a
403 at the connection level** — confirmed directly, not assumed:

```
$ curl https://gamma-api.polymarket.com/markets
curl: (56) CONNECT tunnel failed, response 403
# proxy status confirms: "kind": "connect_rejected", "detail": "policy denial"
```

So **no claim below about a "real" Polymarket win rate is being made from
this session** — there is no real trade data fetched here, tennis or
otherwise, and it would be dishonest to present a number as "real" without
having actually pulled it. This is consistent with the original honest
finding in this repo: it does not manufacture the 99.3% figure, and it does
not manufacture a "real data" result it couldn't fetch either.

`scripts/fetch_polymarket_data.py` is fully implemented, including a
`--category tennis` filter (see below), and **you can run it yourself** from
any environment with normal internet access (a laptop, a GitHub Codespace,
a CI runner without this restriction):

```bash
pip install -r requirements.txt
python scripts/fetch_polymarket_data.py --out tennis_trades.csv --category tennis --n-markets 1000
python -m polymarket_strategy.cli walk-forward --csv tennis_trades.csv
```

That will print the real, empirically-measured win rate per price bucket and
the walk-forward, out-of-sample result — the actual verification this
project exists to do. Below, every number is clearly labeled as either
**real** (from the CSV you provide) or **synthetic** (a labeled stand-in used
so the engine is testable without network access).

## The three formulas

1. **Price-error correction** (`polymarket_strategy/pricing.py`)
   `delta = actual_win_rate - implied_probability`, computed empirically per
   price bucket (0-20¢, 20-50¢, 50-80¢, 80-95¢, 95-99¢, or any bucket width
   you choose) from resolved markets. A positive delta means contracts at
   that price resolved YES more often than the price implied.

2. **Expected value** (`polymarket_strategy/ev.py`)
   `EV = (P_win * Gain) - (P_loss * Cost)`, with `Gain = 1 - price` and
   `Cost = price` for a $1-payout share.

3. **Kelly criterion sizing** (`polymarket_strategy/kelly.py`)
   `f* = (p * b - q) / b`, with `b = (1 - price) / price`. The engine uses a
   fractional Kelly (default quarter-Kelly) since full Kelly assumes the
   win-probability estimate is exact, which it never is — and every stake is
   additionally clamped by the risk manager's hard cap regardless of what
   Kelly suggests (see below).

`polymarket_strategy/strategy.py` chains these: mispricing → EV → Kelly size
→ take/skip decision, restricted by default to the 0.80–0.99 price range the
pitch describes (configurable).

## Walk-forward backtest — no future information leaks into a decision

`polymarket_strategy/backtest.py` has two engines:

- `run_backtest`: a single chronological train/test split (fit calibration
  on the first half, trade the second half).
- `run_walk_forward_backtest`: **true walk-forward** with an expanding
  window across `n_folds` (default 5). Fold 1 trains on chunk 0 and trades
  chunk 1; fold 2 retrains on chunks 0–1 and trades chunk 2; and so on. Every
  fold's calibration curve is fit **only** on trades chronologically before
  that fold's test chunk — a fold never sees its own test data, or any data
  from the future, while fitting. Bankroll, drawdown, and risk-manager state
  (loss streaks, cooldowns, daily caps) carry forward continuously across
  fold boundaries, exactly as they would in live sequential trading.

Fitting and evaluating a calibration curve on the same data is a classic
backtest bug — it lets an "edge" be sampling noise the model memorized. Every
metric this engine reports comes from held-out, chronologically-later data.

Every trade's stake is capped by the risk manager's hard limit as a fraction
of the **starting** bankroll (not the compounded one) — real order books
have finite depth at a given price; without this cap, a real edge compounded
via Kelly across thousands of trades produces fantastical returns that
assume infinite liquidity and zero slippage, the same mechanism behind
implausible "turn $10 into a fortune" pitches.

## Risk manager (`polymarket_strategy/risk_manager.py`)

Independent of the pricing/EV/Kelly signal — decides whether a signal is
allowed to fire *at all* right now, on top of whatever the strategy wants:

- **Daily loss cap**: once a day's realized P&L drops below
  `-max_daily_loss_fraction * starting_bankroll` (default 5%), no more trades
  until the next day.
- **Loss-streak cooldown**: after `max_consecutive_losses` losses in a row
  (default 4), trading pauses for `cooldown_trades` subsequent candidate
  trades (default 5) — a streak carries across day boundaries deliberately;
  a bot on a 4-loss streak at 23:59 isn't suddenly trustworthy at 00:00.
- **Hard stake cap**: every stake is clamped to `hard_max_stake_fraction *
  starting_bankroll` (default 2%) regardless of what Kelly sizing (or a bug
  in it) suggests — the last line of defense against a sizing error blowing
  up the account on one trade.

`tests/test_risk_manager.py` proves all three independently (cap triggers
and resets, cooldown arms/counts down/clears, hard cap overrides an
oversized Kelly suggestion).

## Paper trading by default; live trading needs a triple opt-in

`polymarket_strategy/executor.py`:

- **`PaperBroker`** (default): simulates an instant fill at the quoted price
  and logs to a local JSON-lines ledger. Never touches the network to place
  an order.
- **`LiveBroker`**: places real orders via Polymarket's official
  `py-clob-client` (not reimplemented here — EIP-712 order signing is
  security-critical and best left to the maintained library). It refuses to
  even construct unless **all three** hold:
  1. The caller passes `live=True` — i.e., you ran `cli.py live`, never
     `cli.py paper` with a flag that silently escalates.
  2. Environment variable `POLYMARKET_LIVE_TRADING=true` is set.
  3. Environment variable `POLYMARKET_PRIVATE_KEY` is set — the signing key
     for a **dedicated trading wallet**, not one holding unrelated funds.

  Missing any one raises `LiveTradingNotConfirmed` rather than silently
  falling back to paper mode — so a misconfigured live run fails loudly
  instead of leaving you believing real orders were placed when none were.
  `tests/test_executor.py` proves each of the three gates independently, and
  that an incomplete `--live` request never silently downgrades to paper.

Live trading additionally requires `pip install -r requirements-live.txt`
(kept separate so paper trading and backtesting need no wallet-signing
dependency at all).

## Live/paper polling loop (`polymarket_strategy/live_loop.py`)

Polls currently open markets from Gamma API, applies a **pre-fit**
calibration curve (from a CSV you generated with the fetch script) through
EV + Kelly, routes every candidate through the risk manager, and places
orders via whichever broker `cli.py` constructed. `fetch_open_markets` is
the only network-touching function; `evaluate_market` and `run_once` — the
actual decision logic — are fully unit-tested with mocked markets and a fake
broker (`tests/test_live_loop.py`), independent of network access.

**Known gap, stated plainly**: this loop only handles entries. Feeding a
placed trade's real outcome back into the risk manager once its market
resolves (so the loss-streak/daily-cap breakers actually fire in live/paper
mode, not just in the backtest which knows outcomes immediately) requires a
settlement poller that isn't built yet. Don't rely on this loop's risk
wiring alone for real-money trading until that's added — the risk manager
itself is fully correct and tested; what's missing is *feeding it live
results*.

## Fetching real data, tennis-specific (`scripts/fetch_polymarket_data.py`)

For each closed market, this pairs a sample of the winning-or-losing
outcome token's historical prices with the market's actual final outcome —
exactly the (price, outcome) pairs the calibration curve needs. `--category`
filters client-side against tags/category/question/slug text (robust
regardless of which server-side tag-filter parameter Gamma API happens to
support at the time you run it):

```bash
python scripts/fetch_polymarket_data.py --out tennis_trades.csv --category tennis --n-markets 1000
```

Requires network access to `gamma-api.polymarket.com` and
`clob.polymarket.com` — blocked in this session (see above); run it from an
environment with normal internet access.

## Running it

```bash
pip install -r requirements.txt
pytest                                          # 48 tests: formula correctness, walk-forward
                                                 # bias-detection + zero-trade control, risk
                                                 # manager, live-trading gating, live-loop logic

python -m polymarket_strategy.cli backtest      # single-split, synthetic demo data
python -m polymarket_strategy.cli walk-forward  # walk-forward + risk manager, synthetic demo data
python -m polymarket_strategy.cli walk-forward --csv your_trades.csv --n-folds 5

python -m polymarket_strategy.cli paper --calibration-csv your_trades.csv --once
python -m polymarket_strategy.cli live  --calibration-csv your_trades.csv --once   # refuses without the triple opt-in
```

### Actual result, on labeled synthetic data (NOT a claim about real Polymarket)

`generate_synthetic_trades()` models a modest, realistic favorite-longshot
bias — a documented phenomenon where near-certain contracts are slightly
underpriced — capped at +6 percentage points at price≈0.99, zero below
price=0.50. Out-of-sample, **walk-forward** result (5 folds) on 40,000
synthetic trades, with the risk manager active (5% daily cap, cooldown after
4 consecutive losses, 2% hard stake cap):

```
[walk-forward, 5 folds] candidates=6437 taken=5174 wins=4793 losses=381
win_rate=92.64% avg_return_per_trade=3.60% total_pnl=$372.53 roi=372.53%
max_drawdown=8.31% skipped_by_risk_manager=10 ending_bankroll=$472.53
```

92.6%, not 99.3% — and that's on data engineered to contain a real, if
modest, edge. The control test
(`test_walk_forward_stays_at_zero_trades_with_exactly_calibrated_market`)
uses a **deterministic** (no RNG) dataset where every bucket's empirical win
rate equals its implied probability exactly, by construction, and asserts
the engine takes **exactly zero trades** — not "a low rate", zero — proving
it doesn't invent an edge that provably isn't there.
`test_walk_forward_detects_a_real_injected_bias_out_of_sample` injects a
known bias and asserts the engine finds it out-of-sample. Both are
walk-forward tests, not single-split, so the "no lookahead" guarantee is
what's actually being tested.

## Repo layout

```
polymarket_strategy/
  pricing.py       — formula 1: mispricing / calibration curve
  ev.py            — formula 2: expected value
  kelly.py         — formula 3: Kelly position sizing
  strategy.py      — combines the three into a signal
  backtest.py       — single-split AND walk-forward (expanding window) backtest engines
  risk_manager.py   — daily loss cap, loss-streak cooldown, hard stake cap
  executor.py       — PaperBroker (default) / LiveBroker (triple opt-in, py-clob-client)
  live_loop.py      — polls open markets, applies a pre-fit curve, routes through risk + broker
  cli.py            — unified entry point: backtest / walk-forward / paper / live
  data.py           — CSV loader for real trades + labeled synthetic generator
tests/              — formula correctness + backtest control tests + risk manager +
                       executor gating + live-loop logic (48 tests total)
scripts/
  run_backtest.py            — legacy single-split CLI (see cli.py for the unified one)
  fetch_polymarket_data.py   — pulls real resolved markets from Gamma/CLOB APIs,
                                 optional --category filter (e.g. tennis)
requirements.txt        — pytest only; backtesting/paper trading need nothing else
requirements-live.txt   — py-clob-client, only needed for `cli.py live`
```

## Known limits

- No live network access to Polymarket from this session (see above) — the
  fetch script, live polling loop, and live broker are implemented and unit
  tested with mocks, but have not been exercised against the real API from
  here. Run them yourself where you have normal internet access.
- The live/paper polling loop doesn't yet feed resolved-market outcomes back
  into the risk manager (see "Known gap" above) — entries are fully gated,
  exits/settlement tracking is not yet wired up.
- `LiveBroker` wraps `py-clob-client`'s order-placement calls as I understand
  its API; it has not been run against a funded live wallet. Test with a
  tiny position size on a dedicated wallet before trusting it with real
  capital, exactly as the triple opt-in is designed to force you to
  acknowledge.
- The calibration curve in `paper`/`live` mode is fit once, offline, from a
  CSV — there is no online recalibration loop. Refit periodically as new
  resolved markets accumulate.

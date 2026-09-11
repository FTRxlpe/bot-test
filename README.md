# bot-test — honest backtests of "guaranteed edge" trading-bot pitches

This repo takes hyped trading-bot pitches and tests them honestly instead of
trusting the marketing: implement the actual mechanism, backtest it
out-of-sample, and report the real number instead of the claimed one.

## Polymarket mispricing / EV / Kelly strategy backtest

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
correctly, and run them through a real out-of-sample backtest so the
reported win rate is earned, not asserted.

## The three formulas

1. **Price-error correction** (`polymarket_strategy/pricing.py`)
   `delta = actual_win_rate - implied_probability`, computed empirically per
   price bucket from resolved markets. A positive delta in a bucket means
   contracts at that price resolved YES more often than the price implied.

2. **Expected value** (`polymarket_strategy/ev.py`)
   `EV = (P_win * Gain) - (P_loss * Cost)`, with `Gain = 1 - price` and
   `Cost = price` for a $1-payout share.

3. **Kelly criterion sizing** (`polymarket_strategy/kelly.py`)
   `f* = (p * b - q) / b`, with `b = (1 - price) / price`. The engine uses a
   fractional Kelly (default quarter-Kelly) since full Kelly assumes the
   win-probability estimate is exact, which it never is.

`polymarket_strategy/strategy.py` chains these: mispricing → EV → Kelly size
→ take/skip decision, restricted by default to the 0.80–0.99 price range the
pitch describes.

## The backtest — and why the numbers here don't match the pitch

`polymarket_strategy/backtest.py` splits historical trades chronologically,
fits the calibration curve (formula #1) on the **train** half only, and
trades the **test** half using nothing but what the train half could have
told you at the time. This matters: fitting and evaluating a calibration
curve on the same data lets a strategy "discover" an edge that's really just
sampling noise it memorized — a well-known way to manufacture an inflated
backtest win rate. Every metric in the report below is out-of-sample.

Every trade's stake is also capped at a fraction of the *starting* bankroll
(`max_stake_fraction_of_starting_bankroll`, default 2%), not the
compounded one. Real order books have finite depth at a given price; without
this cap, a real edge compounded via Kelly across thousands of sequential
trades produces fantastical total returns that assume infinite liquidity and
zero slippage — the same mechanism behind implausible "turn $10 into a
fortune" pitches.

### Running it

```bash
pip install -r requirements.txt
pytest                                 # 21 tests: formula correctness + a control
                                        # test proving the engine finds ~no edge
                                        # in an efficient (unbiased) market

python scripts/run_backtest.py --n-synthetic 50000
```

This repo has no network access to Polymarket's API from this environment,
so there is no real historical trade data to backtest against here. To get a
real result, export your own resolved-market trade history to CSV
(`price,outcome[,market_id]`) and run:

```bash
python scripts/run_backtest.py --csv your_trades.csv
```

### Actual result, on labeled synthetic data (NOT a claim about real Polymarket)

`generate_synthetic_trades()` models a modest, realistic favorite-longshot
bias — a documented phenomenon where near-certain contracts are slightly
underpriced — capped at +5 percentage points at price=0.99, zero below
price=0.50. Out-of-sample result on 50,000 synthetic trades:

```
candidates=4817 taken=3674 wins=3435 losses=239
win_rate=93.49%  avg_return_per_trade=3.98%
total_pnl=$292.09  roi=292.09%  max_drawdown=10.75%
```

93.5%, not 99.3% — and that's on data engineered to contain a real,
if modest, edge. The included control test
(`test_backtest_on_efficient_market_finds_no_edge`) confirms the engine
takes almost no trades when prices ARE calibrated, i.e. it doesn't invent an
edge that isn't there.

### Repo layout (Polymarket module)

```
polymarket_strategy/
  pricing.py   — formula 1: mispricing / calibration curve
  ev.py        — formula 2: expected value
  kelly.py     — formula 3: Kelly position sizing
  strategy.py  — combines the three into a signal
  backtest.py  — out-of-sample backtest engine
  data.py      — CSV loader for real trades + labeled synthetic generator
tests/         — formula correctness tests + backtest control tests
scripts/run_backtest.py — CLI entry point
```

## BTC cross-market arbitrage bot backtest

A companion analysis for a different flavor of hyped pitch: a "BTC
arbitrage bot" that claims to scan 50+ markets, sync live Binance data every
second, and capture price errors across dozens of markets before humans can
react — framed as pure speed and pattern recognition, "no guessing, no
emotion, no hesitation."

That framing describes real cross-exchange arbitrage's *mechanism* honestly
(stale quotes on one exchange do create real, transient price gaps versus
faster exchanges), but omits the two things that actually determine whether
it's profitable: **execution latency** (a gap open at detection time can
close, or reverse, by the time both legs of the trade fill) and **round-trip
trading costs** (taker fees + slippage on two separate exchanges). This
module implements the same detect → calibrate → size decision chain as the
Polymarket module, but for cross-market BTC price gaps, and measures how much
of the theoretical edge latency and costs actually eat.

### The three formulas

1. **Gap detection** (`btc_arbitrage/pricing.py`) — at a synchronized
   snapshot of quotes across markets, `raw_gap = (max_price - min_price) /
   min_price`: the theoretical maximum capturable before costs or delay.
2. **Realized net edge** (`btc_arbitrage/execution.py`) — the gap actually
   available once you can act: the price difference at `now + latency_ms`
   (not at detection time), minus round-trip costs
   (`btc_arbitrage/costs.py`). A gap-size calibration curve
   (`btc_arbitrage/calibration.py`), fit only on the train split, buckets
   historical opportunities by their raw gap size and records how often they
   stayed net-positive after realistic execution.
3. **Kelly position sizing** (`btc_arbitrage/sizing.py`) — `f* = (p*b - q)/b`
   using each bucket's calibrated win rate and empirical win/loss
   magnitudes, at a fractional (quarter) Kelly discount, capped per trade at
   a fraction of the *starting* bankroll for the same reason as the
   Polymarket module: real order books have finite depth.

`btc_arbitrage/backtest.py` splits a snapshot history chronologically,
builds realized opportunities and fits the gap-size calibration curve on the
train half only, then trades the held-out test half using nothing the train
half couldn't have told you at the time — same out-of-sample discipline as
`polymarket_strategy/backtest.py`, for the same reason.

### Running it

```bash
python scripts/run_btc_backtest.py                    # synthetic demo data
python scripts/run_btc_backtest.py --csv quotes.csv    # real data (timestamp_ms,market,price)
```

This sandbox has no network access to Binance or any exchange API (outbound
requests to `api.binance.com` are rejected by the environment's network
policy), so there is no real multi-exchange quote history to backtest here.
`generate_synthetic_snapshots` in `btc_arbitrage/data.py` instead models a
shared BTC "true price" random walk plus occasional stale-quote lag on one
market at a time — the real physical mechanism behind cross-exchange price
gaps — rather than fabricating a "free money everywhere" edge. To get a real
result, export your own timestamped multi-exchange quotes to CSV
(`timestamp_ms,market,price`) and run with `--csv`.

### Actual result, on labeled synthetic data (NOT a claim about real exchange spreads)

Out-of-sample result on 200,000 synthetic ticks (~14 hours at 250ms), at
realistic costs (10bps taker fee + 5bps slippage per leg) and a 250ms
detect-and-execute latency:

```
snapshots=200000 candidates=99999 taken=2672
wins=1962 losses=710 win_rate=73.43% avg_return_per_trade=0.08%
total_pnl=$408.23 roi=4.08% max_drawdown=0.03%
```

A real, modest edge — not "no risk, wins every time." The included tests
show why it's fragile in exactly the ways the pitch glosses over:

- **No stale quotes, no edge**: with lag disabled (`lag_probability_per_step=0`,
  so markets only differ by unbiased microstructure noise), the strategy
  takes essentially nothing (`test_backtest_on_efficient_market_finds_no_edge`)
  — apparent gaps that are just noise don't clear real costs.
- **Latency kills it**: raising the same market's execution latency from
  250ms to 3s drives trades taken and total P&L to zero
  (`test_higher_latency_erodes_the_edge`) — the entire edge depends on being
  fast, exactly as "speed is the edge" implies, but the pitch presents that
  as an advantage rather than a fragility.
- **Realistic costs shrink total profit**: the same market at 0 bps costs
  vs. realistic (10+5 bps) costs shows real fees meaningfully cutting into
  total realized profit (`test_realistic_costs_can_erase_edge_that_exists_at_zero_cost`).

### Repo layout (BTC arbitrage module)

```
btc_arbitrage/
  pricing.py     — formula 1: cross-market gap detection
  costs.py       — round-trip fee + slippage model
  execution.py   — formula 2: realized net edge after latency + costs
  calibration.py — gap-size calibration curve (train-only)
  sizing.py      — formula 3: Kelly position sizing
  strategy.py    — strategy configuration
  backtest.py    — out-of-sample backtest engine
  data.py        — CSV loader for real quotes + labeled synthetic generator
tests/                        — formula correctness tests + backtest control tests
scripts/run_btc_backtest.py — CLI entry point
```

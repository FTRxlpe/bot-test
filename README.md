# bot-test — Polymarket mispricing / EV / Kelly strategy backtest

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

## Repo layout

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

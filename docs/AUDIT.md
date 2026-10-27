# Lunch Money / "Espero" — an honest audit

> The origin story of this repo. The harness described at the end is `espero/`; the plan in §6 is the
> roadmap in the README.

**Repo:** `7ucky7/lunch-money-trading-bot` · **Audited:** 2026-10-26 · **Size:** 12,169 lines of Python, 26 files, 61 classes, 2 commits · **Last commit:** 2025-03-14 (18 months ago)

---

## The verdict in one paragraph

The ideas in this repo are not outdated. A 20/50 MA cross, RSI, Bollinger and MACD are as valid in
2026 as they were in 1990 — nobody in Shenzhen or anywhere else has repealed mean reversion. What is
outdated is everything around the signal: the exchange connection, the execution path, the
backtester's fill model, the state handling, the tests. And it is worse than "outdated" — **the
system does not run.** The live path has no exchange client wired into it at all. Both CLIs call
methods that do not exist. The one file that does know how to place an order talks to an API that
Coinbase shut down in 2023. There are no trading results to be behind on, because no trade has ever
been placed by this code.

That is the honest version. The rest of this document is the evidence, a measurement of what your
own strategy looks like once the bugs are removed, where the 2026 bar actually sits, and a 30-day
path that gets you from here to something that can run with real money.

---

## 1. What is actually in the box

| Claim (README) | Reality |
|---|---|
| "Real-Time Data Streaming: WebSocket connections" | Connects to `wss://ws-feed.pro.coinbase.com` — the legacy Pro feed, retired with Coinbase Pro on 2023-12-01 |
| "Live Trading Mode" | `trading_bot.py` never imports an exchange client. It creates a `Position` object in RAM and logs it |
| "Backtesting Engine" | Two of them (`backtest.py`, `backtesting.py`), both unusable — see §2.2 |
| "Risk Management" | `risk_manager.py` (692 LOC) is never loaded by the live or paper bot |
| "ML Strategy (LSTM, RF, GBM)" | Trains on the full series without a split or CV; scaler fitted on all data |
| "MIT License — see the LICENSE file" | There is no LICENSE file |
| Install via `pip install -r requirements.txt` | `cbpro`, `requests`, `ta`, `schedule`, `coinbase_advanced_py` are imported but not listed; `ccxt` is listed but never imported |

Two commits, both on 2025-03-14, two hours apart: an "Initial commit" and then 12,136 inserted lines.
That is not a criticism of the work — it is an explanation of the shape. This is a generated
scaffold that was never executed end-to-end, so nothing ever had the chance to fail in front of you.

Three different bots are stacked in one repo:

- `lunch_money_bot.py` — a 320-line grid bot (the repo's namesake)
- `trading_bot.py` + `strategy_framework.py` + `example_strategies.py` — the "Espero" signal bot (the README)
- `advanced_trading_bot.py` — a 749-line standalone cbpro loop that duplicates the first two

Plus a parallel universe: `strategy.py` defines its own `Signal`, `SignalType` and `Strategy` classes
that are incompatible with `strategy_framework.py`'s versions of the same names. `backtest.py` uses
one universe, `backtesting.py` uses the other. Neither knows the other exists.

**Static import graph of the two Espero entry points** (`trading_bot.py`, `backtesting.py` — there
are four CLIs in total: those two plus `lunch_money_bot.py` and `advanced_trading_bot.py`):

```
trading_bot.py    -> data_manager, example_strategies, ml_strategy, order_validator,
                     position_manager, strategy_framework
backtesting.py    -> data_manager, example_strategies, ml_strategy, position_manager,
                     strategy_framework
```

Never imported by either: `api_client.py`, `order_manager.py`, `order_executor.py`,
`risk_manager.py`, `shutdown_manager.py`, `paper_trading.py`, `config.py`, `logger.py`.
That is **4,088 lines — 34% of the repo — that the running system never sees.** The risk manager,
the order manager, the retry/rate-limit layer and the graceful-shutdown handler are all in that list.

---

## 2. The five findings that matter

### 2.1 `--live` cannot place an order

`trading_bot.py::_execute_trade`, the only place a live order would originate:

```python
# Use normalized size from validation
position_size = validation_result.modified_params.get('size', position_size)

# Create position
position = self.position_manager.create_position(
    product_id=product_id,
    entry_price=current_price,
    ...
)
logger.info(f"Created LONG position: {position.id} for {product_id} at {current_price} "
            f"with size {position_size:.6f}")
```

`create_position` is an in-memory dataclass constructor. There is no `place_order`, no HTTP call, no
exchange client in the import list. If you had ever run `--live` with valid keys, the log would say
"Created LONG position" and your Coinbase balance would be exactly unchanged. That is the single
most dangerous failure mode a trading bot can have: it *looks* like it is trading.

Worse, it would crash before that. The price lookup it does first is:

```python
current_price = await self.data_manager.get_current_price(product_id)
```

`DataManager` has `get_latest_price`, not `get_current_price`. `AttributeError`, every time.

### 2.2 32 call sites into methods that do not exist

I built the object graph and checked every `self.x.method()` against the class actually assigned to
`self.x`. These are not style issues; they are `AttributeError` at runtime:

| Call site | Target | Actual name |
|---|---|---|
| `trading_bot.py:220` | `data_manager.fetch_historical_data` | `fetch_historical_candles` |
| `trading_bot.py:327` | `data_manager.get_candles_df` | `to_dataframe` |
| `trading_bot.py:270,401` | `data_manager.get_current_price` | `get_latest_price` |
| `trading_bot.py:392` | `data_manager.get_account_balance` | *does not exist* |
| `trading_bot.py:138` | `data_manager.get_product_rules` | *does not exist* |
| `trading_bot.py:148-149` | `register_candle_callback` / `register_trade_callback` | `register_callback` |
| `trading_bot.py:213` | `data_manager.subscribe_to_products` | `start(product_ids)` |
| `trading_bot.py:166-187` | `strategy_registry.register` | `register_strategy` |
| `trading_bot.py:274,410` | `position_manager.get_positions_by_product` | `get_positions(product_id=...)` |
| `trading_bot.py:304` | `position_manager.get_positions_by_status` | `get_positions(status=...)` |
| `backtesting.py:415,470,583,597` | `fetch_historical_data`, `get_candles_df`, `get_candle_for_date` | none exist |
| `backtesting.py:347-368` | `strategy_registry.register` | `register_strategy` |
| `trading_bot.py:122` | `DataManager(..., environment=)` | constructor takes only `api_key, api_secret` |

The pattern is the tell: `initialize()` in `trading_bot.py` is a wall of method names that read like
a plausible API — `get_product_rules`, `get_account_balance`, `close()` — none of which were ever
implemented on the class they are called on.

It is even simpler than that. Line 122 is the first real statement of `initialize()`:

```python
self.data_manager = DataManager(
    api_key=..., api_secret=..., environment=self.config.get('environment', 'sandbox')
)
```

`DataManager.__init__(self, api_key, api_secret)` takes two arguments. The `environment=` keyword
raises `TypeError` immediately, in **both** `--paper` and `--live` mode, before a single network
call. Combined with the 32 unresolved call sites behind it, there is no evidence in the repo that
any entry point has ever executed past its first few lines.

### 2.3 The only real order path points at a dead API

`advanced_trading_bot.py:427` really does call `self.auth_client.place_limit_order(...)` — via
`cbpro`. The facts:

- **Coinbase Pro was disabled for customers on 2023-12-01**; Pro API keys cannot be used with
  Advanced Trade, the keys must be regenerated. ([Coinbase Advanced Trade FAQ](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/faq.md))
- **`cbpro` last released 2018-09-06** (PyPI). It is an 8-year-old client for a dead venue.
- `api_client.py` and `data_manager.py` still call `https://api.pro.coinbase.com/products/{id}/candles`
  and `wss://ws-feed.pro.coinbase.com`.
- Amusingly, `config.py` — the module nothing imports — has the correct modern URL
  (`https://api.exchange.coinbase.com`) and the correct fee constants (0.6% taker / 0.4% maker).

The repo was committed on **2025-03-14** — fifteen months after the API it trades against was
disabled. So the repository knows the right answers in a file it never loads, and uses the wrong
ones in the files it does.

### 2.4 The backtester leaks one bar, and that bar is the entire P&L

This is the finding with money attached. In `backtesting.py::_process_day`:

```python
df_filtered = df[pd.to_datetime(df["time"]) <= date]   # data up to and including today's close
...
signals = await strategy.generate_signals(market_data, product_id)   # signal from today's close
...
await self._process_signal(combined_signal, daily_candle)
```

and in `_process_signal`:

```python
open_price = float(candle['open'])
# Use open price for trade execution (assuming we trade at the open of the day)
execution_price = open_price
```

The signal is computed from **today's close** and filled at **today's open**. Every buy gets to buy
the morning after seeing the evening. On a daily bar that is a guaranteed peek at the future, and it
is worth tens of percentage points of fake return (§3).

There are three more realism gaps stacked on top:

1. **Fees.** `config.json` uses `fee_rate: 0.001` (10 bps/side). The repo's own `config.py` says
   taker is 0.006 — 6× higher. At 60 bps a side that is 1.2% round trip: 40 trades turn over ~48%
   of your notional in fees before you are right once.
2. **Position sizing.** `account_balance * risk_per_trade * confidence_factor` = ~2% of equity
   *notional* per trade, with a 5% stop. That risks 0.1% of the account per trade. Over four years
   the equity curve is a flat line that fees slowly eat (§3, rows 1–4).
3. **Intrabar sequencing.** Stop and target are both checked against the same bar's high/low with
   the stop always first, and gaps through the stop fill *at* the stop price rather than at the open.
   This one is conservative, but it is still a model, not a fill.

### 2.5 There are no tests, in the sense CI needs

Five `test_*.py` files, 13 `def test_` functions, all manual scripts run as `python test_x.py`,
printing `All tests passed!`. `test_data_manager.py` contains zero test functions. Nothing is
pytest-collectable, there is no CI, no Dockerfile, no `pyproject.toml`, no coverage, no fixtures.
`test_order_executor.py` builds an `OrderExecutor` from `dummy_key`/`dummy_secret` pointing at the
live Coinbase URL, guarded by an `execute_real_orders = False` flag a few lines below.

For contrast: the tests in `tests/test_timing.py` fail loudly when the fill rule is wrong. That is the difference between a test and a demo.

---

## 3. What your strategy actually does (measured)

I could not run your backtester — it calls methods that do not exist (§2.2). So I reimplemented what
it intends: the four strategies from `example_strategies.py`, the weighted `SignalCombiner` with
0.6 consensus and 0.65 min-confidence, single long position, 5% stop / 10% target, the same exit rule
(`in profit or confidence > 0.8`), on 4 years of real BTC-USD daily candles from Coinbase's public
API (2022-10-28 → 2026-10-27). Then I changed exactly one thing: **when the fill happens.**

![Equity curves](equity.png)

| Case | Return | CAGR | Sharpe | Max DD | Trades | Win % |
|---|---|---|---|---|---|---|
| as coded, 2% notional sizing, 10 bps | **−0.15%** | −0.04% | −0.48 | −0.24% | 11 | 18% |
| honest timing, 2% notional sizing, 10 bps | +0.05% | +0.01% | 0.33 | −0.06% | 7 | 29% |
| as coded, 100% sizing, 10 bps | **+42.95%** | +9.34% | 0.52 | −42.7% | 43 | 51% |
| honest timing, 100% sizing, 10 bps | **+5.23%** | +1.28% | 0.17 | −39.4% | 40 | 45% |
| honest timing, 100% sizing, **60 bps** | **−29.07%** | −8.23% | −0.28 | −50.7% | 40 | 40% |
| buy & hold BTC | **+289.1%** | +40.45% | — | — | 1 | — |

Same signals. Same strategy code. The only differences are the fill rule and the fee assumption.

Read it in three steps:

1. **The look-ahead is the alpha.** 42.95% becomes 5.23% when you move the fill from today's open to
   tomorrow's open. A single bar of hindsight is worth 38 percentage points over four years.
2. **Real fees turn a small win into a real loss.** 5.23% becomes −29.07% at 60 bps. Your own
   `config.py` says 60 bps is the taker rate; `config.json` says 10.
3. **At your configured size, none of it matters.** 2% notional per trade means the bot's P&L is
   rounding error in both directions. You built a machine with a 0.1%-of-equity risk unit and then
   judged it on a chart it cannot move.

And on ETH-USD over the same window the same stack returns **−21.5% as coded** and **−45.9% honest
with real fees**, against +49.5% for holding. So the +43% above is not a strategy edge; it is one
lucky regime plus one bar of cheating.

Two caveats, stated plainly: this is a reconstruction of intent, not byte-identical execution of
your code (yours cannot execute), and it uses daily bars only — the 1h/4h timeframes in your config
would change the trade count, not the sign of these effects. The harness is this repo's `espero/`
package, so you can challenge any number in this table by changing one parameter and re-running.

---

## 4. Where the bar actually is

I am reading "Shenzen" as **Shenzhen** — the 深圳 retail/prop quant stack, and more usefully the
2026 open-source bar globally. If you meant a specific person or repo by that name, tell me and I
will re-aim; the plumbing gap below is the same shape either way.

The Shenzhen/CN stack people mean when they say "what they're doing there" is roughly: **Futu OpenD**
(a local gateway daemon that gives you a real trading session, order callbacks and reconciliation),
**vn.py** (46k stars, gateways for CTP/XTP/Tora/futu, the default Chinese answer for futures),
**QMT / PTrade** (broker-issued Python terminals with real account APIs), **TqSdk** (tick-level
futures data and trading in one SDK), **akshare/tushare** (data), and in crypto, Hummingbot-style
market-making desks. The global equivalents are **NautilusTrader** (Rust core, 31k stars),
**Hummingbot** (21k), **Freqtrade** (56k), **Jesse**, and **LEAN**.

What all of them share is not a better indicator. It is this:

| Dimension | What the 2026 bar does | What this repo does |
|---|---|---|
| **Broker link** | Authenticated session, typed order objects, ack + fill events, cancel/replace, reconnect with backoff | None on the live path; `cbpro` on a dead venue in the one file that has it |
| **Order identity** | `client_order_id` generated before send, persisted, used to dedupe on retry | No idempotency key anywhere; a retry is a second order |
| **Market data** | Exchange-timestamped ticks/L2, gap detection, replayable to the millisecond, stored in Parquet | Candles assembled in RAM from a retired WS feed, no timestamps from the venue, no gap check |
| **Backtest** | Next-tick/next-bar fills, queue position, latency model, fee tier from your account, funding, walk-forward | Same-bar look-ahead, flat 10 bps, no funding, no walk-forward |
| **Risk** | Pre-trade gate on every order: notional, exposure, daily loss, consecutive losses, kill switch; enforced *below* the strategy, not inside it | `OrderValidator` exists but is unreachable from the live path; `risk_manager.py` is dead code |
| **State** | Append-only journal (SQLite/Postgres), restart-safe, reconcile against the exchange on boot | A `positions.json` written on demand and loaded at startup, never reconciled against the exchange |
| **Ops** | Docker, health endpoint, Prometheus metrics, alert on missed heartbeat, secrets from env/manager | `logging.FileHandler`, keys in `config.json` |
| **Research hygiene** | Purged CV, deflated Sharpe, ≥100 trades before believing anything | LSTM trained on the whole series, scaler fitted on all data, 43 trades in 4 years |
| **Tests** | Deterministic, offline, assert the fill rule and the fee math, run in CI on every push | Five scripts that print "All tests passed" |

The uncomfortable scale check: **NautilusTrader is ~31k stars, Freqtrade ~56k, vn.py ~46k — and each
of them is one coherent system.** This repo is 12k lines spread across three systems that do not
import each other. Nobody there is beating you on RSI parameters. They are beating you because
their bot can survive a websocket disconnect at 3am with a position open, and yours cannot survive
`initialize()`.

---

## 5. Three ways to get there

### Option A — Port the strategy into Freqtrade (recommended if the goal is *running* something)

**Effort:** ~1 weekend. **What you keep:** the ideas, the indicator code, the config. **What you
delete:** everything else.

Freqtrade gives you, for free and tested: ccxt (including `coinbaseadvanced`), dry-run that shares
the exact code path with live, backtesting with correct next-candle fills, fee handling per exchange,
SQLite persistence, Telegram control, Docker, hyperopt, FreqAI, and a test suite that runs on every push.

You write one file:

```python
class Espero(IStrategy):
    timeframe = "1h"
    stoploss = -0.05
    trailing_stop = True

    def populate_indicators(self, df, metadata):
        df["sma20"] = ta.SMA(df, 20); df["sma50"] = ta.SMA(df, 50)
        df["rsi"] = ta.RSI(df, 14)
        return df

    def populate_entry_trend(self, df, metadata):
        df.loc[(df.sma20 > df.sma50) & (df.rsi < 60), "enter_long"] = 1
        return df

    def populate_exit_trend(self, df, metadata):
        df.loc[df.sma20 < df.sma50, "exit_long"] = 1
        return df
```

Then `freqtrade backtesting --strategy Espero --timerange 20221028-20261027` gives you a number you
can trust, and `freqtrade trade --dry-run` gives you a bot that actually runs. Your first real
deliverable in 48 hours instead of a 30-day rewrite.

**Choose this if:** you want to know whether the strategy has an edge, and you want a bot running
this month.

### Option B — NautilusTrader (if tick-level or multi-venue is the actual goal)

**Effort:** 2–4 weeks of learning curve. Rust core, nanosecond timestamps, event-driven, and — the
important property — **the same `Strategy` code runs in backtest and live**, so "it worked in
backtest" means something. Adapters for Binance/Bybit/Coinbase/Databento, L2 order book, replay.

**Choose this if:** you intend to do intraday/tick work, market making, or anything where latency
and queue position matter. Overkill for a daily MA cross.

### Option C — Keep your own code and rebuild the core (if you are doing this to learn)

**Effort:** 3–6 weeks, and you must accept deleting ~80% of the repo. The target is eight modules,
each with one job:

```
espero/
  config.py      # typed settings from env + TOML, no secrets in git
  broker.py      # interface: place/cancel/fetch; PaperBroker and CoinbaseBroker
  data.py        # WS ingest, Parquet store, gap check, replay
  risk.py        # pre-trade gate + kill switch, called by the engine, not the strategy
  journal.py     # SQLite: intents, acks, fills, positions, equity snapshots
  engine.py      # one loop: bars -> signals -> risk -> orders -> fills -> reconcile
  backtest.py    # same engine, simulated broker, next-bar fills
  cli.py         # `espero backtest|paper|live|doctor`
```

The rule that makes it work: **the strategy emits `Signal` objects and nothing else.** It cannot
call the exchange, cannot size a position, cannot read the account. Everything that can lose money
lives below it and is testable without a network.

**Choose this if:** the bot is the learning project, not the business.

---

## 6. If you go with C: the 30-day plan

| Phase | Days | Deliverable | Acceptance criteria (binary, not vibes) |
|---|---|---|---|
| **0. Freeze** | 1 | `git tag v1-archive`; move `advanced_trading_bot.py`, `lunch_money_bot.py`, `order_manager.py`, `order_executor.py`, `backtest.py`, `strategy.py`, `hybrid_model.py` into `attic/` | One `Signal`/`Strategy` definition in the tree; `pytest -q` green on the kept modules |
| **1. Honest backtest** | 2–5 | `backtest.py` + cached candle data + fee/slippage model | A unit test asserts `entry_bar > signal_bar` and fails if you reintroduce the bug; re-running reproduces §3 to within 0.5pp; fees in the report equal `fee_rate × (entry_notional + exit_notional)` |
| **2. Paper trader** | 6–12 | WS ingest, SQLite journal, `client_order_id`, restart-safe | 72h continuous; `kill -9` mid-position then restart → reconciles, zero duplicate orders; journal vs exchange diff = 0 |
| **3. Micro-live** | 13–20 | Real broker, $50–100 cap, one product, kill switch at −2%/day | 2 weeks; exchange balance == journal to the cent; a TCA report comparing your fill price to the mid at signal time |
| **4. Research** | 21–30 | Purged walk-forward, ≥200 trades per configuration, deflated Sharpe | Strategy beats buy & hold net of your *actual* fee tier out-of-sample — or you shelve it and keep the infrastructure |

The order matters. Most people do 3 before 1 and donate money to the exchange to learn what a
look-ahead bug looks like.

---

## 7. What to keep, what to put in `attic/`

**Keep and port (real work lives here):**
- `example_strategies.py` — the indicator plumbing and confidence formulas are a fine starting point
- `position_manager.py` — the P&L math and `to_dict`/`from_dict` are salvageable
- `order_validator.py` — min-size and balance checks are the seed of a real risk gate
- `paper_trading.py` — the limit/market fill model is a reasonable primitive (drop the random fill-probability gate)
- `config.py` — it has the correct modern URL and the correct fee constants; it should have been the base

**Put in `attic/` (do not delete, do not maintain):**
- `advanced_trading_bot.py` — dead venue, duplicate logic
- `lunch_money_bot.py` — a different bot; keep as an example, not as the product
- `order_manager.py`, `order_executor.py`, `api_client.py` — 2,028 lines of cbpro-era machinery
- `backtest.py` — the second, incompatible backtester
- `strategy.py` — the duplicate framework
- `hybrid_model.py` + `ml_strategy.py` — the LSTM trains on the full series with the scaler fitted
  on all data; if you want ML, do it on tabular features with purged CV (`sklearn` +
  `TimeSeriesSplit(gap=...)`), not an LSTM over raw closes

**One of the three bots.** Not two, not three. The parallelism is what made 12k lines unmaintainable
by one person.

---

## 8. The part no rewrite fixes

Infrastructure gets you to "the bot does what I told it to." It cannot get you to "what I told it to
do makes money." Some numbers to sit with:

- **43 trades in 4 years.** That is ~1/month. You cannot distinguish a 5% edge from noise at that
  sample size; you need 100–200 round trips minimum, which at this frequency is 8–15 years of data.
- **Round trip costs at 60 bps/side = 1.2% of notional.** A daily MA cross has historically captured
  ~0.1–0.3% per signal. The fee is larger than the edge. This is why the whole table in §3 is
  negative at realistic fees — and why the venue decision (Coinbase taker vs. Binance/Bybit maker
  rebates vs. a perp venue) matters more than the indicator choice.
- **The only configuration that made money was the one with hindsight.** That is the definition of
  a backtest artifact.
- **Buy & hold returned 289%; every honest variant returned between +5% and −29%.** Before adding
  another strategy, ask what the bot is supposed to do that holding does not.

If it were mine: I would spend the weekend on Option A, run the strategy through Freqtrade's honest
backtester, and expect to discover there is no edge. That is a *useful* discovery — it costs one
weekend instead of a year of donations to Coinbase. Then I would spend the next month on the
infrastructure that lets me test ten ideas honestly, because that is the thing that compounds.

---

## Appendix — reproducing every number here

```bash
pip install -e ".[chart]"
espero fetch BTC-USD --days 1460             # public Coinbase candles, no key needed
espero matrix                                # the table in §3
espero chart                                 # -> docs/equity.png
python -m unittest discover -s tests -v      # 17 tests: timing, gaps, fees, causality, numbers
```

`espero/backtest.py` is a ~260-line reference backtester: causal indicators, next-bar fills,
per-side fees, slippage, stop-before-target with gap handling. `tests/test_timing.py` asserts the
property your backtester lacked — that a fill happens strictly after the signal — and
`tests/test_reference.py` pins every figure in §3 to the committed dataset. Use it to check any
claim here, or as the seed for Phase 1.

Data: Coinbase Exchange public `/candles`, 1,461 daily bars, committed under `data/` so the numbers
reproduce offline. The API is unauthenticated and the endpoint is live; the ones the original repo
calls are not.

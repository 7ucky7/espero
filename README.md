# espero

A small, honest crypto research harness: causal indicators, next-bar fills, and tests that fail
the moment you cheat.

## Why this exists

I inherited a 12,000-line trading bot. It looked complete — data layer, risk manager, order manager,
ML ensemble, paper trading. It had never placed a trade. The live path had no exchange client wired
into it, both entry points called methods that didn't exist, the only real order code talked to an
API Coinbase shut down in 2023, and the backtester filled at the *open* of the bar whose *close*
produced the signal.

That last bug was worth 38 percentage points of imaginary return. ([Full audit](docs/AUDIT.md).)

This repo is what was left after deleting everything that couldn't be trusted: one honest backtest
loop, four strategies, and a test suite whose job is to make the same mistakes impossible.

## What it does

- **Causal indicators** — 20/50 SMA, RSI(14), Bollinger(20, 2σ), MACD(12, 26, 9), all computed from
  past data only, with a test that proves it by recomputing every value on a truncated series.
- **Two execution models** — `next_bar` (signal at close *i*, fill at open *i+1*) and `same_bar`
  (the original bug), so the size of the look-ahead is measurable instead of assumed.
- **Costs that bite** — per-side fees and slippage from the command line; gaps through the stop fill
  at the open, not at the stop.
- **Numbers pinned in CI** — `tests/test_reference.py` asserts the audit's published figures against
  the committed dataset. Change the engine, and the claims break loudly.
- **Paper trading with a spine** — `espero paper` runs the same signal code against live Coinbase
  candles, fills on the next bar's open (never the bar that produced the signal), writes every
  signal/order/fill/equity mark to SQLite, and resumes the open position after a restart. A risk
  gate sits under the strategy: max 25% of equity per position, 1% risk per trade, daily loss cap.

## Live trading — off by default, and paranoid when on

`espero live` connects to a real Coinbase Advanced account and can place real orders. Four things
must all be true before a single order leaves the process:

1. `.env` contains a CDP key pair (never commit it — `.env` is gitignored)
2. `ESPERO_ALLOW_LIVE=1` is set
3. `--confirm-live` is passed
4. no `KILL` file exists in the working directory

Without `--confirm-live` the bot runs as a **dry run**: it reads your real balance and price, decides
what it *would* do, and logs it. Orders are also hard-capped by `--max-notional` (default $25) and the
process halts itself for the day at `--max-daily-loss` (default $15). Every order carries a
`client_order_id` generated before the call, so a retry is deduplicated instead of doubling.

```bash
cp .env.example .env      # fill in COINBASE_API_KEY and COINBASE_API_SECRET (or _SECRET_FILE)
espero live               # dry run: reads the account, sends nothing
espero live --loop --interval 60

# only after the dry run looks right, and only if you can afford to lose it:
ESPERO_ALLOW_LIVE=1 espero live --confirm-live --max-notional 25 --max-daily-loss 15
touch KILL                # stops the loop on its next pass
```

Honest limits of this version: stops are **software** stops checked once per bar, not exchange-side
orders — if the process dies, the stop dies with it. There is no reconciliation against the venue
yet, no partial-fill handling, and no funding. Fills are market orders at bar close, not the next
bar's open the backtest assumes; the journal records both so the difference is measurable.

## What it does not do (yet)

No reconciliation against a venue on boot, no exchange-side stop orders, no funding, no partial
fills. That is deliberate: those belong *below* the strategy layer, and the roadmap adds them with
tests instead of adding them as decoration. See [Roadmap](#roadmap).

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[chart]"          # numpy + pandas (+ Pillow for charts)

espero matrix                      # the audit table on the committed BTC-USD data
espero backtest --fee-bps 60       # one configuration, honest fills
espero chart                       # docs/equity.png
espero paper                       # one step of paper trading on live candles
espero paper --loop --interval 60  # keep it running (ctrl-c to stop)

espero fetch ETH-USD --days 1460   # fresh data, no API key needed
espero matrix data/ETHUSD_86400s.csv
```

Run the tests:

```bash
python -m unittest discover -s tests -v
```

Or run the whole CI job locally — the same steps as `.github/workflows/ci.yml`, no hosted runner
needed:

```bash
./scripts/check.sh --install     # first time
./scripts/check.sh               # tests + audit table + CLI smoke test

./scripts/install-hooks.sh       # optional: run the checks on every git push
```

## The numbers

BTC-USD, 2022-10-28 → 2026-10-27, 1,461 daily bars, $10,000, one long position.

| Case | Return | CAGR | Sharpe | Max DD | Trades |
|---|---|---|---|---|---|
| as coded (look-ahead), 2% notional, 10 bps | −0.15% | −0.04% | −0.48 | −0.24% | 11 |
| honest, 2% notional, 10 bps | +0.05% | +0.01% | 0.33 | −0.06% | 7 |
| as coded (look-ahead), full size, 10 bps | **+42.95%** | +9.34% | 0.52 | −42.7% | 43 |
| honest, full size, 10 bps | **+5.23%** | +1.28% | 0.17 | −39.4% | 40 |
| honest, full size, **60 bps** | **−29.07%** | −8.23% | −0.28 | −50.7% | 40 |
| buy & hold | **+289.08%** | +40.45% | — | — | — |

![Equity curves](docs/equity.png)

Same signals every row. The only things that change are when the fill happens and what it costs.

## Design rules

1. **A strategy emits `Signal` objects and nothing else.** It cannot size a position, read the
   account, or call a broker. Everything that can lose money sits below it and is testable offline.
2. **A fill happens after the signal.** There is a test for this, and a second test that pins the
   difference between honest and cheating.
3. **Costs are explicit.** Fee per side, in basis points, on the command line. No hidden 10 bps.
4. **Gaps are real.** If the bar opens through your stop, you get the open.
5. **The published numbers are a test fixture.** If they move, one of us is wrong.

## Layout

```
espero/
  espero/
    data.py         # Coinbase Exchange candles (public), CSV cache
    indicators.py   # causal SMAs, RSI, Bollinger, MACD
    signals.py      # four strategies + weighted combiner (pure functions)
    backtest.py     # one position, one bar at a time, two fill models
    journal.py      # SQLite: bars, signals, orders, positions, equity
    risk.py         # pre-trade gate: size, exposure, daily loss cap
    paper.py        # simulated loop: closed bar -> signal -> next-bar fill -> journal
    broker.py       # Broker protocol, Coinbase Advanced adapter, DryRun wrapper
    live.py         # real orders, capped and gated, same signals
    report.py       # the matrix table and the equity chart
    cli.py          # fetch | backtest | matrix | chart | paper
  tests/            # 38 tests: timing, gaps, fees, causality, restart, risk gate, live caps
  data/             # committed BTC/ETH daily candles so the numbers reproduce offline
  docs/AUDIT.md     # the audit that started this
```

## Roadmap

- [x] Causal indicators + honest backtester + reference tests
- [ ] Walk-forward split with a purge gap; report out-of-sample only
- [ ] Position sizing as risk (stop distance × account), not notional
- [x] SQLite journal: bars, signals, orders, fills, positions, equity
- [x] Restart-safe paper trader on live candles, with a pre-trade risk gate
- [x] Broker interface behind one protocol, with `client_order_id` idempotency
- [x] Live path with dry-run, kill switch, notional cap and daily loss limit
- [ ] Reconciliation against a real venue on boot
- [ ] Exchange-side stop orders (so the stop survives a crash)
- [ ] Kill switch: daily loss cap, max open risk, max orders/minute
- [ ] TCA report: fill vs mid at signal time
- [ ] Docker + health endpoint

The gate for live money is not "it backtests well". It is: two weeks of paper at zero duplicate
orders, a restart mid-position that reconciles to the cent, and out-of-sample results that survive
your actual fee tier.

## Docs

- [docs/AUDIT.md](docs/AUDIT.md) — the original audit: what was broken, how it was measured, and the
  30-day plan this project is executing.

## License

MIT. Research and education only. Not financial advice; this software can lose money, and the
default configuration will.

Closes nothing automatically, promises nothing, and has no opinion about what happens next.

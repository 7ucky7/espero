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

## What it does not do (yet)

No live trading. No broker connection. No order management, no reconciliation, no persistence.
That is deliberate: those belong *below* the strategy layer, and the roadmap adds them with tests
instead of adding them as decoration. See [Roadmap](#roadmap).

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[chart]"          # numpy + pandas (+ Pillow for charts)

espero matrix                      # the audit table on the committed BTC-USD data
espero backtest --fee-bps 60       # one configuration, honest fills
espero chart                       # docs/equity.png

espero fetch ETH-USD --days 1460   # fresh data, no API key needed
espero matrix data/ETHUSD_86400s.csv
```

Run the tests:

```bash
python -m unittest discover -s tests -v
```

Or run the whole CI job locally — the same steps as `.github/workflows/ci.yml`, no Actions minutes
needed (private repos draw on a paid quota):

```bash
./scripts/check.sh --install     # first time
./scripts/check.sh               # tests + audit table + CLI smoke test
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
    report.py       # the matrix table and the equity chart
    cli.py          # fetch | backtest | matrix | chart
  tests/            # 17 tests: timing, gaps, fees, causality, reference numbers
  data/             # committed BTC/ETH daily candles so the numbers reproduce offline
  docs/AUDIT.md     # the audit that started this
```

## Roadmap

- [x] Causal indicators + honest backtester + reference tests
- [ ] Walk-forward split with a purge gap; report out-of-sample only
- [ ] Position sizing as risk (stop distance × account), not notional
- [ ] Broker interface: `PaperBroker` and `CoinbaseBroker` behind one protocol
- [ ] SQLite journal: intents → acks → fills, with `client_order_id` idempotency
- [ ] Restart-safe paper trader, reconciles against the exchange on boot
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

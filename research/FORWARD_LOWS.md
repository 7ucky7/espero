# Forward paper test — buying new 4-hour lows, 4-hour hold (#24)

Committed **before** any bar of the forward window is recorded. A paper test: nothing trades. The
twenty-fifth test in this repo.

## Why

#20 ([RESULTS_LOWS.md](RESULTS_LOWS.md)) found new 4-hour lows on a volume spike bouncing +14.8 bps in
the next hour (t 9.78, six years, every year, 40 of 42 coins), "real, not tradable" under the 18 bps
bar. Its information table showed the bounce growing to **+37.8 bps at 4 hours** (t 12.87). That
horizon was not pre-registered, so it is tested here, on data #20 could not have seen: bars that do
not exist yet.

## The rule — frozen (#20's, the horizon changed to 4 hours)

- **Bars**: Binance USDⓈ-M 5-minute klines from Binance's public daily archive, the same source as
  #20, for the same 42 coins (`{COIN}USDT`, SHIB as `1000SHIBUSDT`). Each day's file is recorded by
  the daily job once Binance publishes it; the day before the window is warm-up.
- **Trigger**: #20's exactly (`espero.lows.events`, `liq.triggers`' `down`: a close below the lowest
  low of the previous 48 bars, volume z ≥ 2, the last hour down, ATR above 0), one event per coin
  per hour.
- **Paper trade**: buy at the next bar's open, sell at the close 48 bars (4 hours) after the trigger
  bar: `r240`.

## Data — fixed

Events on UTC days **2026-10-30 → 2027-03-31**. Recorded in `data/lows/forward/`; the ledger is
`lows_fwd_trades.csv`. A day Binance does not publish is recorded as missing, never filled.

## Evaluation — once, after 2027-03-31

Each UTC day's mean is one observation.

**PASS requires all three:**

1. **The bounce holds**: mean 4-hour return > 0, **t ≥ 3**.
2. **Not one stretch**: mean > 0 in each half (Oct 30 → Dec 31; Jan 1 → Mar 31).
3. **It pays**: mean **above 18 bps** (two Hyperliquid taker round trips) with **t > 2**.

## Power, said in advance

At #20's six-year average for 4 hours (+37.8 bps) the expected t over these 153 days is about 3.5. But
#20's bounce was smaller from 2022 on (about two thirds of its average at 1 hour); at that size the
expected t is about 2.3. A FAIL would then not prove it absent; a PASS needs it at least as strong as
its six-year average.

## Outcomes — fixed now

- **PASS**: a document for sizing and execution on a real venue (Binance.US spot or Hyperliquid),
  written before any order.
- **1–2 hold, 3 fails**: real, not tradable; nothing ships.
- **Anything else: FAIL.** No stopping early on the running numbers.

## Known confounds

- Five months, one stretch of market. Overlapping trades (a coin can be held twice within 4 hours of
  a later trigger) are counted as they come, as in #20.
- Binance perpetual prices, not the venue that would trade; entry at the next 5-minute open after a
  crash bar is optimistic, which the two-round-trip bar allows for.

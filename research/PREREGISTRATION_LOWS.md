# Pre-registration — new 4-hour lows bounce (#20)

Committed **before** any 5-minute bar for this test is downloaded, together with #21's document
([PREREGISTRATION_LIQSPIKE.md](PREREGISTRATION_LIQSPIKE.md)), so neither can be shaped by the other's
result. #21 runs first; #20 does not touch its months. The twenty-first test in this repo.

## Why this hypothesis

打板 (#10, #13) bought new 4-hour highs on a volume spike and lost before fees: in this repo,
breakouts reverse. #18's information table measured the mirror on its 82 first-of-month days: new
4-hour **lows** on a volume spike bounced about 18.5 bps in the next hour (t 3.0), while new highs
did not continue. If that is the same forced-selling reversal #18 and the aggr exploration pointed at,
the long-only way to own it is to buy the breakdown, not the breakout. This tests it on the days #18
never used, with price alone (no liquidation data exists for them).

## Data — fixed

- **Bars**: Binance's public archive (data.binance.vision), monthly **5-minute** USDⓈ-M futures klines
  for the 42 coins of `espero/xs.py::UNIVERSE` (`{COIN}USDT`, SHIB as `1000SHIBUSDT`), months
  2019-12 → 2026-03 (December 2019 for warm-up). Cached in `data/lows/` (not committed); the event
  table, output and manifest are committed. Missing months are recorded, never substituted; other
  download errors stop the run, to be fixed and rerun before any number is printed.
- **Days**: events on UTC days **2020-01-01 → 2026-03-31**, **excluding** the first day of every
  month and the days before and after it (the days #18 used and their neighbours). Nothing from
  April 2026 on, the months of the aggr exploration and #21.

## The rule — frozen

- **Trigger**: #18's `down` trigger exactly (`liq.triggers`, built on `degen.features`, #10's frozen
  definitions): the close below the lowest low of the previous 48 bars, volume z-score ≥ 2 over 48
  bars, the last hour's return below 0, ATR above 0.
- **One event per coin per hour**: a coin's breakdowns in the 12 bars after an event are ignored.
- **Entry** at the next bar's open. **Long returns** (simple) to the close of bar *t*+3 (15 minutes),
  *t*+12 (1 hour, primary) and *t*+48 (4 hours). A missing bar leaves that return empty.

## Evaluation — fixed

Each UTC day's mean is one observation: t = mean ÷ (sd ÷ √days).

**PASS requires all four:**

1. **The bounce**: mean 1-hour long return > 0, **t ≥ 3**.
2. **It starts at once**: mean 15-minute long return > 0.
3. **Not one era**: mean 1-hour return > 0 in each half (2020-01 → 2023-01, 2023-02 → 2026-03).
4. **It pays**: mean 1-hour long return **above 18 bps** (two Hyperliquid taker round trips, as
   #18, #19 and #21) with **t > 2**.

**Information only:** the 4-hour horizon; up-breaks (#10's trigger exactly) for contrast; by year;
by coin; net of Binance.US and Hyperliquid round trips.

## Outcomes — fixed now

- **PASS**: `research/FORWARD_LOWS.md` before anything trades, then the degen paper loop's trigger
  mirrored (buy the breakdown) on Hyperliquid prices.
- **Criteria 1–3 hold, 4 fails**: "real, not tradable after costs"; nothing ships.
- **Anything else: FAIL.** Not re-tuned on this data.

## Known confounds

- **The hurdle equals #18's estimate**: a pass needs the bounce at least as large on new days as on
  #18's.
- **Entry at the next 5-minute open after a crash bar** is optimistic: spreads are widest there.
  The two-round-trip hurdle is the allowance.
- **Survivorship**: today's coin list.
- **Perpetual prices**, not Hyperliquid or Binance.US spot.

## Transparency — what was seen before this commit

#18's information table (the 18.5 bps bounce on its 82 days), the aggr exploration of April–June
2026, #19's result, and the design of #21. No 5-minute bar from the days this test uses.

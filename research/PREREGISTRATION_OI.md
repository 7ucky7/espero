# Pre-registration — breakdowns made of closing positions bounce more (#25)

Committed **before** any open-interest file for this test is downloaded (one file's columns were
looked at, below). The twenty-sixth test in this repo.

## Why

#18 asked whether a breakout made of liquidations (forced trades) reverses more than an organic one.
The direction was right everywhere, but it fell short of t −3, on only 82 free days of liquidation
data, and only in the second half. Binance keeps no liquidation history, but its public archive keeps
**open interest every 5 minutes** for every day. When a coin breaks to a new low and open interest
drops sharply in the same hour, positions were closed in a hurry: mostly longs liquidated or
stopped out, forced selling. When open interest holds or rises, new shorts opened the move: organic
selling. This asks #18's question with that proxy, on all days, for down-breaks, the side a long-only
account can trade.

## Data — fixed

- **Events**: #20's down-breaks exactly (`espero.lows.events`, on the 5-minute bars #20 downloaded),
  on UTC days **2021-01-01 → 2026-03-31**, excluding #18's days and their neighbours as #20 did.
- **Open interest**: Binance's daily `metrics` archive for the same 42 perpetuals:
  `sum_open_interest` at each 5-minute `create_time`. Cached in `data/oi/` (not committed). A missing
  file or snapshot leaves that event without a measure; nothing is filled.

## The measure — frozen

For a down-break whose trigger bar closes at *T*:

- **oi_drop** = (OI at *T* − 1h − OI at *T*) ÷ OI at *T* − 1h, each OI being the last snapshot at or
  before that time. Positive when positions closed during the hour of the break.
- **Outcome**: #20's long return to the close one hour after the trigger bar, bought at the next
  bar's open (`r60`).

## Evaluation — fixed

On each UTC day, the day's down-breaks are ranked by oi_drop (percentile ranks, ties averaged):
**forced** = rank above ⅔, **organic** = ⅓ or below; days with fewer than 6 measured events are not
used. D(day) = mean r60 of forced − mean r60 of organic. Each day is one observation.

**PASS requires all four:**

1. **Forced breakdowns bounce more**: mean D **> 0, t ≥ 3**.
2. **Not the coin mix**: the same D with oi_drop minus the coin's own mean oi_drop: mean > 0.
3. **Not one era**: mean D > 0 in each half (2021-01 → 2023-08; 2023-09 → 2026-03).
4. **It pays**: buying the forced breakdowns alone earns a mean 1-hour return **above 18 bps** with
   **t > 2**.

**Information only**: the 4-hour return; global terciles; oi_drop over 15 minutes; by year.

## Outcomes — fixed now

- **PASS**: a forward paper test document (as #24's) before anything trades.
- **1–3 hold, 4 fails**: real, not tradable; the proxy may still serve as a filter in a document of
  its own.
- **Anything else: FAIL.** Not re-tuned on this data.

## Known confounds

- **#20 has already measured these events' average bounce** (+14.8 bps, t 9.8). What it never
  computed is the split by open interest, which is all this test looks at. The pooled average is
  known; the difference between forced and organic is not.
- **Open interest is a proxy**: it falls when any positions close, voluntary or forced, and when both
  sides close at once. It cannot tell a liquidation from a frightened long selling on purpose.
- **Snapshot timing**: Binance stamps each snapshot with its `create_time`; the exact instant it
  measures within the 5 minutes is not documented.
- Survivorship (today's coin list); Binance perpetual prices.

## Transparency — what was seen before this commit

The columns and row count of one metrics file (ADAUSDT, 2026-10-27, outside the window), and the
response codes and sizes of four BTCUSDT files. #18's and #20's results.

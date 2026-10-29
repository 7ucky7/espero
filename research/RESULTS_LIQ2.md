# Result — #18's rule on every day of Binance's COIN-M liquidations (#26)

**Verdict: PASS.** All four criteria. On 429 days #18 never used (June 2023 → October 2024), breaks
made of liquidations faded 23.6 bps more over the next hour than organic ones (t −4.06), in both
halves, and when each coin is compared with its own normal; buying the forced down-breaks earned
+23.5 bps an hour (t 7.13). #18's two failures (strength and era) were met with real liquidation data
on enough days. The first signal in this repo to pass every pre-registered criterion. **The
pre-registration's outcome now applies: a forward-test document before anything trades.**

Spec: [PREREGISTRATION_LIQ2.md](PREREGISTRATION_LIQ2.md) (`c1773a7`) and its amendment before any
download (`8c84a05`); code `7014179`. One crash before any number printed (a column type after
concatenating empty days; fixed in `c6ee4cc`) and one run. Output in
[liq2_run.txt](liq2_run.txt), events in [liq2_events.csv.gz](liq2_events.csv.gz).

## Data

Binance COIN-M liquidation snapshots (data.binance.vision; found by the user's script), 26 coins,
2023-06-26 → 2024-10-14 with #18's days and their neighbours left out: 429 days, **35,906 breaks**
(16,169 up, 19,737 down), 34,202 usable. Prices and volume from Binance USDⓈ-M 5-minute bars.

## Criteria (#18's; halves split at 2024-02-16)

| # | criterion | required | actual | met |
|---|---|---|---|---|
| 1 | forced breaks fade relative to organic | D < 0, t ≤ −3 | **−23.6 bps, t −4.06**, 147 days | yes |
| 2 | not the coin mix | D < 0 | −7.7 bps (t −3.25), 429 days | yes |
| 3 | not one era | D < 0 in both halves | −22.6 bps, −24.7 bps | yes |
| 4 | a long leg > 18 bps an hour, t > 2 | either leg | (a) forced down-breaks **+23.5 bps, t 7.13**; (b) organic up-breaks −4.5 bps | yes |

## Read it with these in mind

1. **Criterion 1 ran on 147 of the 429 days, by #18's tie rule.** COIN-M is a small market: 68% of
   breaks had no liquidation on their side at all. Ties share their average rank, so on a day where
   more than about two-thirds of breaks were zero they all ranked "middle", there was no organic
   group, and the day dropped out. The 147 days are the busier ones (53% zeros against 77%). A check
   made after the run, on every day (forced breaks against breaks with no liquidation at all), gives
   **−12.3 bps, t −4.90, 428 days**, and criterion 2 already used all 429 days. The effect is not a
   product of the day selection; it is about half as large on the quiet days. (The "global terciles"
   line is empty for the same reason: a zero's overall rank is 0.34, just above the ⅓ cut.)
2. **Most of leg (a) is the general bounce, but not all.** #20 measured the average down-break bounce
   at about +10 bps a day in 2023–24; forced down-breaks earned +23.5. After a Hyperliquid round trip:
   +14.5 bps.
3. **4 hours is stronger still** (information only): D −43.7 bps (t −5.65).
4. **Taker flow tells nothing** (information only): ranking by aggressor agreement instead of
   liquidations, D +0.0 bps. It is the liquidations, not the aggressive volume, that separate the
   breaks that reverse.
5. **COIN-M is not where the bot would trade**, and Binance stopped publishing this archive after
   2024-10-14, so a forward test needs a live liquidation feed of its own (aggr's, or the exchanges').

## What this changes

#18's idea is confirmed on new data: **breaks made of liquidations reverse, and the long-only way to
use it is to buy down-breaks driven by long liquidations**. Per the pre-registration, nothing trades
until a forward test document is written and the forward test runs.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 18 | Liquidations sort breakouts into forced and organic (82 days) | fail — right direction, t −2.1, second half only |
| 20 | New 4-hour lows on volume bounce | real, not tradable — +14.8 bps in 1h, t 9.8 |
| **26** | **#18's rule on every day of COIN-M liquidations, Jun 2023 → Oct 2024** | **PASS** — forced breaks fade 23.6 bps more, t −4.1; forced down-breaks bought +23.5 bps an hour |

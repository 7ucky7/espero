# Result — liquidations sort breakouts into forced and organic (#18)

**Verdict: FAIL** on criteria 1 and 3. The forced share points the predicted way in every
variant: breaks made of liquidations fade more than organic ones. But it misses the t ≤ −3 hurdle
(t −2.11) and appears only in the second half of the period. The closest any intraday test here
has come, and still a fail.

Spec: [PREREGISTRATION_LIQ.md](PREREGISTRATION_LIQ.md) (committed `461fba7` before any test-day
data; the code `e09563c`, also before). Two download fixes before any number was printed are in its
amendment (`d9555cc`, `aac88c3`). One run; output in [liq_run.txt](liq_run.txt), events in
[liq_events.csv](liq_events.csv), what was missing in [liq_manifest.json](liq_manifest.json).

## Data

82 first-of-month days, 2020-01-01 → 2026-10-01, 42 coins: 2,986 coin-days had Binance bars. Of
those, 13 had no Binance liquidation file (no forced share, per the amendment), and 472 had no
Bybit file (mostly coins before their Bybit listing). **9,213 breaks** (4,437 up, 4,776 down),
9,212 usable, on all 82 days. 9.3% had no liquidation at all in the hour before.

## Criteria (y = the 1-hour return in the break's direction; within-day terciles of the forced share)

| # | criterion | required | actual | met |
|---|---|---|---|---|
| 1 | forced breaks fade relative to organic | mean D < 0, t ≤ −3 | D −11.4 bps, t −2.11 | **no** |
| 2 | not the coin mix (coin-centred share) | mean D < 0 | −11.2 bps (t −2.01) | yes |
| 3 | not one era | D < 0 in both halves | +0.1 bps (2020-01 → 2023-05), −22.9 bps (2023-06 → 2026-10) | **no** |
| 4 | a long leg > 18 bps an hour, t > 2 | either leg | (a) forced down-breaks **+26.4 bps, t 3.85**; (b) organic up-breaks +2.5 bps, t 0.46 | yes |

## What the tables say

1. **The direction is right everywhere, and the size is not proven.** Every variant has forced
   breaks doing worse than organic ones: Binance's liquidations alone −13.0 bps (t −2.51), Bybit's
   alone −8.1, a 15-minute window −11.1, the 4-hour horizon −21.2 (t −2.37). The taker flow aggr
   draws as CVD (information only) scores −9.8 bps. None reaches t −3.
2. **It is all in the second half.** 2020 → mid-2023: nothing (+0.1 bps). Mid-2023 → 2026: −22.9
   bps. One reading is that the measurement improved: Bybit's complete liquidation feed replaced
   its sampled one in recent years, and the share is only as good as the feeds. Another is that the
   market changed. This test cannot tell them apart, and the pre-registered answer is FAIL.
3. **Down-breaks bounce; up-breaks do not continue.** Across all breaks (information only),
   down-breaks moved **−18.5 bps against their direction** in the next hour (t −3.02), so a long
   bought at a new 4-hour low on a volume spike made about +18.5 bps gross. Up-breaks went +5.5 bps
   their way (t 0.97), nothing. This is the same short-term reversal #9b, #10, #13 and #16/#17 kept
   finding, seen from the long side: the way to own it long-only is to buy breakdowns, not
   breakouts.
4. **Leg (a)'s +26.4 bps is mostly that bounce.** Buying forced down-breaks earned +26.4 bps;
   buying organic down-breaks +9.0 bps. The bounce after any down-break is most of it; the forced
   share adds something on top, but criterion 1 says that extra is not established.

## What this changes

Nothing ships, as the pre-registration fixed: no liquidation recorder, no forced/organic column.
aggr in the browser stays a tool for watching by eye.

**What this run suggests for next time**, as a new hypothesis with its own document and data it
has not seen (it cannot be claimed from this run): **buying 4-hour-low breaks on volume** (the
mirror of 打板) may earn the reversal that buying breakouts paid for. It needs no liquidation data,
so it can be tested on the roughly 2,400 days of Binance bars that are not first days of the month,
none of which any test here has used.

## Transparency

- One run, after two pre-run fixes (Tardis's 400/140 answer and a dropped read), both before any
  number was printed and recorded in the pre-registration's amendment.
- Leg (a) meets criterion 4, but the verdict needs all four criteria. It is reported, not used.
- Each day counts once (82 observations), which is why the t-statistics are modest even with 9,212
  events: breaks on the same day move together.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 12 | Carry with swap gap + maker execution (Hyperliquid) | pass, provisional — forward test to 2026-11-27 |
| 16 | Altcoins led by their peer basket, hourly | fail — no lead at any horizon |
| 17 | ETH-ecosystem coins led by ETH, hourly | fail — wrong sign, within luck |
| **18** | **Liquidations sort breakouts into forced and organic** | **fail** — right direction, t −2.1, second half only |

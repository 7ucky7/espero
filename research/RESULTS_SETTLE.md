# Result — the funding settlement moves prices (#19)

**Verdict: real, not tradable after costs.** Criteria 1–3 pass, 4 fails. Around an 8-hour funding
settlement where one side pays a high rate, prices dip toward the paying side before the instant
and rebound after it, against coins with ordinary funding in the same hour and against the same
coin 4 hours later. This is the first effect a pre-registered test in this repo has confirmed, and
the first test chosen by asking which rule forces someone to trade. It is also small, as the
pre-registration said it had to be, and no long-only spot trade earns it after costs.

Spec: [PREREGISTRATION_SETTLE.md](PREREGISTRATION_SETTLE.md) (committed `d17b0b8` before any data;
the code `af67a7c`, also before). One run; output in [settle_run.txt](settle_run.txt), the high
events with every computed column in [settle_events.csv](settle_events.csv), what was fetched or
missing in [settle_manifest.json](settle_manifest.json).

## Data

Binance USDⓈ-M funding for the 42 coins, 2020-01-01 → 2026-09-30, with hourly perpetual and spot
bars from Binance's archive: **266,964 8-hour settlements**. 17,845 had a high previous rate
(|rate| ≥ 0.05%: 13,732 with longs paying, 4,113 with shorts paying) and 211,519 were baseline.
9,579 high events had at least three baseline coins in the same hour, and so a value of g, on
1,452 days.

## Criteria (hourly perpetual bars; g = the settlement's excess swing minus the placebo's)

| # | criterion | required | actual | met |
|---|---|---|---|---|
| 1 | the settlement moves prices | mean g > 0, t ≥ 3 | **+15.5 bps, t 3.52** | yes |
| 2 | the predicted shape | excess pre < 0, post > 0 | pre −3.3 bps (t −1.56), post **+6.9 bps** (t 2.90) | yes |
| 3 | not one era | g > 0 in both halves | +13.2 bps (2020-01 → 2023-04, 875 days), +18.8 bps (2023-05 → 2026-09, 577 days) | yes |
| 4 | a long-only spot leg | > 18 bps, t > 2 | (a) after the longs paid **−7.4 bps** (t −1.32); (b) into the short cover +7.1 bps (t 1.85) | **no** |

## What the tables say

1. **The rule moves prices, mostly after the instant.** Against same-hour baseline coins, a coin
   whose holders pay a high rate drifts 3 bps against them in the hour before (not significant on
   its own) and recovers 7 bps in the hour after (t 2.90). Against the same coin 4 hours later the
   swing is 15.5 bps. The settlement alone, without the placebo, is +10.2 bps (t 3.22); the placebo
   alone is −4.9 bps (t −1.68): high-funding coins drift slightly against their payers at other
   hours too, which the placebo subtracts.
2. **It holds for both signs and in both eras.** The first half is mostly longs paying (the
   2020–21 mania), the second mostly shorts paying (2022 onward). The effect is there in each.
3. **It grows with the rate, sharply at the extreme** (information only): +11.1 bps at 0.05–0.1%
   per settlement (t 2.57), +13.2 at 0.1–0.2% (t 1.42), **+86.4 bps at 0.2% and above** (t 4.21, 277
   days). Grouping on the rate that actually settles, which traders see building during the
   interval but this test could not know in advance, gives +31.1 bps (t 5.95). Neither can be
   claimed from this run.
4. **It shows on spot too, smaller**: +11.4 bps (t 2.54). Two-hour windows: +17.4 bps (t 2.74).

## Why it is not tradable

- **The effect is relative.** It is a coin against other coins in the same hour. In absolute terms,
  buying spot right after longs paid **lost** 7.4 bps on average. That leg covers all 13,732 such
  settlements, including the frothiest hours when nearly every coin paid and there was no baseline
  to compare with, and the whole market tended to fall after those settlements. Holding the
  relative effect means a long coin against a short basket: two legs of costs on about 7 bps.
- **Buying into the short cover** earned +7.1 bps gross (t 1.85), +3.1 bps after a Binance.US
  round trip and −1.9 bps after Hyperliquid's: a coin flip after costs.
- **The rule bounds it.** If the swing were much larger than the funding plus fees, arbitrageurs
  would trade against it, and it isn't larger: that is the mechanism working as written.

## What this changes

Nothing ships, as the pre-registration fixed: no paper loop, no alerts.

What it establishes is the method. Asking which rule forces someone to trade, then testing the
mechanism once on data not seen before, produced the repo's first confirmed effect after nineteen
pattern-first tests produced none. The size is what a well-arbitraged rule leaves: real, and smaller
than a round trip.

**Leads, each needing its own document and data:** the extreme bucket (≥ 0.2% per settlement), and
timing a trade you would make anyway: for a coin whose shorts pay a high rate, buying in the hour
before the settlement did better than buying in the hour after.

## Transparency

- One run; no crash and no amendment.
- **Binance's 4-hour switch.** Since 2023 Binance has moved a coin to 4-hour settlements when its
  funding reaches the cap. This test kept 8-hour settlements only, so the most extreme recent
  episodes are not in it: long-paying high events fall from 8,490 in 2021 to almost none after 2024.
- 457 perpetual months and 386 spot months were missing across the 42 coins (coins listed later
  than 2020, and delistings), all recorded in the manifest and none substituted.
- The leg results use every high event; g uses only those with three baseline coins in the same
  hour. Both are as pre-registered.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 12 | Carry with swap gap + maker execution (Hyperliquid) | pass, provisional — forward test to 2026-11-27 |
| 18 | Liquidations sort breakouts into forced and organic | fail — right direction, t −2.1, second half only |
| **19** | **The funding settlement moves prices** | **real, not tradable** — +15.5 bps, t 3.5; no long-only leg clears costs |

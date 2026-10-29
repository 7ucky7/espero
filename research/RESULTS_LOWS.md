# Result — new 4-hour lows bounce (#20)

**Verdict: real, not tradable after costs.** Criteria 1–3 pass, 4 fails. Buying a new 4-hour low on
a volume spike earned +14.8 bps over the next hour, on 136,523 breakdowns over 2,055 days (t 9.78),
in both halves of six years: the strongest effect any test in this repo has measured. It falls short
of the 18 bps bar for one hour. Breakouts, the trade 打板 made, lost −6.9 bps (t −6.27).

Spec: [PREREGISTRATION_LOWS.md](PREREGISTRATION_LOWS.md) (committed `0b50764` with #21's, before
either ran); code `776088e`, also before. Two download crashes before any number was printed; the
downloader retried longer (`3feeed8`) and the run resumed from its cache. Output in
[lows_run.txt](lows_run.txt), events in [lows_events.csv.gz](lows_events.csv.gz), the manifest in
[lows_manifest.json](lows_manifest.json).

## Data

Binance USDⓈ-M 5-minute bars, 42 coins, events on 2020-01-03 → 2026-03-30 with #18's first-of-month
days and their neighbours left out: **136,523 breakdowns** on 2,055 days, and 114,488 breakouts for
contrast. 451 coin-months were missing (coins listed after 2020, delistings), none substituted.

## Criteria (a long bought at the next 5-minute open)

| # | criterion | required | actual | met |
|---|---|---|---|---|
| 1 | the bounce | 1h > 0, t ≥ 3 | **+14.8 bps, t 9.78** | yes |
| 2 | it starts at once | 15 minutes > 0 | +6.7 bps (t 8.08) | yes |
| 3 | not one era | 1h > 0 in both halves | +20.0 bps (2020-01 → 2023-01), +9.6 bps (2023-02 → 2026-03) | yes |
| 4 | it pays | 1h > 18 bps, t > 2 | +14.8 bps | **no** |

## What the tables say

1. **Breakdowns bounce, breakouts don't continue.** The same trigger, mirrored: buying the new high
   lost 6.9 bps in an hour (t −6.27); buying the new low made 14.8 (t 9.78). This settles what #10,
   #13 and #18 kept hinting: in crypto at this scale, a violent new extreme reverses, and the long-only
   way to own that is to buy the low.
2. **Every year, smaller lately.** +25 bps in 2020 and 2021, +9 to +10 bps each year 2022–2025, +12.9
   in early 2026 (81 days, t 1.34). The "modern market" explanation for #18 does not show up here:
   the bounce is weaker since 2022, not stronger.
3. **Every coin but two.** 40 of 42 coins bounce on average (TRX and RUNE about −5 bps).
4. **It grows with time, information only.** At 4 hours: **+37.8 bps (t 12.87)**, more than double
   the 18 bps bar. It was not the pre-registered horizon, so it is a lead, not a result.
5. **Costs**: the 1-hour bounce nets +10.8 bps after a Binance.US round trip and +5.8 after
   Hyperliquid's, above zero but under the two-round-trip cushion the bar requires for entering at a
   crash bar's next open.

## What this changes

Nothing ships at 1 hour, as fixed. **The 4-hour hold is the strongest lead this repo has.** It needs
its own document and data #20 did not use: the cleanest is a forward paper test, like #22's, from
the day it is written.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 12 | Carry with swap gap + maker execution (Hyperliquid) | pass, provisional — forward test to 2026-11-27 |
| 19 | The funding settlement moves prices | real, not tradable — +15.5 bps, t 3.5 |
| **20** | **New 4-hour lows on volume bounce** | **real, not tradable** — +14.8 bps in 1h, t 9.8; +37.8 bps at 4h (information) |
| 21 | Liquidation spikes reverse (sealed July–October) | fail — R +4.8 bps, t 0.3 |
| 22, 23 | Liquidation spikes, long and short sides, paper | running — judged after 2027-03-31 |

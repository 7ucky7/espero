# Result — breakdowns made of closing positions bounce more (#25)

**Verdict: FAIL** on criteria 1 and 4. Breakdowns where open interest dropped most in the hour did
bounce a little more than those where it held (+3.2 bps over the next hour, t 2.36), but not enough
for the t ≥ 3 bar, and the difference has faded: positive in 2022–2023, about zero in 2024, negative
in 2025–2026. Open interest is a weak stand-in for liquidations: #26, on real liquidations, found a
gap seven times larger.

Spec: [PREREGISTRATION_OI.md](PREREGISTRATION_OI.md) (`0943263`); code `01f7109`, before any
open-interest file. One run; output in [oi_run.txt](oi_run.txt), events in
[oi_events.csv.gz](oi_events.csv.gz).

## Data

#20's down-breaks on 2021-01-01 → 2026-03-31 (#18's days left out): 124,869, of which 105,156 had an
open-interest drop measured (Binance's metrics archive misses about 300 days a coin), on 1,709 days.
Median drop in the hour of the break +0.18%; the top tenth above +1.45%.

## Criteria

| # | criterion | required | actual | met |
|---|---|---|---|---|
| 1 | forced breakdowns bounce more | D > 0, t ≥ 3 | +3.2 bps, t 2.36, 1,430 days | **no** |
| 2 | not the coin mix | D > 0 | +3.3 bps (t 2.37) | yes |
| 3 | not one era | D > 0 in both halves | +7.6 bps (2021 → Aug 2023), +0.2 bps (Sep 2023 → 2026) | yes |
| 4 | it pays | forced 1h > 18 bps, t > 2 | +12.3 bps (t 6.00) | **no** |

## What the tables say

1. **Every group bounces; the forced one only slightly more.** 1-hour: forced +12.3 bps, middle +8.3,
   organic +9.2. 4 hours: +31.8, +22.0, +24.6. The bounce is #20's; open interest barely sorts it.
2. **It has faded.** D by year: 2022 +6.7, 2023 +10.3, 2024 +1.2, 2025 −4.2, early 2026 −6.3 bps.
   Criterion 3 passes on a technicality: the second half is +0.2 bps.
3. **Real liquidations carry what open interest does not.** Over #26's window (mid-2023 → late 2024)
   the open-interest gap was about +5 bps a year on average here; #26 measured 23.6 bps with
   liquidations. Open interest falls whenever positions close, voluntarily or not; only the
   liquidation feed knows which closes were forced.
4. **Information only**: the 4-hour D is +7.2 bps (t 3.19); not the pre-registered horizon.

## What this changes

Nothing ships. For #26's forward test it is a caution, not a contradiction: the forced/organic
split measured by a proxy has weakened since 2024, and #26's own window ends in October 2024. A
forward test on live liquidations is the only way to know whether #26's effect is still there.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 20 | New 4-hour lows on volume bounce | real, not tradable — +14.8 bps in 1h, t 9.8 |
| **25** | **Breakdowns with an open-interest drop bounce more** | **fail** — +3.2 bps, t 2.4; faded since 2024 |
| 26 | #18's rule on every day of COIN-M liquidations | PASS — forced breaks fade 23.6 bps more, t −4.1 |

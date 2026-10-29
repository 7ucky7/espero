# Result — Polymarket's hourly bitcoin crowd against a random walk (#37)

**Verdict: FAIL** on criteria 1 and 3. At minute 30, betting the random walk's side whenever it
differs from the crowd by 5 points earned **+0.91 cents per $1 share** (t 0.99, 2,271 bets), and
nothing at a 2-cent cost.

On forecasting, **the crowd beat the model**: Brier 0.1702 against the random walk's 0.1733, over
4,297 markets. The crowd prices these hourly binaries better than a textbook random walk does,
most likely because it prices the fat tails a 24-hour σ misses. Paper and research only:
Polymarket restricts US persons.

Spec: [PREREGISTRATION_POLYHOUR.md](PREREGISTRATION_POLYHOUR.md) (`f854e4d`); code `3d1af4a`. One
run, output in [polyhour_run.txt](polyhour_run.txt), markets in
[polyhour_markets.csv.gz](polyhour_markets.csv.gz).

To save time, a helper fetched the second half of the markets in parallel into the same cache,
with the same request format and each file written whole. The run read them as cached. No number
was looked at before the run printed.

## Data

4,320 hourly markets, 2026-05-01 → 2026-10-27: 6 not found, none unresolved, 4,297 with both prices.
Up won 50.0% of the time. The median volume of the markets bet on was $30,056.

## Criteria

| # | criterion | required | actual | met |
|---|---|---|---|---|
| 1 | it pays | mean profit per bet > 0, t ≥ 3 | +0.91 cents, t 0.99 | **no** |
| 2 | not one stretch | > 0 in each half | +0.75, +1.09 cents | yes |
| 3 | the model forecasts better | Brier(q) < Brier(p) | 0.1733 against the crowd's 0.1702 | **no** |

## What the tables say

1. **The crowd is a decent pricer at minute 30.** The small gain at a 1-cent cost (+0.9 cents) is
   inside noise and disappears at 2 cents.
2. **Minute 15 is different (information only).** The same bet 15 minutes into the hour earned
   **+4.65 cents** (t 4.29, 1,987 bets). Minute 45: +2.05 cents (t 2.45). Early in the hour the crowd
   may lag the move so far. A lead for a forward test, not a result.
3. **The crowd does not chase; it leans against the last hour.** Its price of Up at the hour's
   start is correlated −0.46 with the previous hour's BTC move, and +0.06 with the outcome (about
   t 3.8 over 4,300 markets). A slight contrarian lean that is slightly right, the opposite of the
   chasing the pre-registration expected.
4. **By hour of day** the profits scatter between −8 and +8 cents with no pattern a rule could use.

## What this changes

Nothing trades, and it could not: US access is restricted. The minute-15 lead could be recorded
forward from Polymarket's public data, if there is ever a reason to (idea 8 in IDEAS_NOVEL.md).

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| **37** | **Polymarket's hourly BTC crowd mispriced against a random walk** | **fail**: +0.9 cents a share, t 1.0; the crowd forecasts better (Brier 0.1702 against 0.1733). Lead: minute 15, +4.7 cents |

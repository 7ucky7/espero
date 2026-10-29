# Result — what the accounts' 00:00 UTC fills cost (#33)

**Verdict: FAIL** on criteria 1 and 4. The accounts' fill time stays.

**For almost every fill the accounts make, 00:00 UTC is an unbiased price.** On 93.5% of
coin-Mondays funding is ordinary, and the price drifts +1.1 bps in the half hour after the fill
(t 0.2).

The pre-registered effect, a recovery after 00:00 when longs pay hard, is +16 bps but noise:
t 0.9, positive before mid-2023 and negative after.

The mirror is where the bias lives, and it is rare. When **shorts pay hard** (1.5% of
coin-Mondays), the price **falls 34 bps** in the 30 minutes after 00:00 (t −2.6).

Spec: [PREREGISTRATION_FILLCOST.md](PREREGISTRATION_FILLCOST.md) (`195a2eb`); code `a76c0d8`. One run,
output in [fillcost_run.txt](fillcost_run.txt), events in [fillcost_events.csv.gz](fillcost_events.csv.gz).

## Data

- 42 coins, 356 Mondays (2020-01-06 → 2026-10-26).
- 13,089 coin-Mondays, 12,989 of them with a 30-minute drift.
- Buckets: normal 93.5%, longs paying ≥ 0.05% 5.0%, shorts paying ≥ 0.05% 1.5%.

## Criteria

| # | criterion | required | actual | met |
|---|---|---|---|---|
| 1 | longs paying: recovery after 00:00 | m30 > 0, t ≥ 3 | +16.3 bps, t 0.92, 652 coin-Mondays | **no** |
| 2 | big enough to move a fill | ≥ 5 bps | +16.3 bps | yes |
| 3 | shorts paying: the mirror | m30 < 0 | −34.0 bps, t −2.62, 198 coin-Mondays | yes |
| 4 | not one era | > 0 in both halves | +21.4 bps (2020 → May 2023), −5.7 bps (after) | **no** |

## What the tables say

1. **The ordinary fill is fine.** Normal-funding coin-Mondays drift −1.2, +1.1 and −3.0 bps at 15, 30
   and 60 minutes, none significant. That is what XS and #8 almost always trade.

2. **Hard-paying shorts are the one place 00:00 is biased.** At 30 minutes after the settlement:

   | settlement | shorts paying hard | longs paying hard | normal |
   |---|---|---|---|
   | Mondays 00:00 | −34.0 bps (t −2.6) | +16.3 bps (t 0.9) | +1.1 bps |
   | every day 00:00 | −18.6 bps (t −3.7) | +8.0 bps (t 1.3) | +2.6 bps |
   | every day 08:00 | −21.0 bps (t −4.4) | +4.9 bps (t 1.2) | +0.7 bps |
   | every day 16:00 | −4.2 bps (t −0.7) | +9.6 bps (t 1.8) | +2.6 bps |

   When shorts pay a premium, the price is pushed up into the settlement (shorts close before paying)
   and falls back after it. That is #19's swing against the paying side, measured at the minute. A buy
   of such a coin at 00:00 overpays by about 20–35 bps against waiting 30 minutes. A sell gains as
   much.

3. **Longs paying is noise here.** The recovery the pre-registration expected is small and unstable
   by year (+42, +4, −44, +19, −76 bps where there were events).

## What this changes

- **XS keeps its 00:00 fill.**
- **#8 stays frozen.** No ERRATA is needed: its fills are on ordinary-funding coins almost always,
  where the bias is about +1 bps.
- **One rule worth writing down, information only:** a buy of a coin whose shorts pay ≥ 0.05% is
  better made 30 minutes after a settlement. It affects about 1 fill in 70. It would need its own
  document before any account changes.
- The shorts-paying drift (−19 to −34 bps after a settlement, t up to −4.4) was seen here, so it is a
  lead, not a result.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 19 | Funding settlement moves prices | real, not tradable: 15.5 bps against the paying side |
| **33** | **XS's and #8's 00:00 UTC fills are biased by the settlement** | **fail**: unbiased on 93.5% of fills (+1.1 bps); when shorts pay hard the price falls 34 bps after 00:00 |

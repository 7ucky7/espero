# Forward paper test — short-liquidation spikes fade, 4-hour hold (#23)

Committed **before** any bar of the forward window is recorded. A paper test: nothing trades. The
twenty-fourth test in this repo, run beside #22 ([FORWARD_LIQ.md](FORWARD_LIQ.md)) and judged
separately: long and short liquidations are different forced flows, with different expected moves
and different uses for this account, so neither test's result says anything about the other's.
(#22's document lists the short side as information only; this test replaces that.)

## Why

When shorts are liquidated the exchange buys for them at any price, pushing the price up. If forced
buying is temporary, the price should come back. #21's information table on the sealed months: after
short-liquidation spikes, 4 hours later the price was 27 bps below the average hour (t −2.88); the
April–June exploration pointed the same way. For a long-only account the use is a warning (do not
buy a coin that has just squeezed); on Hyperliquid it would be a paper short.

## The rule — frozen (#22's, mirrored)

- Coins, markets and the hourly panel: `espero/aggr.py`, as #22.
- **Spike**: an hour whose **short**-liquidation share (`lbuy` ÷ volume) is above the 98th percentile
  of the coin's previous 720 hours (at least 600 present), with short liquidations above zero; one
  per cascade (6 hours): `espero.liqspike.spikes(df, "short", ...)`, unchanged.
- **Paper trade**: a short opened at the spike hour's close and closed 4 hours later.

## Data — fixed

The same forward window and recording as #22: spike hours from **2026-10-30 00:00** to
**2027-03-31 23:00 UTC**, from `data/aggr/forward/`. Ledger: `liqfwd_short_trades.csv`.

## Evaluation — once, after 2027-03-31

Each UTC day's mean is one observation.

**PASS requires all three:**

1. **Excess**: the 4-hour return after spikes minus the mean 4-hour return of every coin-hour in the
   window: mean **< 0, t ≤ −3**.
2. **Not one stretch**: the excess mean < 0 in each half (Oct 30 → Dec 31; Jan 1 → Mar 31).
3. **It pays as a short**: the paper short's raw 4-hour return (minus the price change) has a mean
   **above 18 bps** with **t > 2**.

## Outcomes — fixed now

- **PASS**: usable as a "do not buy" filter for this account, and a document for a paper short on
  Hyperliquid, written before any order.
- **1–2 hold, 3 fails**: real, not tradable as a short; still worth considering as a filter, in a
  document of its own.
- **Anything else: FAIL.** No stopping early on the running numbers.

## Known confounds

#22's, all of them: five months, 14 coins, one free server, a sampled Binance feed, entry at the
spike hour's close.

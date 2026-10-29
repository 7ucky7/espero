# Forward paper test — buying long-liquidation spikes, 4-hour hold (#22)

Committed **before** any bar of the forward window is recorded. A paper test: nothing trades, no
money. The twenty-third test in this repo.

## Why

#21 failed ([RESULTS_LIQSPIKE.md](RESULTS_LIQSPIKE.md)), but its information table left a lead: at the
4-hour horizon, after a coin's long-liquidation spikes, the price did better than the average hour
(+26 bps, t 3.12) on the sealed months, and the April–June exploration pointed the same way. #21's
design mistake (combining both sides into one same-day number) is not repeated: the long side is
judged on its own, over time. Since the sealed months are used, the only clean data is data not yet
recorded, so this test records it.

## The rule — frozen (#21's, unchanged except the horizon)

- **Coins, markets and the hourly panel**: aggr's, exactly as in the exploration and #21 (14 coins;
  price and volume from Binance futures, SHIB from OKX; liquidations summed over Binance futures,
  Bybit and OKX), now in `espero/aggr.py`.
- **Spike**: an hour whose long-liquidation share is above the 98th percentile of the coin's previous
  720 hours (at least 600 present), with long liquidations above zero; one per cascade (6 hours),
  `espero.liqspike.spikes` unchanged.
- **Paper trade**: buy at the spike hour's close, sell at the close 4 hours later.

## Data — fixed

- **Forward window**: spike hours from **2026-10-30 00:00 UTC** to **2027-03-31 23:00 UTC**. Nothing
  in it exists yet.
- **Recording**: the daily job (`espero daily`) saves each complete UTC day of aggr's hourly bars to
  `data/aggr/forward/` and rebuilds the ledger. Earlier aggr bars (April → October 28) are warm-up
  for thresholds only.
- A day aggr cannot serve is recorded as missing and is not filled from any other source.

## Evaluation — once, after 2027-03-31

Each UTC day's mean is one observation.

**PASS requires all three:**

1. **Excess**: the 4-hour return after spikes minus the mean 4-hour return of every coin-hour in the
   window: mean **> 0, t ≥ 3**.
2. **Not one stretch**: the excess mean > 0 in each half (Oct 30 → Dec 31; Jan 1 → Mar 31).
3. **It pays**: the raw 4-hour simple return has a mean **above 18 bps** (two Hyperliquid taker round
   trips) with **t > 2**.

Information only: short-liquidation spikes (as a paper short), 1-hour and 24-hour horizons, by coin.

## Outcomes — fixed now

- **PASS**: a document for real-money sizing and execution, written before any order.
- **1–2 hold, 3 fails**: real, not tradable; nothing ships.
- **Anything else: FAIL.** No peeking-driven stop: the ledger runs to the end date whatever it shows,
  and its running numbers decide nothing.

## Known confounds

- Five months, one stretch of market; 14 coins.
- aggr is one person's free server: gaps, or a change in what it records, end the test early as
  inconclusive, not as a pass or fail.
- Binance's liquidation feed is sampled (a lower bound).
- Entry at the spike hour's close assumes acting within a minute; the bot will see it a day later
  from the recorder, so this is a test of the effect, not of the execution.

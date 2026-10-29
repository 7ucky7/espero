# Pre-registration — liquidation spikes reverse (#21)

Committed **before** the sealed months are read, together with #20's document
([PREREGISTRATION_LOWS.md](PREREGISTRATION_LOWS.md)), so neither can be shaped by the other's
result. #21 runs first. The twenty-second test in this repo (#9 and #9b both count).

## Why this hypothesis

Liquidations are trades an exchange forces through at any price. Forced trades move prices
temporarily and the move comes back (Coval & Stafford, 2007, for mutual-fund fire sales). Three
looks in this repo point that way, none of them a confirmed test:

- #18: breakouts made mostly of liquidations faded more than organic ones (t −2.1, FAIL)
- #18, information only: new 4-hour lows bounced about 18 bps in the next hour
- the exploration of aggr's hourly bars, April–June 2026
  ([EXPLORE_AGGR_LIQ.md](EXPLORE_AGGR_LIQ.md)): after a coin's biggest long-liquidation hours, price
  rose 65 bps over the next day net of drift (t 2.4); after its biggest short-liquidation hours it
  fell 56 bps (t −2.6)

This test asks whether that pattern holds on months nobody has looked at, with a rule a bot could
run live.

## Data — fixed

- **Test months**: **2026-07-01 00:00 → 2026-10-28 23:00 UTC**, aggr's hourly bars downloaded on
  2026-10-29 and sealed unread: the four files in `data/aggr/holdout/`, which must match the SHA-256
  in [aggr_holdout_manifest.json](aggr_holdout_manifest.json) or the run stops.
- **Warm-up**: the explored months (`data/aggr/explore/`), used only for the trailing thresholds
  below, never for an outcome.
- **Coins and markets**: the exploration's, unchanged (`aggr_explore.COINS`): 14 coins; price and
  volume from Binance futures (SHIB from OKX); liquidations summed over every venue aggr records for
  the coin (Binance futures, Bybit, OKX). `lsell` is longs liquidated (a forced sale), `lbuy` is
  shorts liquidated (a forced buy).
- **The hourly panel**: the exploration's `panel`, unchanged. Missing hours stay empty.

## The rule — frozen, causal

For coin *i*, side *s* (longs or shorts liquidated) and the hour *h* (bar open; known at its close):

- **share** = liquidations on side *s* in hour *h* ÷ the hour's volume on the price market
- **spike**: share above the **98th percentile of the coin's share over the previous 720 hours**
  (*h* − 720 … *h* − 1, at least 600 of them present), with liquidations on that side above zero
- **one per cascade**, as explored: a spike within 6 hours after the previous qualifying hour of the
  same coin and side is the same cascade and not an event
- **events**: spikes whose hour opens from 2026-07-01 00:00 to 2026-10-27 23:00, so the 24 hours
  after each are in the data
- **returns**, from the spike hour's close: r4 and r24 = log(close 4 and 24 hours later ÷ close)
- **excess**: r minus the mean of the same-horizon return over every coin-hour in the test months
  (the exploration's baseline)
- **reversal R** = excess r24 for a long-liquidation spike, minus excess r24 for a short one: positive
  when the forced move comes back

## Evaluation — fixed

Each UTC day's mean is one observation (the day of the spike hour): t = mean ÷ (sd ÷ √days).

**PASS requires all four:**

1. **Forced flow reverts**: mean R over both sides > 0, **t ≥ 3**.
2. **On each side**: mean excess r24 > 0 after long-liquidation spikes and < 0 after short ones.
3. **Not one stretch**: mean R > 0 in each half (July–August; September 1 → October 27).
4. **A long-only trade pays**: after long-liquidation spikes, the **raw** 24-hour simple return (what
   a buyer earns, market move included) has a mean **above 18 bps** (two Hyperliquid taker round
   trips, as #18 and #19) with **t > 2**.

**Information only:** 1-hour and 4-hour horizons; entry at the next hour's open; each side
separately with t; the short side as a (paper) short; by coin; by spike size; market-wide spikes
(the 14 coins' liquidations summed); legs net of Binance.US and Hyperliquid round trips.

## Outcomes — fixed now

- **PASS**: `research/FORWARD_LIQSPIKE.md` before anything trades, then a recorder of aggr's (or the
  exchanges') hourly liquidations and a paper loop that buys the spikes.
- **Criteria 1–3 hold, 4 fails**: "real, not tradable after costs"; nothing ships.
- **Anything else: FAIL.** No re-tuning on these months: the sealed data is used once.

## Power, said in advance

If the effect is the size explored, criterion 1's expected t over these 119 days is about 4, and
the long side's alone about 2.8. A FAIL would not prove the effect absent; a PASS needs it at least
as strong as April–June suggested.

## Known confounds

- **Four months, one stretch of market**: whatever it did, July–October did it to every coin.
  Criterion 4 is measured raw, so a falling market can fail it even if the reversal is real.
- **Mostly majors**: 14 coins, the ones aggr records.
- **Sampled feeds**: Binance's liquidation stream sends at most one liquidation per coin per second,
  so its dollars are a lower bound, worst in a cascade.
- **Entry at the spike hour's close** assumes the bot acts within a minute of the hour; the next
  hour's open is reported beside it.
- **The baseline uses the whole test window**, as in the exploration: a fixed constant per horizon,
  the same for every event.

## Transparency — what was seen before this commit

The exploration of April–June (its table, charts and spike list), the existence and checksums of the
four sealed files (nothing in them), #18's and #19's results, and the design of #20.

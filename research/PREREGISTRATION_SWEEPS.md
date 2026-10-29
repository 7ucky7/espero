# Pre-registration — stop runs at yesterday's low reverse (#35)

Committed before any sweep is computed. The thirty-sixth test in this repo.

## Why

Stop-loss orders are forced orders, like liquidations. Unlike liquidations they cluster at prices
anyone can see in advance: **just past yesterday's high and low**. When the price trades through
such a level, the stops fire and sell (or buy) into the market. If the price then closes back on
the other side, that forced flow is spent, and by #26's logic the move should reverse.

Traders call this a liquidity sweep or stop hunt. I know of no rigorous public test. The trigger is
also new to this repo: every test so far fired on a new rolling 4-hour extreme. This one fires on a
fixed level known since midnight.

## Data — fixed

- **Bars**: Binance USDⓈ-M 5-minute klines for the 42 coins of `xs.UNIVERSE`, from the cached months
  and days (#20's `data/lows/`, #28's `data/levetf/`, #30's `data/bids/`). Nothing is downloaded.
- **Days**: UTC days 2020-01-02 → 2026-10-27. These months were read by #20 and #30 for 4-hour
  breakdowns, but never at yesterday's levels.

## The rule — frozen

For each coin and UTC day d:
- **Levels**: L = the lowest low of day d−1, and H = the highest high of day d−1. Day d−1 must have
  all 288 bars, or the day is skipped.
- **The sweep** (long side, primary):
  - the first bar j of day d whose low is below **L × (1 − 0.001)**, i.e. 10 bps through
    yesterday's low;
  - it is **reclaimed** if bar j or one of the next 3 bars (within 15 minutes) **closes above L**.
    The first such bar is k;
  - otherwise it is **failed**.
- **The trade**:
  - after a reclaim, buy at the open of bar k+1 and hold to the close of bar k+12 (1 hour; also
    k+48, 4 hours);
  - after a failure, the same long from the open of bar j+4, as the comparison.
- **Short side** (information only): the mirror at H. The first high above H × (1 + 0.001), reclaimed
  by a close below H within 15 minutes, then a paper short.
- Only the first sweep of each level each day counts. A missing bar in a trade's span leaves its
  return empty.

## Evaluation — fixed

Each UTC day's mean is one observation.

**PASS requires all four:**

1. **The reversal**: reclaimed sweeps' mean long 1-hour return **> 0, t ≥ 3**.
2. **The reclaim matters**: reclaimed minus failed, 1-hour, **> 0, t ≥ 2** (Welch on the two groups'
   day means).
3. **Not one era**: criterion 1's mean > 0 in both halves (2020-01 → 2023-04; 2023-05 → 2026-10).
4. **It pays**: reclaimed sweeps' mean **above 18 bps** (two Hyperliquid taker round trips), **t > 2**.

**Outcomes:**
- **PASS**: a forward document before anything trades.
- **Criteria 1–3 hold, 4 fails**: "real, not tradable after costs".
- **Anything else: FAIL.** Not re-tuned.

**Information only:**
- the 4-hour horizon;
- the short side at yesterday's high;
- the overlap with #20's breakdown trigger;
- round-number levels (BTC to the nearest $1,000 and ETH to the nearest $100), same rule;
- by year; by coin; net of costs.

## Known confounds

- **#20's bounce**: a sweep of yesterday's low is often also a new 4-hour low. Criterion 2 compares
  sweeps with each other, which #20's effect alone does not explain, and the overlap is reported.
- **Survivorship**: today's coin list.
- **Perpetual prices**; Hyperliquid's would differ by its spread.

## Transparency — what was seen before this commit

#20's and #30's results on these bars (4-hour lows and resting bids), #26, #19 and #33. No sweep of
any daily level has been computed in this repo.

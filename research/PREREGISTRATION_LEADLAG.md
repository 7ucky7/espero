# Pre-registration — BTC lead-lag into altcoins, hourly

Committed **before** `research/leadlag.py` is run and before any hourly candle is fetched for this
purpose. Hypothesis #9, and the first intraday one in this repo.

## Why this hypothesis

Bitcoin's market is the deepest in crypto; the smaller coins' markets are thinner and their prices
adjust to the same information more slowly. If that is true, a coin that has *not yet* moved with
BTC over the last hour should catch up over the next few hours. This is a flow mechanism, not a
chart pattern: it needs no indicator, and it has a documented analogue in equities (large caps lead
small caps at daily horizons; Lo & MacKinlay 1990) and in the crypto literature at intraday
horizons.

It is tested here because the two things an intraday rule needs — a plausible mechanism and a
venue where the fee fits inside the expected move — are both present, and because the hourly bar
strategy that used to live in this repo was just shown to have negative edge at every horizon. If
there is intraday predictability a small account can reach, it will be from flow, not from RSI.

## Data — fixed

- **Source**: Coinbase Exchange public hourly candles (`data.fetch`, granularity 3600), the same
  endpoint the paper trader uses. Real venue prices, real venue volume.
- **Universe**: the coins in `espero/xs.py::UNIVERSE` that Coinbase lists as `{COIN}-USD`. Coins it
  does not list are recorded as missing, not substituted.
- **Window**: the 365 days ending at the fetch time (fetched once, saved to `data/panel_hourly/`,
  not refreshed during analysis).
- **Leader**: BTC. It is excluded from the cross-section it is the leader of.
- **Eligibility on each hour**, from that hour's past only: at least **720 hourly closes** (30
  days) and trailing **168-hour (7-day) mean dollar volume ≥ $50,000 per hour**, so the top of a
  ranking cannot be a coin that trades $2,000 an hour.

**Survivorship** is disclosed: this is the 2026 list. **One year** is a short window with no full
cycle. Both bias upward.

## The signal — frozen

For coin *i* at the close of hour *t*:

```
leadlag_1h(i, t) = r_BTC(t-1, t) − r_i(t-1, t)
```

the gap between BTC's last-hour return and the coin's own. **Sign: positive**, a coin that lagged
BTC's move is expected to catch up. `leadlag_3h` (the same gap over three hours) is reported for
information.

**The control, pre-registered.** The gap is BTC's return minus the coin's own return, and the second
term alone is plain one-hour reversal (`rev_1`, already in the zoo). To count as a lead-lag effect
and not reversal in disguise, `leadlag_1h` must beat `rev_1` on the same data. If it does not, the
verdict is FAIL regardless of its own t-statistic.

Nothing is tuned: 1 hour, BTC as leader, no scaling, no neutralization. Any variant is a new
document.

## Evaluation — fixed

- **Primary horizon: 3 hours** (forward return from the close of hour *t* to the close of hour
  *t+3*). 1, 6 and 12 hours reported for information.
- **Method**: rank IC per hour across eligible coins; purged walk-forward with **4 test blocks** and
  a **24-hour embargo**, minimum 30 days of training.
- **Costs for the spread test**: Binance.US taker, 2 bps a side, 4 bps round trip, the cheapest
  venue in `venues.py`. Coinbase's 240 bps is reported to show what it would do to the result.

**PASS requires all four:**

1. out-of-sample rank IC **t > 3** at 3 hours
2. out-of-sample t for `leadlag_1h` **greater than** out-of-sample t for `rev_1` at 3 hours
3. mean top-minus-bottom quintile spread at 3 hours **> 10 bps** (two and a half round trips on the
   cheapest venue; a spread that only covers the fee is not an edge)
4. hit rate (fraction of hours with positive IC) **> 0.52**

Criterion 3 is the one hypothesis #8 taught: a rank IC can be large while the mean spread is
negative. Both must hold.

Anything else is FAIL, and a failure is not re-tuned on this data.

## What a pass would and would not mean

A pass means building the next thing, which does not exist yet: an hourly cross-sectional paper
book with resting limit orders, since a 3-hour hold at taker fees is still thin. It does not mean
capital, and it does not mean the effect survives the execution model; that is the forward test.

## Multiple testing

Ninth hypothesis; the table reports 13 zoo factors plus two variants, so 15 comparisons at four
horizons. The expected best t among that many null factors is printed next to the observed ones.
Two of nine passing so far, both risk-construction. The base rate for this one is low, and it is
written down here so the author cannot forget it when the first table looks good.

# Pre-registration — the funding settlement moves prices (#19)

Committed **before** any funding history or hourly bar for this test is downloaded, except the
probes listed under *Transparency*. Hypothesis #19, the twentieth test in this repo (#9 and #9b
both count).

## Why this hypothesis: the rule, who it forces, and when

The question was which **rules** create an edge, not which chart patterns. This one starts from a
rule. Binance's USDⓈ-M perpetuals settle funding every 8 hours, at 00:00, 08:00 and 16:00 UTC:
whoever holds a position at that instant pays, or receives, position × rate. When the rate is
high, holding a long through the instant costs money, and two groups trade around it:

- **longs who will not pay**: they close shortly before the settlement and reopen after it
- **arbitrageurs who collect it**: they open a short just before and close it just after

Both sell into a settlement where longs pay and buy after it, and do the reverse where shorts
pay. So the rule predicts **a dip into a high-funding settlement and a rebound after it**,
mirrored when funding is negative. It says who trades, when, and why. It is the same rule that
pays #12's carry, seen from the price side.

The rule also bounds the effect: a swing much larger than the funding plus fees would pay
arbitrageurs to lean against it. A small effect is expected; the test asks whether it exists at
all, and whether a long-only spot trade can collect it after costs.

## Data — fixed

- **Venue**: Binance USDⓈ-M perpetuals, the largest perp venue, whose funding history is public
  back to 2019 (`/fapi/v1/fundingRate`).
- **Coins**: the 42 coins of `espero/xs.py::UNIVERSE`. Perpetuals `{COIN}USDT`, except SHIB
  (`1000SHIBUSDT`); spot `{COIN}USDT`, including `SHIBUSDT`. Today's list: survivorship disclosed.
- **Period**: settlements from **2020-01-01 00:00 to 2026-09-30 16:00 UTC**, the last full month in
  the price archive.
- **Prices**: Binance's public archive (data.binance.vision), monthly **1-hour** klines for the
  perpetual (where the funding flows trade) and for spot (what a long-only account buys).
- Downloads are cached in `data/settle/` (not committed); the event table, the output and a
  manifest of what was missing are committed (`research/settle_events.csv`, `settle_run.txt`,
  `settle_manifest.json`). A missing file or symbol is recorded, never substituted; other download
  errors stop the run, to be fixed and rerun before any number is printed.

## Events — frozen

- **A settlement**: coin *i* at time *T* (Binance's `fundingTime`, rounded to the hour) whose
  previous settlement was exactly **8 hours** earlier. Coins and times on 4-hour or 1-hour
  intervals are left out.
- **The signal is the previous rate, f_prev**: the rate settled at *T* − 8h, known in full 8 hours
  before *T*. (The rate settling at *T* is partly set by the last hour's prices, so it is
  information only.)
- **Groups**: **high** if |f_prev| ≥ **0.05%** per settlement, above a maker round trip, so avoiding
  or collecting the payment pays; **baseline** if |f_prev| ≤ **0.0125%**, the default 0.01% and
  near zero, where nobody gains by trading around it. *d* = sign(f_prev) for high events: +1 when
  longs pay.
- **Windows** on hourly **perpetual** bars: pre = log(close ÷ open) of the bar [*T*−1h, *T*);
  post = the same for [*T*, *T*+1h); swing = post − pre.
- **Placebo**: the same windows around *T*+4h, the middle of the interval where nothing settles,
  so the bars [*T*+3h, *T*+4h) and [*T*+4h, *T*+5h). The coin's next settlement must be at *T*+8h.
- **Excess**: at each *T*, B(*T*) = the mean swing of that hour's baseline coins (at least 3 with
  bars), and e(*T*) = *d* × (swing − B(*T*)). At *T*+4h the same, with the same baseline coins.
- **The primary quantity**, per high event: **g = e(*T*) − e(*T*+4h)**, settlement minus placebo.
  Comparing with baseline coins at the same hour removes moves that hit every coin; comparing with
  the same coin 4 hours later removes anything about high-funding coins that is not the settlement.

## Evaluation — fixed

Each UTC day's mean of g over its high events is one observation, so events that move together
on one day count once: t = mean ÷ (sd ÷ √days).

**PASS requires all four:**

1. **The settlement moves prices**: mean g > 0 and **t ≥ 3**.
2. **In the predicted shape**: at *T*, the excess pre-window move against the paying side, mean of
   *d* × (pre − baseline pre) **< 0**, and the excess rebound after it, mean of *d* × (post −
   baseline post) **> 0**.
3. **Not one era**: mean g > 0 in each half (2020-01 → 2023-04 and 2023-05 → 2026-09).
4. **A long-only spot trade pays**: at least one leg earns a mean return **above 18 bps** (two
   Hyperliquid taker round trips, as #18) with day-clustered **t > 2**, on spot bars, raw returns:
   - (a) **after the longs paid**: f_prev ≥ +0.05%: buy spot at *T*, sell at *T*+1h
   - (b) **into the short cover**: f_prev ≤ −0.05%: buy spot at *T*−1h, sell at *T*

**Information only, cannot change the verdict:**

- g by funding bucket: 0.05–0.1%, 0.1–0.2%, 0.2% and above
- grouping on the settling rate instead of f_prev
- the placebo e(*T*+4h) alone; g on spot instead of perpetual bars; 2-hour windows
- both legs net of a Binance.US (4 bps) and a Hyperliquid (9 bps) taker round trip
- event counts by year and by the sign of funding

## Outcomes — fixed now

- **PASS**: `research/FORWARD_SETTLE.md` is written before anything trades on it, then a paper loop
  that alerts on high-funding settlements and books the passing leg on spot prices.
- **Criteria 1–3 hold, 4 fails**: "real, not tradable after costs". Reported; nothing ships.
- **Anything else: FAIL.** Nothing is re-tuned on this data: another threshold, window, venue or
  period is a new document.

## Known confounds

- **f_prev stands in for the rate traders watch.** Binance shows a running estimate of the rate
  that will settle; funding is persistent, so the previous rate is a close proxy, and its noise can
  only weaken the test.
- **Clock hours.** 00:00, 08:00 and 16:00 UTC are also session times (Asia, Europe, the US
  afternoon). Baseline coins at the same hour remove effects common to all coins; the 4-hour placebo
  removes effects particular to high-funding coins at any hour. An effect particular to
  high-funding coins at those clock hours, but not about funding, would survive both.
- **Hourly bars** blur an effect that lives in the last minutes before the settlement.
- **High funding comes in manias** (2021, early 2024), so the halves criterion matters.
- **Survivorship**: October 2026's list.
- **The swing is bounded by arbitrage** (roughly the funding plus fees), so criterion 4 is demanding
  by design: at 0.05% funding the expected swing is a few basis points.

## Transparency — what was seen before this commit

- Response codes only for the archive's 1-hour files: BTCUSDT 2020-01 and 2026-09 (perpetual and
  spot), SHIBUSDT spot and 1000SHIBUSDT perpetual 2026-09, EOSUSDT perpetual 2022-01. The funding
  endpoint's first three BTCUSDT rows (2019-09-10, each 0.01%), and the size of an EOSUSDT response.
- #18's downloads (Binance perpetual 1-minute bars around the first day of each month, 2020–2026)
  are on disk; no return around a funding time has been computed from them.
- #11, #12 and #14 used Hyperliquid's and Kraken's funding; their results, and general knowledge of
  typical funding levels, were known.

## The multiple-testing note

Twentieth test; three thin passes, all risk construction or carry. This is the first test chosen
by asking which rule forces someone to trade, which is a reason to test it, not to expect a pass.
The t ≥ 3 hurdle is kept, and the test runs once.

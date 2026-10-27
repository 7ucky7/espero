# Pre-registration — post-earnings announcement drift (PEAD)

Committed **before** any filing, price or event was fetched for this test. Hypothesis #5.

## Why this hypothesis

PEAD is one of the oldest documented anomalies: after an earnings surprise, the price keeps drifting
in the direction of the surprise for weeks (Ball & Brown 1968; Bernard & Thomas 1989). It is:
- **slow** — the drift lasts weeks, so retail latency does not kill it
- **event-defined** — there is a timestamp, not a vibe
- **testable without a data vendor** — SEC filings give the exact public moment

It is the one news-driven idea in this repo that has a real prior and a free point-in-time source.

## Data — exact sources

| what | source | why |
|---|---|---|
| event + timestamp | SEC EDGAR `submissions/CIK##########.json`, 8-K with item **2.02** | `acceptanceDateTime` is the moment the filing became public, not when we read it |
| prices | Yahoo chart API, daily OHLCV | free, long history |
| universe | 60 large-cap US names, fixed list compiled at commit time | see confounds |

**No consensus-EPS data is used.** The signal is the market's own reaction, which is a legitimate
proxy for surprise and avoids a paid vendor.

## The rule — frozen

**Event**: an 8-K filing with item `2.02` accepted on date *t*.

**Reaction day** (uses the acceptance timestamp, in US/Eastern):

- accepted **before 09:30** → reaction day is *t*
- accepted **at or after 16:00** → reaction day is the next trading day
- accepted **between** → reaction day is *t* (partial session, treated as same day)

**Signal**: `reaction = close(reaction_day) / close(previous trading day) − 1`.

**Entry filter**: `reaction ≥ +3.0%` (long-only; a large positive surprise proxy).

**Entry**: at the **open of the trading day after the reaction day**.

**Exit**: at the **close of the 40th trading day** after entry, or at the next eligible entry if the
position cap forces it. No stops.

**Portfolio**: equal weight, **maximum 5 concurrent positions** (20% each), remainder in cash. If more
than five signals fire, take the five largest reactions.

**Costs**: **10 bps per side**.

No parameter above is tuned after results are seen.

## Evaluation — fixed in advance

**Periods**

- design/dev: **2010-01-01 → 2020-12-31**
- **holdout: 2021-01-01 → 2026-10-27**

**Metrics**: CAGR, Sharpe (daily, rf=0), max drawdown, number of trades, win rate, average trade.

**Benchmark**: SPY buy-and-hold over the same window.

**PASS requires all three on the holdout:**

1. Sharpe > SPY Sharpe
2. CAGR > 0 net of costs
3. at least **30 closed trades** (otherwise the sample is too small to say anything)

## Known confounds, stated up front

- **Survivorship.** The 60 names are chosen in 2026 from companies that still exist. This biases
  absolute returns upward. It does *not* fully bias the PEAD effect, which is relative to each stock's
  own pre-event close, but it is a real limitation.
- **Coverage.** Not every company files item 2.02 for every quarter; some use 8-K item 8.01 or file
  late. Missing events are missing at random, not selected on outcome.
- **Reaction is not surprise.** A 3% move may be noise, guidance, or a sector move. Consensus-EPS
  surprise would be cleaner and is not available free.
- **Long-only.** The classic effect is symmetric; this version only buys positive surprises.
- **Concentration.** 5 positions at 20% is far riskier than the six-asset trend book. A single bad
  earnings gap hurts.
- **Fifth hypothesis.** Four have been tested; three failed, one passed thinly. A pass here is weaker
  evidence than it looks.

## What a pass would mean

Paper trade it, 90 days, no capital — same gate as TSMOM. At $500, 20% position sizing means $100 per
name; that is enough to feel the mechanics and not enough to matter financially.

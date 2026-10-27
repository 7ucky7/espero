# Pre-registration — cross-sectional momentum among large-cap crypto

Committed **before** the data was fetched or any result was computed. This document is the contract;
`research/RESULTS.md` records the outcome against it.

## Why this hypothesis

Crypto momentum is one of the few factors with a published prior rather than a chart story (it appears
in the academic asset-pricing literature for crypto, and in time-series momentum across asset classes
more broadly). It is also testable with data this machine can reach, needs no funding rates, no
sentiment, and no leverage. Being well-known is acceptable: a prior that others have found is a
feature, not a bug. Being already arbitraged away is the risk, and the holdout is designed to detect it.

## The rule — frozen

**Universe** (9 Coinbase USD spot pairs): BTC, ETH, SOL, LINK, ADA, XRP, DOGE, LTC, AVAX.

**Eligibility**: on a rebalance date, a coin must have at least **365 daily closes** available. This
prevents newly listed coins from winning the ranking on a few days of price history.

**Signal**: 30-calendar-day total return, computed from daily closes, ending on the close of the day
before rebalance.

**Rebalance**: weekly. Decision after the Sunday close; execution at the **Monday open**.

**Position**: long exactly the top-ranked eligible coin, **100% of equity**, if and only if its 30-day
return is **> 0**. Otherwise hold cash. One position at a time, no leverage, no shorting, no stops.

**Costs**: **10 bps per round trip** (5 bps per side), charged on every switch. Staying in the same coin
costs nothing. First entry costs 5 bps.

**No parameters are tuned.** 30 days, weekly, 365-day eligibility, and the >0 filter are fixed here and
will not be changed after seeing results.

## Evaluation — fixed in advance

**Periods**

- design/dev: 2020-01-01 → 2023-12-31
- **holdout: 2024-01-01 → 2026-10-27** (not looked at until the rule above was committed)

**Metrics**: CAGR, annualised Sharpe (daily returns, rf = 0), max drawdown, Calmar, switches per year,
percentage of weeks in market.

**Benchmark**: BTC buy-and-hold over the same window, entry cost applied.

**PASS requires all three, measured on the holdout:**

1. Sharpe greater than BTC buy-and-hold over the holdout
2. max drawdown shallower than BTC buy-and-hold over the holdout
3. positive CAGR net of costs over the holdout

Anything else is FAIL. A failure is not re-tuned on this data: a new hypothesis requires a new
pre-registration and a holdout that has not been used.

Cost sensitivity at 4 bps and 30 bps will be reported for information only — it cannot change the pass
or fail verdict.

## Known confounds, stated up front

- **Survivorship bias.** The universe is chosen in 2026 from coins that survived. This biases results
  upward and cannot be fully corrected with Coinbase data.
- **Delistings are absent**, so failed coins never appear in the ranking.
- **10 bps is an assumption.** It approximates Binance.US taker plus slippage; Coinbase retail would be
  far worse, which is itself part of the finding.
- **One asset class.** A single market regime family, so a pass would still not be a law.
- **Monday-open execution** assumes the process runs; it does not model a missed rebalance.

## What a pass would and would not mean

A pass would justify paper trading this rule with the existing harness, three months, no money. It
would **not** justify live capital: nine assets, one class, ~330 weekly rebalances total, and a
survivorship-biased universe are enough to falsify a bad idea and not enough to confirm a good one.

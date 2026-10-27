# Pre-registration — cross-asset time-series momentum

Committed **before** any of these series were fetched or tested. This is hypothesis #4 in this repo;
see the multiple-testing note at the bottom.

## Why this hypothesis

Time-series momentum — an asset's own trailing return predicting its next return — is one of the most
documented anomalies across asset classes (Moskowitz, Ooi & Pedersen, *Time Series Momentum*, JFE 2012;
Hurst, Ooi & Pedersen, *A Century of Evidence on Trend-Following Investing*). Unlike the previous three
hypotheses, it does **not** depend on one venue's microstructure or one market's regime, and it is the
first idea in this repo that actually needs the expanded data layer.

It is also long-only-implementable, low-turnover, and needs no leverage — which matters at $500.

## Universe — fixed

| asset | instrument | venue | why |
|---|---|---|---|
| US equities | **SPY** | Alpaca/IBKR | index proxy, no survivorship |
| long bonds | **TLT** | Alpaca/IBKR | the 2022 test case |
| gold | **GLD** | Alpaca/IBKR | crisis asset |
| oil | **USO** | Alpaca/IBKR | the commodity leg you asked about |
| bitcoin | **BTC-USD** | Yahoo series | 24/7, high trend persistence |
| ether | **ETH-USD** | Yahoo series | second crypto asset |

**Eligibility**: an asset enters the universe on a rebalance date only if it has at least **252 daily
closes** of history. BTC and ETH therefore join years after the start.

**Excluded on purpose**: leveraged and inverse ETFs (their returns are path-dependent and would
flatter any trend rule), single stocks, and anything with less than five years of history.

## The rule — frozen

- **Signal**: 252-trading-day total return, computed on daily closes.
- **Decision**: at the close of the last trading day of each month.
- **Execution**: at the **next month's first trading day open**.
- **Position**: equal weight across every eligible asset whose 252-day return is **> 0**, capped at
  **1/6 of equity each**; the remainder sits in cash. No shorting, no leverage, no stops.
- **Rebalance**: monthly. Only the weights that change are traded.
- **Costs**: **10 bps per side** on every trade (spread + slippage; commission-free ETFs assumed).

No parameter in this list will be changed after the results are seen.

## Evaluation — fixed in advance

**Periods**

- design/dev: **2010-01-01 → 2020-12-31**
- **holdout: 2021-01-01 → 2026-10-27** (not looked at before the rule above was committed)

**Metrics**: CAGR, annualised Sharpe (daily returns, rf = 0), max drawdown, Calmar, average number of
positions, turnover per year.

**Benchmark**: equal-weight buy-and-hold of the same eligible universe (rebalanced monthly, same costs).
Secondary: 60/40 SPY/TLT.

**PASS requires all three on the holdout:**

1. Sharpe > equal-weight benchmark
2. max drawdown shallower than the benchmark
3. CAGR > 0 net of costs

## Known confounds, stated up front

- **Long-only.** The literature's version shorts negative-trend assets; this one goes to cash. That
  halves the opportunity set and will understate the documented effect.
- **Six assets, one monthly clock.** A pass is evidence, not proof.
- **ETF proxies.** USO bleeds contango, so "oil trend" here is partly a roll-cost trend.
- **Multiple testing.** This is the fourth hypothesis in this repo. At four independent tests, one
  nominal 5%-level pass is roughly what chance alone would produce. A pass here therefore warrants
  paper trading, not capital.
- **Regime.** The holdout contains a bond bear market and a crypto bull/bear cycle; that is good for a
  trend test, but it is still one path.

## Multiple-testing note

Hypotheses so far: funding extremes (fail), cross-sectional crypto momentum (fail), Polymarket liquidity
provision (fail). Each was recorded before its result. The fifth hypothesis — if there is one — should
raise the bar further, not lower it.

## What a pass would mean

Paper trade it through the existing harness for 90 days: monthly rebalances, six assets, $500 notional.
It would **not** mean live capital, and it would not mean $15/day — at $500 an 8%/yr edge is $0.11/day.
It would mean the research process finally produced something worth running at size.

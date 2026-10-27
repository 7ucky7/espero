# Pre-registration — crypto-policy odds as a signal

Committed **before** the market basket was enumerated or any odds fetched. Hypothesis #6.

## Hypothesis

The implied probability of **crypto-policy events** on Polymarket carries information that spot price
does not. When the crowd's belief that something policy-positive will happen rises over a week, BTC's
next 20 days are better than when it falls.

This is deliberately **not** about price-level markets ("BTC above $100k"), whose odds are derived from
the underlying and would be circular.

## Data — exact sources

| what | source |
|---|---|
| event odds | Polymarket Gamma search + CLOB `prices-history`, daily fidelity |
| BTC price | Yahoo `BTC-USD` daily |
| market metadata | Gamma `public-search`, `closed` included (resolved markets stay queryable) |

## Basket construction — mechanical, fixed now

Search terms (all of them, no others): `bitcoin etf`, `crypto regulation`, `crypto bill`,
`sec crypto`, `bitcoin reserve`, `stablecoin bill`, `crypto tax`.

A market is **included** if:

- the question contains a crypto term: `bitcoin`, `btc`, `crypto`, `ethereum`, `stablecoin`
- **and** a policy term: `etf`, `regulation`, `bill`, `law`, `sec`, `approval`, `ban`, `reserve`,
  `tax`, `legislation`, `congress`
- **and** it is not a price-level market: no `above $`, `hit $`, `between $`, `close at`, `price`
- **and** it has at least **30 daily observations** before resolution

Excluded on purpose: airdrops, IPOs, price targets, sports, elections (election odds are a separate
hypothesis and would contaminate the basket).

The qualifying list will be enumerated by the rule above and frozen in `research/odds_basket.json`
before any return is computed.

## The signal — frozen

For each date *t*:

- let `S_t` = markets with an observation at both *t* and *t − 7*
- `Δ_t = mean(p_t − p_{t−7})` over `S_t`
- if `|S_t| < 3`, there is **no signal** that day

`Δ_t > 0` means the crowd's policy probability rose over the week.

## Trading rule — frozen

- `Δ_t > 0` → long BTC from the next day's open for **20 trading days**
- otherwise → cash
- no overlapping positions; **10 bps per side**

## Evaluation — fixed in advance

**Periods**

- design/dev: **2022-01-01 → 2024-12-31**
- **holdout: 2025-01-01 → 2026-10-27**

**Statistics**

1. Spearman correlation between `Δ_t` and BTC's forward 20-day return, in each period
2. Forward 20-day return by quintile of `Δ_t` (is it monotone?)
3. The trading rule's CAGR / Sharpe / max DD vs BTC buy-and-hold

**PASS requires all three on the holdout:**

- Spearman > 0
- top-quintile minus bottom-quintile forward return > 0
- strategy Sharpe > BTC Sharpe

## Known confounds, stated up front

- **Small N of events.** The basket may contain 5–20 distinct questions; a pass would rest on a handful
  of policy episodes and would be fragile.
- **Co-movement, not prediction.** News moves odds and price together. A positive correlation could be
  simultaneity, not forecasting.
- **Composition drift.** Markets enter and leave; the matched 7-day sample mitigates but does not
  eliminate this.
- **Thin books.** A $700 market's odds can move 10 points on a $50 trade; the "crowd" may be one person.
- **Selection.** The search terms were chosen by me, today. They are frozen in this document, but they
  are not exhaustive.
- **Sixth hypothesis.** Two passes out of six would still be roughly chance at the 5% level.

## What a pass would mean

Not capital. It would mean the odds feed is worth wiring into the TSMOM book as a **filter or a second
signal** — and that would itself need a separate pre-registration, because combining two signals after
one passes is how the multiple-testing bill comes due.

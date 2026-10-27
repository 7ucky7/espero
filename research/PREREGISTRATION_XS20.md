# Pre-registration — cross-sectional crypto momentum, top 5 of 21

Committed before the run. Hypothesis #7 — and the first one where I have to admit the historical data
is already contaminated.

## The contamination, stated first

The 9-coin / top-1 version of this hypothesis was tested on **2024–2026** and failed. Any top-5 variant
run on the same window is not independent evidence — the window has been seen, and the rule differs in
a way chosen with that knowledge.

So this document separates two things:

- the **historical run** is *exploratory*: it shows the shape, it cannot pass anything
- the **forward paper trade** is the actual test

## Universe — fixed

21 coins with ≥5 years of Yahoo history: BTC, ETH, LTC, XRP, BCH, ADA, LINK, XLM, ETC, ZEC, DASH, EOS,
XTZ, ATOM, ALGO, FIL, AAVE, MKR, DOGE, SOL, AVAX.

Eligibility on a rebalance date: **≥365 daily closes**.

**Survivorship bias is severe here and is disclosed, not fixed.** These are coins that exist in 2026.
The ones that died — and cross-sectional momentum would have bought several — are absent. Every number
below is therefore an upper bound.

## The rule — frozen

- **Signal**: 30-calendar-day return, computed on daily closes
- **Rebalance**: monthly, first trading day, at the open
- **Portfolio**: long the **top 5** eligible coins by 30-day return, **20% each**, fully invested
- **No cash filter**, no trend overlay, no stops — this is pure cross-sectional momentum
- **Costs**: **10 bps per side** (Binance.US taker + slippage), stress-tested at 30 bps

## Historical run — exploratory only

- window: **2023-01-01 → 2026-10-27** (2021-10 start leaves too little design data)
- reported metrics: CAGR, Sharpe, max DD, turnover, vs BTC and vs equal-weight universe
- **cannot pass**, by construction

## Forward test — the actual criterion

Starting at the **next rebalance after this commit**, paper-traded for **6 months**:

- rule: top 5 of 21, monthly, 10 bps
- PASS: net return > 0 **and** Sharpe > BTC over the same window
- with ~6 monthly rebalances and 30 names-of-positions, a pass is still weak — it would justify
  continuing, not capital

## Known confounds

- **Survivorship**: only coins that survived to 2026 exist in the data.
- **Contamination**: 2024–2026 has been used for a related rule.
- **Short window**: 2021-10 onward; no full cycle.
- **Fees**: 10 bps assumes a venue you may not have access to; Coinbase would be 120 bps and a
  guaranteed loss.
- **Seventh hypothesis**: seven tests, two passes would be unremarkable at the 5% level.

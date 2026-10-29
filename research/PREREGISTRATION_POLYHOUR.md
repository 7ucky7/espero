# Pre-registration — Polymarket's hourly bitcoin crowd against a random walk (#37)

Committed before any Polymarket price is fetched for this test. Paper and research only: Polymarket
restricts US persons. The thirty-eighth test in this repo.

## Why

Polymarket runs a market every hour: "Bitcoin Up or Down". It resolves Up if Binance's BTC/USDT
1-hour candle closes at or above its open. Halfway through the hour, the fair chance of Up follows
from two things: how far BTC has moved since the open, and how much it moves in the half hour left.
That is a binary option, and a random walk prices it in one line.

Retail crowds chase moves and like round odds. If the crowd's price strays from the random walk, and
the random walk is right more often, the gap is an edge **in the prediction market itself**. It is
a different mechanism from the forced flows tested here so far: crowd mispricing, not forced
trading. Idea 8 in [IDEAS_NOVEL.md](IDEAS_NOVEL.md).

## Data — fixed

- **Markets**: every hourly event `bitcoin-up-or-down-{month}-{day}-2026-{hour}{am|pm}-et` from
  **2026-05-01 → 2026-10-27**, read from Polymarket's public Gamma API: the outcome from
  `outcomePrices`, and the "Up" token id.
- **The crowd's price**: Polymarket's public CLOB `prices-history` for the Up token, 1-minute fidelity,
  over the hour. Fetched once, cached in `data/polymarket/` (not committed).
- **A missing market is recorded, never substituted.**
- **BTC**: Binance USDⓈ-M 5-minute bars from #28's and #30's caches. They are not the spot pair the
  market resolves on, but the perpetual and spot track within basis points.

## The rule — frozen

For each market (the hour starting at H:00 ET):
- **The crowd**: p = the last price of Up at or before H:30. It must lie within the 2 minutes before
  H:30; a staler price skips the market.
- **The model**: q = Φ( ln(P₃₀ / P₀) / (σ · √30) ).
  - P₀ is the open of the 5-minute bar at H:00 and P₃₀ the open of the bar at H:30.
  - σ is the per-minute volatility: the standard deviation of the 288 five-minute log returns
    before H:00, divided by √5.
- **The bet**: when |q − p| ≥ **0.05**, buy the side the model favours at the crowd's price.
  - Up: profit = outcome − p.
  - Down: profit = p − outcome.
  - Each bet pays a **cost of 0.01** per $1 share, for the spread on a thin book.

## Evaluation — fixed

Each UTC day's mean profit per bet is one observation.

**PASS requires all three:**

1. **It pays**: mean profit per bet **> 0, t ≥ 3**.
2. **Not one stretch**: > 0 in each half (May–July, August–October).
3. **The model is the better forecaster**: over every market with both, the Brier score of q is below
   the Brier score of p.

**Information only:**
- thresholds of 0.03 and 0.10;
- minutes 15 and 45;
- a cost of 0.02;
- the crowd's lean at the hour's start (p at H:00 against 0.5), set against the previous hour's BTC
  move and the outcome (do they chase?);
- by hour of day;
- Polymarket volume of the markets bet on.

## Outcomes — fixed now

- **PASS**: a document on what a paper strategy would need: depth at the quoted price, fees, and
  whether US access exists at all. Nothing trades.
- **Anything else: FAIL.**

## Known confounds

- **Thin books**: about $13,000 of volume per market (one sampled). A last trade is not a fill; the
  1-cent cost is the allowance, and it may be too small.
- **Fat tails**: a random walk with a 24-hour σ underprices big moves. If the crowd prices them
  better, criterion 3 says so.
- **Fees**: Polymarket's fee schedule on these markets may differ from zero; not modelled.

## Transparency — what was seen before this commit

Three markets' metadata (October 2025, October 2026) to confirm the slugs, the resolution rule and
the shape of the price history: 120 points in one market's last two hours, values not examined.
No market's price has been set against BTC or its outcome.

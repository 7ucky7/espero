# Result — crypto-policy odds as a signal

**Verdict: FAIL.** The rank correlation is +0.024 — statistically indistinguishable from zero — and the
quintile spread runs the wrong way. The trading rule's +24.7% is 16 trades of noise, not evidence.

Spec: [PREREGISTRATION_ODDS.md](PREREGISTRATION_ODDS.md) (`509fb20`). Basket: `odds_basket.json`.
Code: `odds_signal.py`.

## What was built

- **76 markets** qualified under the frozen rule (crypto term + policy term, no price-level markets).
- **17** had ≥30 daily observations and formed the panel.
- Panel: 901 days, 2023-12-02 → 2026-10-27. **432 signal days**, 422 with a forward return.

## Results

| period | n | Spearman | Q1 mean | Q5 mean | Q5−Q1 |
|---|---|---|---|---|---|
| design 2022–2024 | **0** | — | — | — | — |
| holdout 2025–2026 | 422 | **+0.024** | +2.06% | +1.21% | **−0.85%** |

| pass criterion | required | actual | met |
|---|---|---|---|
| Spearman > 0 | > 0 | +0.024 | yes, numerically |
| Q5 − Q1 > 0 | > 0 | −0.85% | **no** |
| strategy Sharpe > BTC | > BTC | not reached | — |

The rule itself: 16 trades, +24.66% vs BTC −15.68% over the holdout, 38% win rate. With 16 trades
and a zero rank correlation, that is a small-sample artefact — three good trades carry it.

## The design flaw, disclosed

**The design period was empty.** Polymarket's CLOB price history for these markets begins
2023-12-02, so there is no data for 2022–2024 as the pre-registration assumed. I should have checked
data availability *before* fixing the periods; instead the test effectively ran on the holdout only,
with no design/holdout separation.

That does not rescue the result — a near-zero correlation on 422 observations is a near-zero
correlation — but it does mean the test was underpowered relative to its design.

## Why it likely fails

1. **The basket is not one thing.** "Bitcoin ETF approved" and "crypto tax repealed" are different
   hypotheses with different actors; averaging them produces a number with no clear meaning.
2. **Co-movement.** Policy odds and BTC price both react to the same news. A positive correlation would
   be simultaneity; a zero correlation suggests the odds add nothing beyond the news itself.
3. **Thin markets.** Several qualifying markets had a few hundred dollars of liquidity — the "crowd" may
   be one market maker, and the odds move for inventory reasons, not information.
4. **Composition drift.** 17 markets over 900 days with entries and exits; the matched 7-day sample
   helps but the composite is not stable.

## What this retires

- The idea that a **composite policy-odds index** is a usable directional signal for BTC, at least in the
  window where data exists.
- The shortcut of "sentiment from prediction markets" as a general-purpose feature.

## What it does not retire

- **Single-event** odds as a filter (e.g. only ETF-approval markets, tested alone).
- **Cross-venue** disagreement between Polymarket and Kalshi on the same event.
- Prediction-market **arbitrage** (monotonicity, mutually exclusive sums) — a different mechanism
  entirely.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 1 | Funding extremes | fail |
| 2 | Cross-sectional crypto momentum | fail |
| 3 | Polymarket liquidity provision | fail |
| 4 | Cross-asset TSMOM | **pass (thin)** |
| 5 | PEAD, large/small cap | fail |
| **6** | **Crypto-policy odds composite** | **fail — Spearman +0.02** |

# Result — top-5-of-21 crypto momentum (exploratory)

**Not evidence, by construction.** The window is contaminated (a related rule already used it) and the
universe is survivorship-biased. This run exists to show the shape before the forward paper trade.

Spec: [PREREGISTRATION_XS20.md](PREREGISTRATION_XS20.md). Code: `xs20.py`.

## Numbers

| | CAGR | Sharpe | max DD |
|---|---|---|---|
| **XS20** (top 5 of 21, monthly, 10 bps) | +42.39% | 0.86 | −55.65% |
| XS20 at 30 bps | +37.97% | 0.81 | −56.47% |
| BTC buy & hold | **+50.67%** | **1.12** | −53.06% |
| Equal-weight all 21 | +38.64% | 0.83 | −61.10% |

Window 2023-01-01 → 2026-10-27, 46 monthly rebalances.

## What it says

**Selection added almost nothing.** Top-5 over equal-weight: **+3.75pp CAGR and +0.03 Sharpe.** That is
the entire contribution of ranking 21 coins by 30-day return — inside noise, and it comes with a 56%
drawdown.

**BTC beat it on every dimension** — more return, better Sharpe, smaller drawdown. In this window,
picking the hottest five coins was strictly worse than doing nothing.

**The drawdown is the story.** −56% peak-to-trough. At $600 that's $264 gone, and the rule gives no
mechanism to stop it. The TSMOM book's −8% came from having cash and a trend filter; this has neither.

## Why the breadth argument didn't show up

Chinese quant works because 400 names × 250 days × a 0.05% edge compounds. Here: 5 positions × 12
rebalances × an unknown edge, on 21 survivorship-selected coins. That's not breadth — it's five bets a
month. The statistical power of the Chinese version comes from *thousands* of independent observations
per year, and we have sixty.

## What happens now

The forward paper trade (6 months, 10 bps, top 5 of 21) is the only clean test left, per the
pre-registration. It hasn't started — it needs a monthly rebalancer for this rule, which the current
paper account doesn't implement (that one is TSMOM).

Until then, the honest status: **exploratory, no demonstrated edge, worse risk than holding BTC.**

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 1 | Funding extremes | fail |
| 2 | XS momentum, 9 coins top-1 | fail |
| 3 | Polymarket LP | fail |
| 4 | Cross-asset TSMOM | **pass (thin)** |
| 5 | PEAD | fail |
| 6 | Crypto-policy odds | fail |
| 7 | XS momentum, 21 coins top-5 | exploratory — selection ≈ equal-weight, loses to BTC |

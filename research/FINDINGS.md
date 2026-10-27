# Findings — funding-rate extremes

**Status: unproven. Do not trade it.** This document exists because the first result looked good and
the follow-up did not, and the negative result is the more useful one.

## What was tested

Hypothesis: when perpetual funding is extremely negative (shorts crowded, shorts paying longs), the
next day's return is positive — a short-squeeze.

Frozen rule:

- signal: funding z-score below −2 (causal 30-day window)
- entry: next bar's open · exit: the close `hold` days later
- costs: 2 × 4 bps
- selection period: 2023-05 → 2024-12 · holdout: 2025-01 → 2026-10

## First look — Hyperliquid funding, holdout only

| | n | total | max DD | win | profit factor | t |
|---|---|---|---|---|---|---|
| BTC, hold 1d | 38 | **+28.62%** | −8.76% | 63% | 2.45 | 1.77 |
| BTC, hold 3d | 34 | +29.47% | −9.21% | 65% | 2.28 | 1.21 |
| ETH, hold 1d | 43 | **+28.23%** | −20.66% | 51% | 1.71 | 1.13 |
| ETH, hold 3d | 40 | +0.33% | −25.90% | 45% | 1.08 | 0.18 |

Buy & hold over the same window: BTC −15.1%, ETH −30.7%.

Looked like a genuine edge on two assets, in a period when holding lost money.

## Why it fell apart

**1. The selection period had nothing.** Same rule, 2023-05 → 2024-12:

| | n | total | win | t |
|---|---|---|---|---|
| BTC | 18 | +1.53% | 50% | 0.28 |
| ETH | 18 | −6.84% | 50% | −0.86 |

The edge existed only in the holdout window. That is the signature of a regime effect, not a law:
2025–26 was choppy-to-down, where buying panic pays. A trending bull or a real crash is a different
test.

**2. BTC and ETH are not independent tests.** They share a beta and a regime. Two correlated assets
agreeing is one observation, not two.

**3. The long history does not confirm it.** Deribit funding (the only free source here with depth),
hourly, 2019-04 → 2026-10, 8h-window-equivalent z-score, same rule:

| period | n | total | max DD | win | t |
|---|---|---|---|---|---|
| 2019 | 2 | −10.12% | −5.82% | 0% | — |
| 2020 | 2 | +8.67% | 0.00% | 100% | — |
| 2021 | 2 | −7.97% | 0.00% | 50% | — |
| 2022 | 8 | +10.61% | −1.67% | 50% | 1.04 |
| 2023 | 2 | +9.05% | 0.00% | 100% | — |
| 2024 | 2 | +2.63% | −0.04% | 50% | — |
| 2025 | 4 | +4.72% | −1.04% | 75% | — |
| 2026 | 3 | +0.62% | −1.13% | 67% | — |
| **all** | **25** | **+17.24%** | **−8.39%** | **60%** | **0.91** |

25 trades in 7.5 years, t = 0.91, against +636% for buy & hold. No evidence of edge.

**4. Funding is venue-specific, which breaks the threshold.** Deribit's hourly funding has a standard
deviation 8× larger than Hyperliquid's (2.27e-4 vs 2.8e-5) and much fatter tails. A fixed z < −2 cut
fires ~3 times a year on one venue and ~17 times a year on the other. The "signal" is partly a
property of how each exchange computes funding, not of the market.

A venue-agnostic version (bottom 2% of the trailing 30-day distribution) fired ~190 times a year and
returned +12% over 7.5 years with a −73% drawdown. That is noise with costs.

## What would change the verdict

- a threshold defined on a robust scale (median/MAD) rather than mean/σ, so heavy tails do not inflate
  the denominator
- a per-venue calibration, tested on each venue's own history
- conditioning on regime (trend filter) tested as a pre-registered hypothesis, not discovered after
  the fact
- more than one truly independent asset class

## The lesson worth keeping

The first table in this document is what a backtest looks like when it is right by accident, and it is
exactly what would have justified a live order. The second table is why the rule in this repo is
"a fill happens after the signal" and "features carry the time they could first be read" — and why
none of that is sufficient on its own. A clean pipeline still needs a sample that can say no.

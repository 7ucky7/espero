# Result — cross-asset time-series momentum

**Verdict: PASS, by a thin margin, on the pre-registered criteria.** First hypothesis in this repo to
survive its holdout. It is a risk result, not an income result.

Spec: [PREREGISTRATION_TSMOM.md](PREREGISTRATION_TSMOM.md) (committed `c1502c3`, before the data was
fetched). Code: [tsmom.py](tsmom.py). One run.

## Headline

| period | | CAGR | Sharpe | max DD | total |
|---|---|---|---|---|---|
| design 2010–2020 | TSMOM | +1.00% | 0.23 | −9.21% | +11.56% |
| | equal-weight | +1.61% | 0.25 | −22.29% | +19.21% |
| **holdout 2021–2026** | **TSMOM** | **+7.26%** | **1.08** | **−8.15%** | **+50.05%** |
| | equal-weight | +8.50% | 1.02 | −14.56% | +60.47% |
| full 2010–2026 | TSMOM | +3.14% | 0.59 | −9.21% | +67.92% |
| | equal-weight | +3.94% | 0.53 | −22.29% | +91.36% |

| pass criterion (holdout) | required | actual | met |
|---|---|---|---|
| Sharpe > benchmark | > 1.02 | 1.08 | **yes** |
| drawdown shallower | > −14.56% | −8.15% | **yes** |
| CAGR > 0 | > 0 | +7.26% | **yes** |

## What kind of pass this is

**It is drawdown control, not alpha.** The benchmark made *more money* (+8.50% vs +7.26% CAGR) and the
strategy made it with **44% less drawdown**. In the design period the same pattern held: half the return,
less than half the pain.

The mechanism is visible in the yearly numbers:

```
2022: +1.6%   2023: +0.3%   2024: +6.9%   2025: +10.0%   2026: +17.8%
```

2022 was the year long bonds fell ~30% and a 60/40 portfolio had its worst year in decades. The strategy
held **+1.6%** because TLT's 252-day return was negative, so it sat in cash instead of holding the falling
bond. That is trend following doing exactly what the literature says it does — it is a crash filter that
costs you upside in melt-ups.

Behaviour: ~2.4 positions at a time out of 6, 10% turnover per month, 1–3% of months fully in cash.

## Why a pass here still does not mean money

- **The margin is noise-sized.** Sharpe 1.08 vs 1.02 over 70 monthly observations is a coin flip. The
  drawdown difference is real; the risk-adjusted-return difference is not demonstrated.
- **At $500 this is $0.10/day.** 7.26% of $500 is $36 a year. The strategy is only interesting at
  capital that doesn't exist yet.
- **Fourth hypothesis.** Three prior tests failed. One nominal pass out of four is roughly what chance
  alone produces at the 5% level, which is exactly why the pre-registration said a pass warrants paper
  trading and not capital.
- **Long-only, six assets, one path.** The literature's version shorts the negative-trend assets; this
  one goes to cash and gives up half the effect.

## What happens next, per the pre-registration

Paper trade it through the existing harness for 90 days: monthly rebalance, six assets, $500 notional,
10 bps a side. Success is that the fills, the weights and the equity curve match the simulation — not
that it makes money. Only after that would the question of real capital be worth asking.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 1 | Funding extremes | fail — 7.5-year history, t=0.91 |
| 2 | Cross-sectional crypto momentum | fail — −29.75% on holdout |
| 3 | Polymarket liquidity provision | fail — rewards < inventory loss |
| **4** | **Cross-asset time-series momentum** | **pass — drawdown control, thin margin** |

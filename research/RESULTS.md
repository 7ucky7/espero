# Result — cross-sectional momentum

**Verdict: FAIL.** All three pre-registered criteria missed on the holdout. The rule is dead as
specified and will not be re-tuned on this data.

Spec: [PREREGISTRATION.md](PREREGISTRATION.md) (committed as `474c2cc`, before any data was fetched).
Code: [momentum.py](momentum.py). One run.

## Headline

| period | strategy CAGR | Sharpe | max DD | BTC buy & hold CAGR | BTC Sharpe | BTC max DD |
|---|---|---|---|---|---|---|
| design 2020-01 → 2023-12 | **+115.27%** | **1.28** | −83.64% | +55.81% | 1.00 | −76.67% |
| **holdout 2024-01 → 2026-10** | **−29.75%** | **−0.06** | **−82.90%** | +23.30% | 0.68 | −53.08% |
| full 2020-01 → 2026-10 | +37.14% | 0.79 | −83.64% | +42.36% | 0.89 | −76.67% |

| pass criterion (holdout) | required | actual | met |
|---|---|---|---|
| Sharpe > BTC | > 0.68 | −0.06 | **no** |
| max DD shallower than BTC | > −53.08% | −82.90% | **no** |
| CAGR > 0 | > 0 | −29.75% | **no** |

Cost sensitivity, for information only (it cannot change the verdict):

| round trip | holdout CAGR | Sharpe | max DD |
|---|---|---|---|
| 4 bps | −28.78% | −0.05 | −82.52% |
| 10 bps | −29.75% | −0.06 | −82.90% |
| 30 bps | −32.90% | −0.12 | −84.14% |

**Costs are not the cause.** The strategy loses ~29% a year even at 4 bps. The signal stopped working;
the fees were never the problem.

## What happened

- **The design period is what momentum looked like in the 2020–21 alt bull.** +2,047% over four years,
  Sharpe 1.28. If the test had stopped there — or if the rule had been chosen after seeing that
  chart — it would have looked like the answer.
- **The holdout is what happened next.** 2024–26 was BTC-led, with alt-seasons that kept failing. A
  rule that always holds the single hottest 30-day coin spent those years buying tops: 28.7 switches
  per year, −29.75% a year, while simply holding BTC made +23.3%.
- **The drawdown was never acceptable, even in the good years.** −83.6% peak-to-trough in the design
  period. At 100% in one asset that is not a strategy you can sit through, which the pre-registration
  should have anticipated and did not.
- **Survivorship bias helped the strategy and it still failed.** The universe is today's survivors —
  coins that were listed and did not die. That is an upward bias, and it was not enough to rescue the
  holdout.

## Transparency

One implementation bug was found on the first execution — `KeyError` when the strategy was flat and
the script tried to mark a `None` position — and fixed before any results were printed. The rule in the
pre-registration was not modified.

## What would be a *new* hypothesis (not a retune)

Each of these must be pre-registered separately, with a holdout that has never been used:

- volatility-scaled position sizing instead of 100% in one coin (the −83% drawdown is a sizing
  failure more than a signal failure)
- a regime filter (e.g. only when the universe median is above its 200-day average), stated in advance
- equal-weight top-3 instead of top-1, to reduce single-coin luck
- a different rebalance clock (monthly), decided before looking

Adding any of them to *this* dataset and reporting the improved number would be the exact error the
pre-registration exists to prevent.

## The pattern so far

Two hypotheses, both tested honestly, both dead:

1. **Funding extremes** — looked like +28% on the holdout, died on a 7.5-year history (`FINDINGS.md`).
2. **Cross-sectional momentum** — looked like +2,047% on the design period, died on the holdout.

That is the normal yield of this process. The next one gets a new page.

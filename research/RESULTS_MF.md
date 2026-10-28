# Result — multi-factor cross-sectional crypto, vol-targeted, turnover-buffered

**Verdict: PASS on the four pre-registered criteria. It is a construction result, not a selection
result, and one of the four criteria turned out to be badly designed.** Both of those sentences are
part of the verdict.

Spec: [PREREGISTRATION_MF.md](PREREGISTRATION_MF.md) (committed `f58c3b8`, before the run). Code:
[multifactor.py](multifactor.py). Panel: 42 coins, 1,827 days from Yahoo, none failed to load, 38
eligible on the last day. One run, then one re-run after two changes that did not touch the rule
(see *Transparency*).

## Headline

| period | book | CAGR | Sharpe | max DD | turnover/yr |
|---|---|---|---|---|---|
| design 2021-10 → 2024-06 | **MF** | +9.50% | 0.64 | −15.52% | 6.5× |
| | BTC buy & hold | +2.62% | 0.32 | −76.63% | |
| | equal-weight eligible | +15.53% | 0.54 | −41.90% | 2.2× |
| **holdout 2024-07 → 2026-10** | **MF** | **+16.90%** | **0.92** | **−24.09%** | 9.5× |
| | BTC buy & hold | +10.67% | 0.45 | −53.06% | |
| | equal-weight eligible | −4.17% | 0.29 | −76.49% | 3.4× |

| pass criterion (holdout) | required | actual | met |
|---|---|---|---|
| Sharpe > BTC | > 0.45 | 0.92 | **yes** |
| max DD shallower than BTC | > −53.06% | −24.09% | **yes** |
| CAGR > 0 net of 10 bps | > 0 | +16.90% | **yes** |
| composite OOS rank IC t > 3 (5d, purged) | > 3 | 8.11 | **yes** |

At 30 bps a side: +14.71%, Sharpe 0.82, −25.18%. Costs are not the story.

## What kind of pass this is

The pre-registration asked for information-only variants precisely so this question could be
answered. Holdout, same cost:

| book | CAGR | Sharpe | max DD | turnover/yr |
|---|---|---|---|---|
| MF (composite, vol-targeted, buffered) | +16.90% | 0.92 | −24.09% | 9.5× |
| MF **plain** (same composite, equal weight, no buffer) | **−13.94%** | 0.07 | −78.16% | 57.1× |
| no ranking at all (first 10 names alphabetically), same construction | +9.45% | 0.55 | −32.46% | 2.4× |
| all eligible, vol-targeted, no buffer | +9.66% | 0.60 | −22.16% | 2.3× |
| `lowvol_30` alone, same construction | +21.42% | 1.06 | −23.20% | 4.5× |
| `mom_30` alone, same construction | +12.69% | 0.82 | −19.31% | 6.7× |
| `rev_3` alone, same construction | +4.80% | 0.35 | −21.32% | 14.9× |

Read top to bottom:

1. **The composite with plain weights loses 14% a year.** Fully invested in the top 10 and rebalanced
   weekly, the selection alone is worse than holding everything (−4%) and far worse than BTC.
2. **Ten names chosen alphabetically, with the construction, beat BTC on Sharpe and drawdown.** Vol
   targeting and the turnover buffer, applied to no signal at all, already clear criteria 1–3. The
   mechanism is the same one that made TSMOM pass: when crypto's realized vol doubles, the book
   halves, and the drawdown that follows is halved with it. Gross exposure averaged well under 50%.
3. **The composite adds about 7 points of CAGR and 0.4 of Sharpe on top of that**, which is real on
   this path but is not a demonstrated edge (one path, 121 rebalances, contaminated window).
4. **The addition is the low-vol factor.** `lowvol_30` alone does better than the composite;
   `mom_30` adds less; `rev_3` dilutes. The momentum family, which hypotheses #2 and #7 tested as
   the whole signal, has a *negative* in-sample IC and a zero out-of-sample IC in the table below.

So: like #4, this is **drawdown control first, a low-vol tilt second, and no evidence for momentum**.

## The IC table, and the flaw in criterion 4

Full window, 5-day horizon, four purged test blocks, 5-day embargo, 13 comparisons:

```
factor           IC is   t is  IC oos   ICIR  t oos   hit   Q5-Q1  churn  pass
mom_7           -0.025  -1.37  -0.016  -0.07  -2.46  0.47  +0.35%   0.28  -
mom_30          -0.041  -2.38  -0.004  -0.02  -0.59  0.51  +0.53%   0.13  -
mom_90          -0.061  -2.92  +0.008   0.03   1.04  0.52  +0.53%   0.08  -
rev_1           -0.001  -0.05  +0.018   0.08   2.70  0.53  -0.25%   0.77  -
rev_3           -0.005  -0.30  +0.020   0.08   2.92  0.54  -0.34%   0.47  -
lowvol_30       +0.066   2.82  +0.090   0.29  10.51  0.61  +0.01%   0.06  YES
maxret_30       +0.083   4.69  +0.075   0.30  10.87  0.62  -0.01%   0.06  YES
amihud_30       -0.044  -2.69  -0.080  -0.31 -11.15  0.37  -0.37%   0.01  -
volume_z_20     -0.022  -1.31  -0.023  -0.12  -4.27  0.46  +0.21%   0.48  -
alpha101_6      +0.035   2.56  +0.024   0.12   4.31  0.55  -0.06%   0.28  YES
alpha101_12     +0.004   0.26  +0.002   0.01   0.41  0.50  -0.46%   0.67  -
alpha101_101    +0.013   0.94  -0.009  -0.05  -1.65  0.47  +0.27%   0.77  -
composite       +0.028   1.55  +0.061   0.23   8.11  0.58  -0.20%   0.36  YES
```

Expected best t among 13 null factors ≈ 1.7; the vol factors are far above it. Three things to say
honestly about this table:

- **`lowvol_30` and `maxret_30` are the same factor.** A coin's largest daily return and its
  realized vol are nearly collinear (churn 0.06 for both, IC within noise of each other). That is
  one pass, not two. `alpha101_6` passes at t = 4.3 with an IC of 0.024 and a negative spread; it is
  not worth a sentence more.
- **`amihud_30` is strongly negative** (t = −11): in this universe illiquid means dying, as the
  factor's own docstring warned. Its sign was fixed as the literature's premium; the literature is
  wrong here. It was not in the composite and does not change anything.
- **The composite's mean Q5−Q1 spread is negative (−0.20% per 5 days) while its rank IC is
  positive and large.** These disagree because crypto returns are right-skewed: the top-composite
  (calm) coins beat the bottom (wild) coins *most weeks*, which is what a rank correlation measures,
  and lose to them *on average*, because the wild quintile's mean is made by a few +50% weeks. A
  long-only book earns means, not ranks. **Criterion 4 should have required a positive mean spread
  as well as t > 3; it did not.** It is met as written, and the verdict stands as written, but the
  criterion as designed could be satisfied by a factor that loses money. The next pre-registration
  that uses an IC hurdle must pair it with a spread hurdle. (Hypothesis #6's document recorded an
  equivalent design flaw, the empty design period; this is this document's.)

IC decay rises with horizon (0.049 at 1 day → 0.071 at 10 days): a slow signal, consistent with the
low-vol tilt doing the work rather than the one-week reversal.

## Transparency

Two changes were made after the first run and the script was re-run. Neither touched the rule, the
windows, the costs or the criteria:

1. `factor_eval.evaluate` split the full date index into train/test blocks, and the first training
   block fell entirely inside the year the 365-close eligibility rule blanks, so the in-sample
   column printed NaN. The evaluator now starts the splits at the first date on which any coin is
   eligible. The out-of-sample numbers moved in the third decimal (composite t 8.40 → 8.11) because
   the block boundaries moved; the pass/fail flags did not change.
2. The decomposition rows (information only, pre-registered as such) were added to the script after
   seeing the headline, to answer the question the headline raised. They cannot change the verdict
   and are the reason the verdict is described correctly.

The first run's output is preserved in the commit message of the results commit.

## What happens next, per the pre-registration

A pass means a **forward paper trade for six months**: a third weekly account running this exact
rule (composite, top 10, buffer 20, 20% vol target, 10 bps) alongside the existing XS account, with
the same `daily` runner. The account wrapper does not exist yet (`espero/xs.py` is the plain top-10
rule and must stay that way for its own track record). Building it is the next engineering step; it
is not in this change because it would have been designed after seeing the result.

It does not mean capital. A result whose first 9 points of CAGR come from holding less when things
get wild, and whose next 7 come from a tilt to calm coins over one contaminated window, is a reason
to keep watching, nothing more.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 1 | Funding extremes | fail |
| 2 | XS momentum, 9 coins top-1 | fail |
| 3 | Polymarket LP | fail |
| 4 | Cross-asset TSMOM | **pass (thin)** — drawdown control |
| 5 | PEAD | fail |
| 6 | Crypto-policy odds | fail |
| 7 | XS momentum, 21 coins top-5 | exploratory — no edge |
| **8** | **Multi-factor XS, vol-targeted, buffered** | **pass** — construction and a low-vol tilt; momentum contributes nothing; criterion 4 was badly designed |

Two nominal passes in eight, both risk-construction results. At the 5% level, eight tries were
expected to produce 0.4 false passes. The honest reading is that this repo has not found alpha; it
has found, twice, that holding less when volatility rises is the only thing that has reliably helped.

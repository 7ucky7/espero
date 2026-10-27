# Pre-registration — multi-factor cross-sectional crypto, vol-targeted, turnover-buffered

Committed **before** `research/multifactor.py` is run. Hypothesis #8. The multiple-testing note is at
the bottom and is the most important paragraph in this document.

## Why this hypothesis

Seven hypotheses so far: one thin pass (cross-asset TSMOM, a drawdown result), six failures. The
cross-sectional crypto tests (#2, #7) failed in a specific way: **selection added nothing over equal
weight, and the drawdown was uncontrolled**. `RESULTS_XS20.md` named the missing ingredient: the
Chinese quant shops that run cross-sectional books profitably do it with *breadth* (hundreds of
names), *many weak factors combined by rank*, *neutralization*, *vol control* and *turnover
control* — not one momentum number and 100% invested.

We cannot buy the breadth (42 coins is what a small account can reach). This hypothesis tests whether
the other four ingredients change the picture on the breadth we have. It is the first rule in this
repo built from the factor stack (`espero/ops.py`, `factors.py`, `factor_eval.py`, `portfolio.py`)
rather than one hand-written signal.

## Universe — fixed

The 42 coins in `espero/xs.py::UNIVERSE`, priced in USD from Yahoo. **Dated eligibility** on each
decision date, using only that date's past:

- at least **365 daily closes** so far
- trailing **30-day mean dollar volume ≥ $1,000,000**

**Survivorship bias is severe and is disclosed, not fixed.** These are coins that exist in October
2026; the ones that died are absent. Every number produced is an upper bound.

## The signal — frozen

Three factors from `espero/factors.py`, each with its sign fixed in the code before this document was
written and with a published prior:

| factor | definition | sign | prior |
|---|---|---|---|
| `mom_30` | 30-day return ending 1 day ago | + | Jegadeesh-Titman; Liu-Tsyvinski-Wu (crypto) |
| `rev_3` | −(3-day return) | + | short-horizon reversal, Jegadeesh 1990 |
| `lowvol_30` | −(30-day realized vol of log returns) | + | low-vol anomaly, Ang et al. |

**Composite**: each factor is MAD-winsorized (k = 3), cross-sectionally percentile-ranked among
eligible coins, and the three ranks are averaged with **equal weights**. No model chooses the weights.
No factor is added, removed, re-signed or re-weighted after seeing results.

`amihud_30`, `maxret_30`, `volume_z_20`, `mom_7`, `mom_90`, `rev_1` and the three Alpha101 examples
are **evaluated in the IC table for information** and are **not** in the composite. Their signs are
fixed in the code too, so the table is a fair reading of each; it cannot change the verdict.

## The portfolio — frozen

- **Decision**: at the close of every **Sunday** (UTC). **Execution**: at **Monday's open**.
- **Selection**: hold **10** coins. **Turnover buffer**: a held coin is kept while its composite rank
  is within the top **20**; empty slots are filled from the top of the ranking
  (`portfolio.turnover_buffer`, buffer = 2.0).
- **Weights**: equal weight across the 10, then each position scaled by
  **20% / its 30-day realized annualized vol**, scale capped at 2×, **gross exposure capped at
  100%** — no leverage, remainder in cash (`portfolio.vol_scaled`). A coin with no vol estimate gets
  no weight.
- **Costs**: **10 bps per side** on dollar turnover (Binance.US taker + slippage). Stress-tested at
  30 bps for information.
- No stops, no shorting, no intraweek trading.

## Evaluation — fixed in advance

**Windows**

- design: **2021-10-01 → 2024-06-30**
- **holdout: 2024-07-01 → 2026-10-27**

**Contamination, stated first.** 2024–2026 has been used by hypotheses #2 and #7, both plain momentum
rules. This composite is a different rule, but it contains `mom_30`, and the person writing this has
seen those results. The holdout is therefore *weakened*, not clean. A pass here is evidence for
continuing to the forward paper trade, not for capital. The forward test is the real one.

**Metrics**: CAGR, annualized Sharpe (daily returns, rf = 0, √365), max drawdown, turnover per year,
number of rebalances. Benchmarks: BTC buy-and-hold; equal-weight eligible universe rebalanced weekly
at the same cost.

**Information-only variants** (reported, cannot change the verdict): the same composite with plain
equal weights and no buffer (to measure what vol targeting and the buffer contribute), and the book
at 30 bps.

**PASS requires all four, measured on the holdout:**

1. Sharpe greater than BTC buy-and-hold
2. max drawdown shallower than BTC buy-and-hold
3. positive CAGR net of 10 bps
4. the composite's out-of-sample rank IC at a 5-day horizon has **t > 3** under the purged
   walk-forward split (4 blocks, 5-day embargo) over the full window

Criterion 4 is the Harvey-Liu-Zhu hurdle. A book can pass 1–3 on one lucky path; a factor with
t < 3 on its own forward returns has not demonstrated anything.

Anything else is **FAIL**. A failure is not re-tuned on this data. The next idea gets a new document.

## Known confounds

- **Survivorship**: see above. Upper bound.
- **Contamination**: see above. Weakened holdout.
- **Short history**: five years of Yahoo daily data, no full cycle before 2021 for most coins.
- **Yahoo data quality**: unofficial endpoint; gaps are left as NaN, never filled.
- **Fee assumption**: 10 bps assumes a venue the reader may not have. Coinbase retail would be 120 bps
  a side and the book would lose by construction.
- **Sunday decision**: ETF-style weekly calendar on a 24/7 asset; a different weekday is a different
  rule and would be a new hypothesis.

## The multiple-testing note

This is the **eighth** hypothesis. At a 5% false-positive rate, eight independent tries produce
0.4 false passes in expectation; the chance of at least one is 34%. The factor zoo adds twelve more
comparisons to the IC table, which is why that table reports the expected best t-statistic among
that many null factors next to the observed ones (`factor_eval.expected_max_sharpe`), and why the
composite's own t must clear 3.

A pass means: paper trade it forward for six months through a new weekly account alongside the
existing XS account, same cost, and compare. It does not mean money.

# Result — BTC lead-lag into altcoins, hourly (#9)

**Verdict: FAIL, by construction, before any data was fetched.** Criterion 2 of the pre-registration
cannot be met by the signal as written. The corrected rule is a new hypothesis,
[PREREGISTRATION_LEADLAG2.md](PREREGISTRATION_LEADLAG2.md), and its result will be a new page.

Spec: [PREREGISTRATION_LEADLAG.md](PREREGISTRATION_LEADLAG.md) (committed `cd748f3`).

## What went wrong

The signal was

```
leadlag_1h(i, t) = r_BTC(t-1, t) − r_i(t-1, t)
```

and criterion 2 required it to beat plain one-hour reversal, `rev_1(i, t) = −r_i(t-1, t)`, on
out-of-sample rank IC, to show the effect was lead-lag and not reversal in disguise.

Within any one hour, `r_BTC` is a single number shared by every coin. Subtracting a constant from
every coin in a row does not change the row's ranks. The cross-sectional rank IC of `leadlag_1h` is
therefore **identical** to that of `rev_1`, hour for hour, and "greater than" is impossible. The
control was well chosen; the signal it was meant to control for was the control.

This was caught by the evaluator's smoke test on synthetic data, where both factors printed the same
IC to four decimals, before `research/leadlag.py` had fetched a single candle. It is recorded as a
fail rather than quietly rewritten because the pre-registration says a rule is not re-tuned after
the fact, and a rule that cannot pass is a rule that failed.

## What the mechanism actually needs

"Coin *i* has not yet moved with BTC" only means something relative to how much coin *i* usually
moves with BTC. A coin with a beta of 2 to BTC that rose 1% when BTC rose 1% has lagged; a coin with
a beta of 0.5 that did the same has overshot. The gap that carries cross-sectional information is

```
beta_i(t) × r_BTC(t-1, t) − r_i(t-1, t)
```

with `beta_i` estimated causally from the trailing week of hourly returns. That is hypothesis #9b.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 1–8 | see RESULTS_MF.md | two passes, both risk-construction |
| **9** | **BTC lead-lag, unscaled gap, hourly** | **fail by construction** — the signal's ranks equal reversal's |
| 9b | BTC lead-lag, beta-scaled gap, hourly | pending |

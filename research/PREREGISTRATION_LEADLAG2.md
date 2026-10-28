# Pre-registration — BTC lead-lag into altcoins, beta-scaled, hourly (#9b)

Committed **before** any hourly candle is fetched. Supersedes #9, which failed by construction
([RESULTS_LEADLAG.md](RESULTS_LEADLAG.md)). Everything not stated here is as in
[PREREGISTRATION_LEADLAG.md](PREREGISTRATION_LEADLAG.md): same data, universe, eligibility,
leader, windows, horizons, split, costs, and the same four criteria.

## The signal — frozen

For coin *i* at the close of hour *t*:

```
beta_i(t)        = cov(r_i, r_BTC) / var(r_BTC)   over the trailing 168 one-hour returns, causal
leadlag_beta_1h  = beta_i(t) × r_BTC(t-1, t) − r_i(t-1, t)
```

**Sign: positive.** A coin that moved less than its own beta says it should have is expected to
catch up over the next hours. BTC is excluded from the cross-section. `leadlag_beta_3h` (the same
gap over three hours, same beta) is reported for information.

Why this is not #9 with a tweak: the beta term is the mechanism. Without it the signal has no
cross-sectional content, which is exactly what #9's failure showed; with it, two coins that fell by
the same amount in an hour when BTC rose are ranked differently if one of them usually follows BTC
twice as hard. Nothing else changes, and the 168-hour window is the first value chosen, not a
searched one.

## The control — unchanged

`leadlag_beta_1h` must beat `rev_1` on out-of-sample rank IC at the 3-hour horizon. This time the
comparison is meaningful: the two factors differ by `beta_i × r_BTC`, which varies across coins.
`leadlag_1h` is also shown in the table, where its t will equal `rev_1`'s exactly, as a check that
the evaluator does what #9's post-mortem says.

## Evaluation and pass criteria

As in #9, at the 3-hour horizon, out of sample under the purged 4-block walk-forward with a 24-hour
embargo:

1. rank IC t > 3
2. t greater than `rev_1`'s
3. mean top-minus-bottom quintile spread > 10 bps
4. hit rate > 0.52

All four, or FAIL. No re-tuning on this data.

## Multiple testing

Tenth test counting #9. Fifteen zoo factors in the table at four horizons. The expected best t
among that many null comparisons is printed next to the observed ones. The author has now spent
two documents on this idea, which is itself a reason to hold it to the hurdle rather than relax it.

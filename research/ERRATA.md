# Errata

Corrections to published research results, newest first. A result is never re-run to
change its verdict; the code that produced it stays as it ran, marked with a comment that
points here. Numbers below were reproduced from cached data during the 2026-10-27 audit
(docs/AUDIT_2026-10-27.md, section D) unless stated.

## 2026-10-28

**No published PASS/FAIL verdict changes.** Two items change how strong a reported number is.

### Reported statistics that overstate

- **Factor t-stats ignore overlapping returns** (RESULTS_MF, RESULTS_LEADLAG, RESULTS_LEADLAG2).
  `factor_eval.summarize` reports t = ICIR·√n on daily ICs of overlapping h-period forward
  returns; neighbouring ICs share h−1 periods of the label, so under a null the reported t has
  a standard deviation near 2 instead of 1 at h = 5. MF composite: plain t 8.11; Newey-West
  4.5–5.0; every 5th day only, 3.15. MF's criterion (OOS t > 3) still passes, narrowly on the
  non-overlapping check. The "expected best null t" printed beside the table assumed
  independent dates and is too low. LEADLAG's t of 13–17 are inflated the same way; it failed on
  spread, so its verdict stands. From this date `evaluate` also reports `t_oos_nw`
  (Newey-West, 2·(h−1) lags); the pass column stays the pre-registered plain t.
- **Carry Sharpe depends on sampling frequency** (RESULTS_CARRY, RESULTS_CARRY2). The
  criterion is the Sharpe of hourly marks, which carry two-venue basis noise that reverts
  within hours (lag-1 autocorrelation about −0.5). On daily closes: #12 7.2 against 1.77
  reported; #11 3.5 against 0.88; ablation A 5.3 against 1.35; ablation B 7.1 against 1.71.
  No verdict flips: #11 and both ablations fail other criteria. The #12 forward test keeps the
  pre-registered hourly criterion; `espero carry status` now shows both.

### Biases that favour a pass

- **Carry universe chosen today** (research/carry.py). Today's top 20 perps by open interest
  were applied to history. Disclosed in the results, but #12 is the pass it could inflate:
  coins that are large now are the ones whose funding stayed positive. The forward test is the
  only control.
- **PEAD** (research/pead.py): same-day close exits fund same-day open entries, entry sizing
  marks open positions at that day's close, and the universe is today's mega-caps. All favour a
  pass, so its FAIL is robust.

### Small deviations from the pre-registered text

- **Momentum lookback one bar short** (research/tsmom.py, xs20.py, momentum.py):
  `iloc[-LOOKBACK]` measures LOOKBACK−1 bars (251 days, not 252; 29, not 30). TSMOM passed
  narrowly (Sharpe 1.08 against the benchmark's 1.02), so a boundary month could move a pick.
  Not checked: its input CSVs are not on disk. The live `espero/tsmom.py` measures 364 calendar
  days and is not affected.
- **Carry time stop** (espero/carry.py, also the forward books): exits after 30 days even when
  the coin still qualifies, then may re-enter it the same hour (4 of 11 time exits in #12). The
  pre-registration says "after 30 days without re-qualifying". Conservative: the round trips
  cost money. The forward books keep the rule as run.
- **One missing hour blanks the carry signal for a week** (espero/carry.py): the 168-hour
  rolling mean needs every hour, so a single gap gives 168 hours of NaN and a no_data exit (ZRO:
  322 NaN hours from 2 gaps; XPL: 168 from 1; one no_data exit in #12). The forward books
  average the last 168 published rates and do not do this.
- **Lead-lag training minimum** (research/leadlag.py): `MIN_TRAIN = 720` was never passed to
  `fe.evaluate`, so the run used 180 hours against the pre-registered 30 days. This moves the
  split edges and the in-sample column; the FAIL was decided on spread and stands.
- **TSMOM benchmark cap** (research/tsmom.py): the equal-weight benchmark keeps its 1/6 cap
  when fewer than 6 assets are eligible (2010–14: 4 eligible, a third in cash). Design period
  only; all 6 are eligible in the holdout.
- **Multifactor marks** (research/multifactor.py): a held coin with a missing close drops out
  of equity that day. Latent: the gaps fall before those coins are eligible, and a re-run with
  forward-filled prices is identical.

### Fixed in code

- **LP simulation trading P&L** (research/lp_sim.py, LP_NOTES.md): rewards were subtracted
  from a cash balance they were never added to; each trading-P&L row was $12.48 too low. Fixed;
  the notes table is corrected and marked. Totals and the conclusion are unchanged.
- **Backtest annualisation** (espero/backtest.py, report.py): Sharpe and CAGR assumed daily
  bars. They now read the bar spacing (identical for daily bars; no result used other bars).

### Forward-test log

- **#12 carry books**, from 2026-10-28 about 02:25 UTC: the loops now backfill missed settled
  hours (up to 72 h), always fetch held coins, drop rows with missing prices and survive failed
  steps. No rule parameter changed; what the books record changed from this time.

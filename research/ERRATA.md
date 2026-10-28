# Errata

Corrections to published research results, newest first. A result is never re-run to
change its verdict; the code that produced it stays as it ran, marked with a comment that
points here. Numbers below were reproduced from cached data during the 2026-10-27 audit
(docs/AUDIT_2026-10-27.md, section D) unless stated.

## 2026-10-28 (later): degen replay clock

**#10's verdict (FAIL) stands; two of its explanations do not.**

- **Timestamps 1000× too small in the degen backtest** (espero/cli.py `_cmd_degen_backtest`).
  pandas 3 parses the cached candle strings to `datetime64[us]`, and `astype("int64") // 10**9`
  assumed nanoseconds, so a 5-minute bar advanced `ts` by 0.3. Bars sharing one integer `ts`
  overwrote each other in the replay (about two in three were dropped from trading, though the
  features still saw them), the 36-bar time stop could not fire, the daily loss cap read every
  bar as 1970-01-21, and the stale-order check never fired. Live loops were not affected: they
  take `ts` from the API as integers. Fixed in `0f9bebf` (`data.unix_seconds`), with a guard that
  refuses a frame whose bar spacing is not the granularity.
- **#10 reproduced on its own 60 cached files with the corrected clock** (Binance.US fees):
  812 trades (as run 180), profit factor 0.98 (0.78), net −$12.60 (−$40.94), max drawdown 30.0%
  (12.8%), Kraken −$280.14 (−$173.21). Still FAIL on four criteria. But RESULTS_DEGEN's "loses
  money before fees" is wrong: with about $35 of fees on 812 trades, the gross is near
  **+$22, roughly break-even**. Its "half the stops are gaps, the breakout bar is the climax" is
  also an artifact: corrected, 51 of 586 stops are gaps.
- Also corrected, not used by any result: `data.fred_series` and `carry_paper._close_at`'s
  fallback built `ts` the same way.

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
- **#13 forward book** (`degen-1h.db`), started 2026-10-28, first bar 05:00 UTC, rule `13` on
  Binance.US fees, polling every 5 minutes. Registered 60 days (to 2026-12-27; to 30 trades or
  2027-02-25 at the latest if fewer). Started after the backtest had already failed, to record
  whether the live period agrees.

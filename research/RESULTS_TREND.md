# Results — multi-asset trend, sized by volatility (#15)

Pre-registration: [PREREGISTRATION_TREND.md](PREREGISTRATION_TREND.md) (commit 19c5490). Rule and
simulator committed before the data (a460756); the snapshot committed before any result was
computed (cfe0327); one run, output in [trend_run.txt](trend_run.txt).

## Verdict: FAIL on criterion 1

The published 1/3/12-month trend rule, long/flat and vol-sized, on 5 equity, 2 bond and 6 commodity
ETFs, BTC/ETH/SOL and an altcoin sleeve, 2018-01-01 → 2026-10-26:

| book | CAGR | Sharpe | max DD | vol | turnover/yr | trades | costs | avg gross |
|---|---|---|---|---|---|---|---|---|
| **trend** | +6.57% | 0.87 | −13.93% | 7.6% | 6.76x | 3749 | 4.20% | 63% |
| volonly (same sizing, always in) | +8.94% | 0.90 | −24.46% | 10.0% | 1.09x | 837 | 0.77% | 96% |
| static (no sizing, always in) | +18.00% | 0.88 | −40.48% | 21.3% | 0.70x | 562 | 1.12% | 97% |
| 60/40 SPY/TLT | +8.22% | 0.72 | −27.55% | 12.0% | 0.43x | 210 | 0.27% | 100% |

| # | criterion | required | actual | met |
|---|---|---|---|---|
| 1 | trend adds return beyond vol sizing | mean(e) > 0 and NW t ≥ 1.28 | k 0.759; mean(e) −0.44 bps/wk; NW t −0.18 | **no** |
| 2 | trend protects beyond vol sizing | max DD > −19.08% | −13.93% | yes |
| 3 | beats 60/40 | Sharpe > 0.72 | 0.87 | yes |
| 4 | survives doubled costs | CAGR > 0 | +6.17% | yes |

**What it means.** Trend timing bought drawdown protection and nothing else. Against the same
vol-sized book scaled down to the same risk, it lost slightly (−0.44 bps a week, t −0.18): no return
beyond holding less. It did cut the worst loss, −13.9% against −19.1% for the vol-matched book, and
it beat 60/40 on Sharpe — but so did volonly (0.90) and static (0.88), with no timing at all. This
is the fourth time the repo has found the same thing (#4, #8, and #8's decomposition): **holding less
when volatility is high does the work; the signal adds little or nothing to it.**

Criterion 2 passing and criterion 1 failing is not the "construction, not signal" case the
pre-registration named (that was for 1 and 2 failing together). It is a drawdown result: real, and
the same shape as #4's, but it is not an edge in returns.

## Information only (cannot change the verdict)

| book | CAGR | Sharpe | max DD | turnover/yr |
|---|---|---|---|---|
| trend, costs ×3 | +5.78% | 0.78 | −14.93% | 6.77x |
| 28-day lookback alone | +7.13% | 1.02 | −12.65% | 12.91x |
| 91-day lookback alone | +6.25% | 0.80 | −13.81% | 7.11x |
| 364-day sign alone (≈ #4) | +6.77% | 0.83 | −14.09% | 3.67x |
| no crypto (budgets ⅓) | +4.04% | 0.65 | −12.05% | 8.61x |
| no alts | +6.31% | 0.91 | −12.08% | 6.85x |
| alts as a fifth class | +7.36% | 0.86 | −14.94% | 5.54x |
| no band | +6.17% | 0.93 | −12.18% | 7.84x |
| idle cash earns BIL | +7.45% | 0.98 | −11.37% | 6.77x |
| SPY buy-and-hold | +14.31% | 0.83 | −33.72% | |
| BTC buy-and-hold | +21.71% | 0.63 | −81.53% | |

- **By period**, the trend book made Sharpe 1.18 in 2018–2021 and 0.57 in 2022–2026.
- **By class** (P&L as a share of starting equity, after costs): equity +17.9%, bonds −3.1%,
  commodities +23.8%, crypto +24.2%, alts +12.5%. Bonds trended badly for a long-only book: the
  2022 fall was a short trade this rule cannot take, and the rebounds whipsawed it.
- **The 28-day lookback alone** has the best Sharpe of the variants (1.02). It is one of ten
  information-only rows, after the fact, at twice the turnover; it is not a finding.
- **Turnover** is high for a weekly book (6.8x a year, 3,749 trades over 8.8 years), because every
  position is re-sized to its volatility every week; the 1% band keeps it from 15,721.

## Post-hoc checks, after the verdict was read

These were not in the pre-registration and cannot change anything; they ask whether the failure
depends on the data problems below.

| criterion 1 recomputed on | k | mean(e) | NW t | max DD trend vs vol-matched |
|---|---|---|---|---|
| no alts | 0.731 | +0.45 bps/wk | +0.19 | −12.08% vs −18.14% |
| no crypto | 0.777 | −0.01 bps/wk | −0.01 | −12.05% vs −16.99% |

The failure does not come from the altcoins: without them, or without crypto at all, the timing
still adds nothing to the vol sizing, and the drawdown benefit is the same.

## Transparency

- **Ticker collisions, confirmed** (the pre-registration flagged the risk). Yahoo's `ARB-USD` is not
  Arbitrum: it is a dead token, last close $0.0006 on zero volume. `TIA-USD`, `WLD-USD` and
  `OP-USD` switch from another token to the real one mid-history, with one-day jumps of
  +68,063,639% (2024-03-26), +31,092% (2023-08-02) and +200,020% (2022-10-06). The $1M liquidity
  filter kept the impostor periods out (it excluded a coin on 416 of 461 decisions, up to 7 at
  once), but after each switch the coin's 364-day lookback compared the real price with the
  impostor's for up to a year, so its trend read "up" whatever it did. The weights involved are
  tiny (each alt is about 1/16 of the book divided among ~26 coins, then vol-scaled), and the
  post-hoc no-alts check shows the verdict does not depend on them. The same tickers are in
  `xs.UNIVERSE`, used by the XS account (no liquidity filter) and by #8 (filtered): recorded in
  ERRATA for those tests.
- **SHIB's zero prices.** Yahoo rounds `SHIB-USD` to exactly 0 on 258 days (2020-08-01 →
  2021-04-15). No decision got a NaN weight (checked: 0 of 461), because SHIB was not yet eligible
  while the zeros could reach its volatility window; but for about eight months after it became
  eligible its 364-day reference was 0, so its trend read "up". After the run, `trend.ann_vol` was
  given a guard that returns None instead of NaN for such a series; the reference test confirms the
  published numbers did not move.
- **A wrong confound.** The pre-registration said the alt sleeve would be empty until November 2018.
  It was not: Yahoo's `LTC-USD` history starts in October 2016, so the sleeve was LTC alone from
  the first decision until the other coins became eligible.
- **Float dust, found by the CI matrix.** Replayed under Python 3.9 and pandas 2.3, the trend book
  ended 0.07% lower with the same 3,749 trades. When a week's ETF buys spent the cash to the last
  1e-17, pandas 2's rounding left 1.2e-17, which bought a 6.9e-18 ETC position at Monday's close;
  that dust then counted as held, sat inside the 1% band and blocked ETC's real entry a week later.
  After the run, positions and buys below 1e-12 of equity are zero (`trend.DUST`). The published
  run (pandas 3.1) never created such a position, so its numbers are unchanged at every daily mark,
  and the two library versions now agree to twelve decimals.
- **A deprecation.** After the run, `DatetimeIndex.weekday` (deprecated in pandas 3) was replaced by
  `day_of_week` in the simulator's weekly sampler; the rerun output is byte-identical.

## What happens next, per the pre-registration

FAIL: no forward paper account and no alerts. The board (`espero board`) ships as an unsized
scanner: it shows each asset's 1/3/12-month trend and the prices that would flip it, labelled with
this verdict, and does not size positions. The rule is not re-tuned on this data; the 28-day
variant above would need its own document and data it has not seen.

What this adds to the repo's evidence: across #4, #8 and #15, on stocks, bonds, commodities, crypto
and altcoins, the one effect that survives is volatility sizing — holding less when markets are
wild cuts drawdowns roughly in half. None of the entry signals tested here has added return on top
of it.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 12 | Carry with swap gap + maker execution (Hyperliquid) | pass, provisional — forward test to 2026-11-27 |
| 13 | 打板 on 1h bars, one entry per bar, beats BTC | fail — negative before fees |
| 14 | #12's carry rule on Kraken Futures | fail — funding rarely clears the bar |
| **15** | **Multi-asset trend (1/3/12 months), vol-sized** | **fail** — cuts drawdown, adds no return beyond vol sizing |

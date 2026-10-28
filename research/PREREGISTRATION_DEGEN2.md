# Pre-registration — 打板 on 1-hour bars, one entry per market move (#13)

Committed **before** any 1-hour candle is fetched for this test and before its paper loop starts.
It is the second go at [#10](PREREGISTRATION_DEGEN.md), which failed on 5-minute bars
([RESULTS_DEGEN.md](RESULTS_DEGEN.md)). Two things are carried over from that failure and the
2026-10-28 audit, and both are written down here rather than discovered in the data:

1. **The horizon was too short for the fees and the noise.** At 2 ATR, a 5-minute stop is
   0.3–0.4% wide, inside ordinary noise, and a 3-ATR target (about 0.5%) is below every venue's
   round trip but Binance.US's. On 1-hour bars the same multiples give a stop of about 1.3–1.5% and
   a target of about 2.1% (XRP, SOL, LTC measured 2026-10-28), 2.6× Kraken's 0.8% round trip.
2. **Several coins breaking out on the same bar is one market move, not several trades.** The #10
   forward book bought three majors on one BTC-led bar and lost on all three.

The honest prior is against this. #10 lost money *before* fees: its breakout bar was the climax,
and the move reversed in the next bar. Hourly bars may average that reversal away or may not.
This test exists to find out, read against criteria fixed now.

## What changes from #10 — frozen

Everything in [PREREGISTRATION_DEGEN.md](PREREGISTRATION_DEGEN.md) holds (the universe rule and
its top-60 cut and $2M floor, every feature, the score, the exits, sizing, fills, fees) **in bar
counts**, with these three changes and no others:

| | #10 | #13 |
|---|---|---|
| bar | 5 minutes | **1 hour** |
| entries per bar | as many as there are slots | **at most one**: the highest-scoring candidate |
| relative strength | none | **the coin's `burst` must exceed BTC-USD's `burst` on the same bar** |

Because the bar counts are unchanged, the clock lengths scale by 12:

```
burst      12 bars   = the last 12 hours          (was 1 hour)
vol_z      48 bars   = the coin's own last 2 days (was 4 hours)
breakout   48 bars   = a new 2-day high           (was 4 hours)
ATR        14 bars   = 14 hours
time stop  36 bars   = 36 hours                   (was 3 hours)
stops      2.0 ATR initial, 2.5 ATR chandelier trail, 3.0 ATR target
```

BTC-USD is fetched as the benchmark only. It is never ranked and never bought (BTC and ETH stay
out of the universe). A bar where BTC's own candle is missing allows no entry.

## Evaluation

**Backtest, once.** Coinbase Exchange 1-hour candles for the universe chosen by the frozen rule on
the day of the fetch, replayed through the same code the paper loop runs, over **180 days:
2026-03-30 00:00 UTC to 2026-09-26 00:00 UTC**. The window ends the day before #10's 30-day
window began, so no bar of it was in #10's backtest or forward test. Bars before 2026-03-30 are
used only as warm-up (the first 50 bars of each coin), never traded. Anything fetched after
2026-09-26 is cut off before the replay and not looked at for this test.

Disclosed, as in #10: survivorship (today's top-60 list biases the test *for* the strategy), and
the $2M liquidity floor uses today's 24-hour dollar volume, not the historical one. Other
hypotheses in this repo have used hourly Coinbase data from this period for majors on different
signals; no breakout rule has been run on it.

**Forward, on paper.** `espero degen paper` with the #13 rule on Binance.US fees, journal
`degen-1h.db`, from its start date for **60 days**. If it has fewer than 30 closed trades by day
60, the verdict is INCONCLUSIVE and the loop keeps running until 30 trades or day 120, whichever is
first; at day 120 with fewer than 30 trades, criterion 1 fails. The #10 loop on `degen.db` is not
touched and ends on 2026-11-10 as registered.

## Pass criteria — unchanged from #10

On Binance.US fees (2 bps taker), all required, in both the backtest and the forward test:

1. at least 30 closed trades
2. profit factor > 1.3
3. net P&L > 0
4. max drawdown shallower than 15% of starting equity ($500)
5. net P&L > 0 **also on Kraken fees** (40 bps taker)

All five, or FAIL. Coinbase (120 bps taker) and the generic perp are reported, not criteria.

**Reported beside it, not a criterion:** the same 1-hour bars run *without* the two new entry
filters (#10's rule, only the bar changed). It is decided now so that it is a control, not a
second chance: if the control passes and #13 fails, #13 still fails.

**On FAIL** the scanner stays and the result is recorded. **On PASS** it stays paper; real money
would need a US-legal, low-fee venue whose fees are checked first, and a separate decision.

## Multiple testing

Fourteenth test in the repo (#1–#12, 9b, this one). The three changes are the first values written
down: the bar is the one already compared against fees on 2026-10-28, "at most one" is the
smallest number that is not zero, and "beat BTC" uses #10's own `burst` with no threshold. The
30-minute bar was considered and **not** chosen; if it is run, it is exploratory, in its own
journal, and counts for nothing here. One backtest run, one forward run, no re-tuning. Any change
after the fetch is a new hypothesis with a new number.

# Result — 打板 on 1-hour bars, one entry per market move (#13)

**Verdict: FAIL.** Four of the five pre-registered criteria missed. The longer bar did what it was
meant to do to the stops (gap stops fell to 3% of exits), and the edge is still negative before
fees.

Spec: [PREREGISTRATION_DEGEN2.md](PREREGISTRATION_DEGEN2.md) (committed `65189b5`, before the
fetch). Code: `espero/degen.py` rule `13` (`51cf4d6`, timestamp fix `0f9bebf`), run as
`espero degen backtest --rule 13 --start 2026-03-30 --end 2026-09-26`. One run. Raw output:
[degen2_backtest.txt](degen2_backtest.txt), control: [degen2_control.txt](degen2_control.txt).

## Data

Coinbase Exchange 1-hour candles, 2026-03-30 → 2026-09-26 UTC (180 days, plus 50 warm-up bars
before it), for the top 60 altcoins by 24-hour dollar volume on 2026-10-28 (ZEC-USD .. FIL-USD).
58 replayed; PONS and CT have no bars in the window. BTC-USD as the benchmark. Bars after the
window were downloaded (the API pages back from now) and dropped before the replay read them.

A first attempt the same day replayed nothing: every coin read as "no bars in the window" because
of the timestamp bug in [ERRATA.md](ERRATA.md) (2026-10-28, degen replay clock). No trade was
simulated and no number was seen; this is the one run.

## Criteria, on Binance.US fees (2 bps taker)

| criterion | required | actual | met |
|---|---|---|---|
| closed trades | ≥ 30 | 468 | yes |
| profit factor | > 1.3 | 0.90 | **no** |
| net P&L | > 0 | −$80.93 on $500 | **no** |
| max drawdown | < 15% | 29.0% | **no** |
| net P&L on Kraken fees | > 0 | −$322.16 | **no** |

## Every venue, and the control

```
rule 13 (one entry per bar, beats BTC)
venue                        trades   hit     PF    fees  maxDD%      P&L   equity  exits
Binance.US                      468  0.35   0.90    9.55    29.0   -80.93   423.91  gap_stop=14 gap_target=4 stop=317 target=132 time=1
Kraken                          460  0.30   0.56  129.17    66.3  -322.16   179.58
Coinbase Advanced               390  0.24   0.22  202.24    92.1  -460.51    39.49
Perp (generic, base tier)       468  0.34   0.86   26.85    31.8  -111.38   393.05

control: 1-hour bars, no new filters (reported, not a criterion)
Binance.US                      507  0.36   0.92   10.36    25.3   -70.20   430.53
Kraken                          499  0.31   0.56  136.88    66.5  -322.30   177.73
```

(`fees` is the entry side only; the exit side is about the same again.)

## What the table says

1. **Still negative before fees.** On Binance.US the round trips cost about $19; the loss is
   $81, so the rule loses roughly $62 gross over 468 trades. The hourly bar did not turn the
   breakout into an edge.
2. **Hit rate 35% against a 40% break-even.** A 2-ATR stop and a 3-ATR target need two wins in
   five. 132 targets against 331 stops.
3. **The longer bar fixed the stops, not the entries.** Gap stops are 14 of 331 (on corrected 5m
   data #10 had 51 of 586). The stops are now outside the noise, and the trades still lose: the
   problem is where the rule buys, not how tight it exits.
4. **Both new filters made it slightly worse.** The control (same bars, every breakout, no BTC
   test) lost $70 against $81, with a shallower drawdown. "One entry per move" and "beat BTC" are
   recorded as not helping here.
5. **Kraken and Coinbase fees are ruinous** (−64% and −92%). Only the 2 bps venue keeps the
   loss to a sixth of the account.

## What this changes

The breakout family is done here: 5 minutes and 1 hour, with and without the market filter, and
the gross edge is at or below zero every time. The forward paper loop the spec registered
(`degen-1h.db`, 60 days) is optional now; the backtest has already failed the verdict, as #10's
did, and the loop would only record whether the live 60 days agree.

## Transparency

One run, no parameter changed after the fetch. Survivorship and the use of today's dollar volume
for the $2M floor are as disclosed in the spec and bias the test *for* the strategy.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 10 | 打板 altcoin breakout, 5m | fail (see ERRATA 2026-10-28: about break-even before fees, not negative) |
| 11 | Perp funding carry, delta-neutral | fail |
| 12 | Carry with swap gap + maker execution | pass, provisional — forward test to 2026-11-27 |
| **13** | **打板 on 1h bars, one entry per bar, beats BTC** | **fail** — negative before fees; the filters did not help |

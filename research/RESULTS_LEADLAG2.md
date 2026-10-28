# Result — BTC lead-lag into altcoins, beta-scaled, hourly (#9b)

**Verdict: FAIL.** Two of the four pre-registered criteria missed. The statistics are enormous and
the money is not there, which is the most useful kind of failure this repo has produced.

Spec: [PREREGISTRATION_LEADLAG2.md](PREREGISTRATION_LEADLAG2.md) (committed `55663e2`, before the
fetch). Code: [leadlag.py](leadlag.py). One run.

## Data

365 days of hourly Coinbase Exchange candles, 2025-10-27 → 2026-10-27, 8,756 hours. 39 of the 42
coins are listed on Coinbase (RUNE, THETA, TRX are not); 23 were eligible in the final hour under
the 30-day-history and $50k-per-hour volume rules. BTC is the leader and is excluded from the
cross-section.

## Criteria, at the 3-hour horizon, out of sample under the purged 4-block walk-forward

| criterion | required | actual | met |
|---|---|---|---|
| rank IC t > 3 | > 3 | 13.44 | yes |
| beats `rev_1` on t | > 14.18 | 13.44 | **no** |
| Q5−Q1 spread > 10 bps | > 10 | +3.7 bps | **no** |
| hit rate > 0.52 | > 0.52 | 0.560 | yes |

Net of one round trip per rebalance: **−0.3 bps on Binance.US, −236 bps on Coinbase.**

## What the table says

```
factor           IC is   t is  IC oos   ICIR  t oos   hit   Q5-Q1  churn  pass
leadlag_beta_1h  +0.028   1.43  +0.040   0.15  13.44  0.56  +0.04%   0.76  YES
leadlag_beta_3h  +0.023   1.18  +0.050   0.19  16.44  0.58  +0.04%   0.46  YES
leadlag_1h      +0.029   1.46  +0.042   0.16  14.18  0.56  +0.04%   0.77  YES
rev_1           +0.029   1.46  +0.042   0.16  14.18  0.56  +0.04%   0.77  YES
rev_3           +0.029   1.40  +0.053   0.20  17.30  0.58  +0.04%   0.46  YES
mom_7           -0.026  -1.38  -0.027  -0.10  -8.75  0.45  +0.03%   0.31  -
mom_30          -0.066  -3.70  -0.022  -0.08  -7.10  0.47  +0.04%   0.16  -
lowvol_30       +0.068   2.89  +0.034   0.11   9.58  0.54  -0.03%   0.06  YES
alpha101_101    -0.029  -1.65  -0.034  -0.14 -11.97  0.45  -0.03%   0.77  -
```
(abridged; the full table with all 15 factors is in the script output)

1. **The #9 post-mortem is confirmed in the data.** `leadlag_1h` and `rev_1` print identical
   statistics to every decimal, as the evaluator was told they would.
2. **The beta term subtracts information.** Scaling BTC's move by each coin's trailing beta was the
   mechanism; it produced a t of 13.44 against reversal's 14.18, and a lower spread. Whatever
   altcoins do in the hour after BTC moves, it is not "catch up in proportion to beta". The
   mechanism as stated is wrong.
3. **Short-horizon reversal is real and worthless.** `rev_1` and `rev_3` have t-statistics of 14
   and 17 over 7,854 hours, hit rates of 56 to 58 percent, and a mean spread of 4 bps per three
   hours. A statistic that large with a payoff that small is the signature of the bid-ask bounce:
   hourly closes alternate between prints at the bid and prints at the ask, so last hour's loser
   "reverts" by about one spread. The effect is the spread. You cannot capture the spread by
   crossing it, and a taker book built on this signal pays exactly what it earns.
4. **IC decay is slow and flat** (0.040 at 1h → 0.013 at 24h), consistent with a mechanical
   microstructure effect, not with information arriving.
5. **The sign of momentum is negative at every intraday horizon**, as it was on daily data. That
   is now four windows in a row.

## What this changes

The reversal spread is precisely the market-maker's income. The only way to be on the right side
of a 4 bps bounce is to be the resting order that gets bounced into, earning the spread and the
maker rebate instead of paying them. That is an execution strategy, not a prediction strategy, and
it is why the next piece of work in this repo is a resting-limit-order simulator with queue
position (`espero/execution.py`) and a semi-automatic screen on top of it, rather than another
signal. The 3.7 bps measured here is the edge budget that screen will show, next to the cost, so the
ratio is in front of the human before every order.

Equally, **no intraday signal in the zoo clears a realistic cost on any venue a small account can
use.** The hourly bar strategy's negative edge, measured earlier the same day, was not an unlucky
indicator set; it is the horizon.

## Transparency

One run. The script was pointed at `leadlag_beta_1h` as the primary before the fetch
(`55663e2`). The evaluator and factor code are the same as for #8, plus the two new factors and
the hourly panel builder, all committed before the fetch with tests.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 1 | Funding extremes | fail |
| 2 | XS momentum, top-1 | fail |
| 3 | Polymarket LP | fail |
| 4 | Cross-asset TSMOM | **pass (thin)** — drawdown control |
| 5 | PEAD | fail |
| 6 | Crypto-policy odds | fail |
| 7 | XS momentum, top-5 | exploratory, no edge |
| 8 | Multi-factor XS, vol-targeted | **pass** — construction and a low-vol tilt |
| 9 | BTC lead-lag, unscaled | fail by construction |
| **9b** | **BTC lead-lag, beta-scaled, hourly** | **fail** — does not beat reversal; the spread is the bid-ask bounce |

Ten tests, two passes, both risk-construction. No predictive edge found at any horizon from one
hour to one month. The slow books stay; the fast work turns to execution.

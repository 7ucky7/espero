# Result — funding carry with a swap gap and maker execution (#12)

**Verdict: PASS, provisional.** All five criteria met on the primary window. The pass is
provisional for the two reasons the pre-registration gave in advance: the hypothesis is post-hoc
(written after #11's diagnosis, run on the same sample), and the maker-execution assumption is
the optimistic end (resting orders fill at the close, no slippage, no unhedged wait). What it has
earned is a 30-day forward paper test with live hourly funding, not a conclusion.

Spec: [PREREGISTRATION_CARRY2.md](PREREGISTRATION_CARRY2.md) (committed `a651f18`, before the
run; engine change `0e2049e`, also before). Raw output: [carry2_run.txt](carry2_run.txt). One
run. The reference row reproduces #11 to the decimal, which checks that the engine change did
not alter the old rule.

## Criteria — primary window 2026-04-02 → 2026-10-28, 18 coins, 4,996 hours

| criterion | required | #12 | #11 | met |
|---|---|---|---|---|
| net annualised return on equity | > 8% | **+10.9%** | +5.2% | yes |
| max drawdown of equity | < 5% | 1.5% | 1.5% | yes |
| Sharpe (hourly, annualised) | > 1.5 | **1.77** | 0.88 | yes |
| funding paid / received | < 25% | 4% | 4% | yes |
| net annualised, Kraken spot (maker 25 bps) | > 4% | **+6.4%** | −7.1% | yes |

28 trades instead of 75. Funding received 6.00% of equity (#11: 5.77%), fees **0.14%** (#11:
3.15%), basis +0.43%. Final equity 1.0606.

## The ablations: which change did the work

| variant | ann. return | Sharpe | Kraken | fees | exits `ranked_out` | verdict |
|---|---|---|---|---|---|---|
| #11 rule, taker | +5.2% | 0.88 | −7.1% | 3.15% | 55 / 75 | fail |
| A: gap + min hold, taker | +8.2% | 1.35 | +1.6% | 1.58% | 6 / 28 | fail |
| B: #11 rule, maker | +10.5% | 1.71 | +1.8% | 0.29% | 55 / 75 | fail |
| **#12: gap + maker** | **+10.9%** | **1.77** | **+6.4%** | **0.14%** | 6 / 28 | **pass** |

1. **The gap halves the fee bill and leaves the income alone.** Swaps fall from 55 to 6, funding
   collected is unchanged (6.0% vs 5.8%), fees halve. The churn in #11 was pure cost: the coin it
   swapped into paid no more, on average, than the one it left.
2. **Execution is worth more than the gap** on Binance.US (B beats A), but neither alone passes:
   A fails Sharpe and Kraken, B fails Kraken. Only together do they clear the Kraken criterion,
   because the gap is what keeps the 25 bps spot maker fee from being paid 55 times.
3. **Nothing changed about the market.** Same 1.5% drawdown, same 4% funding paid. The funding
   available in this window is about 12% a year on notional (6% on equity at 1×). #12 keeps 10.9
   of it; #11 kept 5.2. The regime finding from #11 stands: 2024 paid three times this.

## What the pass does not say

- **Fills.** A maker order on a quiet hour may not fill, and the hour it rests the book is
  one-legged. The 0.14% fee line is a floor, not an estimate. The honest number lies between B's
  world and A's world, and the forward test is where it gets measured: the `fast` screen's
  queue-position simulator exists for exactly this.
- **Sample.** Seven months, one regime, chosen because the venue's candle history ends there.
  Sharpe 1.77 on 4,996 hours is a t-statistic of about 1.3 on the annualised figure; the pass is
  consistent with a true Sharpe of 1 and also with 2.5.
- **Post-hoc.** Two parameters (5 points, 7 days) were written down once and not searched, but
  they were written *after* seeing where #11 lost money. The forward test is the control for
  that; nothing else is.
- **Venue.** Hyperliquid excludes US persons. A pass that survives the forward test is a reason
  to find a venue the account can use at comparable maker fees, not a reason to use this one.

## What this changes

Carry is the first structural strategy in the repo to pass a pre-registered test, and the first
pass that is income rather than risk construction. It moves to a **30-day forward paper test**
(the pre-registration's condition) on Hyperliquid mainnet data with live hourly funding, at
#12's rule, charging #11's taker costs on one book and #12's maker costs on another so the fill
question is bracketed rather than assumed. The slow books and the 5-minute loops are untouched.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 1 | Funding extremes, directional | fail |
| 2 | XS momentum, top-1 | fail |
| 3 | Polymarket LP | fail |
| 4 | Cross-asset TSMOM | **pass (thin)** — drawdown control |
| 5 | PEAD | fail |
| 6 | Crypto-policy odds | fail |
| 7 | XS momentum, top-5 | exploratory, no edge |
| 8 | Multi-factor XS, vol-targeted | **pass** — construction and a low-vol tilt |
| 9 | BTC lead-lag, unscaled | fail by construction |
| 9b | BTC lead-lag, beta-scaled, hourly | fail — the spread is the bid-ask bounce |
| 10 | 打板 altcoin breakout, 5m | fail — the breakout bar is the climax |
| 11 | Perp funding carry, delta-neutral | fail — fees took half, regime faded |
| **12** | **Carry with swap gap + maker execution** | **pass, provisional** — post-hoc, upper-bound fills; forward test pending |

Thirteen tests, three passes. The third is the first income, and the only one with a condition
still attached.

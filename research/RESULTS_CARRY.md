# Result — perpetual funding carry, delta-neutral, hourly (#11)

**Verdict: FAIL.** Three of five pre-registered criteria missed on the primary window. The
strategy made money, it was delta-neutral as claimed, and it did not make *enough*: fees took
more than half of the funding it collected, and the funding regime that would have cleared the
bar ended in 2024.

Spec: [PREREGISTRATION_CARRY.md](PREREGISTRATION_CARRY.md) (committed `6f031c3`, before the
fetch). Engine: [`espero/carry.py`](../espero/carry.py), runner [carry.py](carry.py). Raw output:
[carry_run.txt](carry_run.txt). One run on the complete universe.

## Data

Hyperliquid's top 20 perps by open interest on 2026-10-28, minus XMR and LIT (no Coinbase spot
pair): 18 coins. Hourly funding from May 2023 (`fundingHistory`). Hyperliquid serves at most its
last 5,000 candles per interval, so **hourly perp closes exist only from 2026-04-02**; the
pre-registration said "full available history" and this is what is available with the basis
marked. The primary window is therefore 2026-04-02 → 2026-10-28, 4,996 hours. Coinbase hourly
spot for each coin's full life.

A first run on 13 coins (the fetch was rate-limited before WLD, LINK, AAVE, XPL, BNB landed)
printed +7.3% / 1.08 Sharpe / −1.4% Kraken; it is disclosed here and not used. The recorded run
is the complete one.

## Criteria — primary window, Binance.US spot fees, Hyperliquid base tier

| criterion | required | actual | met |
|---|---|---|---|
| net annualised return on equity | > 8% | **+5.2%** | **no** |
| max drawdown of equity | < 5% | 1.5% | yes |
| Sharpe (hourly, annualised) | > 1.5 | **0.88** | **no** |
| funding paid / funding received | < 25% | 4% | yes |
| net annualised return, Kraken spot fees | > 4% | **−7.1%** | **no** |

75 trades, 15,559 position-hours. Funding received 5.77% of starting equity, funding paid 0.23%,
fees and slippage **3.15%**, basis +0.54%. Final equity 1.0293.

## What the table says

1. **The hedge works.** Max drawdown 1.5%, funding paid only 4% of funding received, basis a small
   positive. Delta-neutral was the easy part and it held.
2. **Fees ate 55% of the funding.** 33 bps per cycle against funding that averaged about 7% a year
   on notional in this window means each cycle needs two to three weeks to break even, and the
   rule did not hold that long: 55 of the 75 exits were `ranked_out`, a held coin swapped for one
   whose trailing funding was marginally higher. That churn is in the rule as written (top five by
   `f_ann`, re-ranked every hour) and it is the single largest cost. A rule that only swapped on a
   meaningful gap would have paid far less. **That is hypothesis #12, not a correction to #11.**
3. **The Kraken criterion does its job.** At 40 bps spot taker the strategy loses 7% a year. The
   edge, such as it is, lives entirely in the cheapest venues' fee tiers.

## The extended view (information only, not a criterion)

With the perp price taken as spot before the hourly candles begin (basis marked at zero there,
funding real), 2023-05-12 → 2026-10-28, 29,766 hours, 369 trades:

| | |
|---|---|
| net annualised on equity | +9.0% |
| max drawdown | 1.6% |
| Sharpe | 3.46 |
| funding paid / received | 4% |
| Kraken fees | −1.7% |

| year | return |
|---|---|
| 2023 (from May) | +8.8% |
| 2024 | +16.5% |
| 2025 | +2.2% |
| 2026 (to Oct) | +3.3% |

Funding carry paid well in 2023–24, when perps traded at a persistent premium, and has paid
almost nothing since. The primary window is the current regime, and the rule fails in it. Even
across the whole period the Kraken criterion fails, so the extended view would not have passed
either.

## What this changes

The carry is real income and the hedge is clean; what the test rejects is the claim that it
clears 8% net on a retail fee tier in today's market with this rule. Two things would move the
number and both are new hypotheses: a swap rule with a hysteresis gap (kills the `ranked_out`
churn) and maker execution on both legs (1.5 bps instead of 4.5 on Hyperliquid, which the
`fast` screen exists to test). Neither changes the regime finding: perp premiums in 2025–26 are a
third of what they were.

`espero carry scan` stays as a read-only view of what shorts are being paid today.

## Transparency

One run on the complete universe. The rule, thresholds, costs and criteria are those in the
pre-registration. Two things were discovered after the fetch and disclosed rather than tuned:
the venue's 5,000-candle limit (primary window shortened to where the basis can be marked), and
the partial first run (rate limit, not used). The `ranked_out` churn was visible only after the
run; its fix is not applied here.

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
| **11** | **Perp funding carry, delta-neutral** | **fail** — hedge clean, fees take half, regime faded after 2024 |

Twelve tests, two passes. The first structural (non-predictive) test came closest of anything
since #8: positive, neutral, and under the bar.

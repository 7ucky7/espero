# Result — 打板: altcoin breakout chasing on 5-minute bars (#10)

> **Erratum 2026-10-28:** this run's replay clock was 1000× too small; corrected, the verdict is
> still FAIL but the gross is about break-even, not negative, and gaps are 9% of stops, not half.
> See [ERRATA.md](ERRATA.md). The text below is as published.

**Verdict: FAIL.** Three of the five pre-registered criteria missed, and the one that matters most
missed before fees: the strategy loses money with the fee set to zero.

Spec: [PREREGISTRATION_DEGEN.md](PREREGISTRATION_DEGEN.md) (committed `87c3974`, before the fetch).
Code: `espero/degen.py`, run as `espero degen backtest --days 30`. One run. The raw output is in
[degen_backtest.txt](degen_backtest.txt).

## Data

30 days of 5-minute Coinbase Exchange candles, 2025-09-27 → 2026-10-27, for the 60 altcoins with
the highest 24-hour dollar volume on the day of the fetch (XRP-USD .. GTC-USD). Survivorship as
disclosed in the spec: this is today's hot list, which biases the test *for* the strategy.

## Criteria, on Binance.US fees (2 bps taker)

| criterion | required | actual | met |
|---|---|---|---|
| closed trades | ≥ 30 | 180 | yes |
| profit factor | > 1.3 | 0.78 | **no** |
| net P&L | > 0 | −$40.94 on $500 | **no** |
| max drawdown | < 15% | 12.8% | yes |
| net P&L on Kraken fees | > 0 | −$173.21 | **no** |

## The same 180 trades under every venue

```
venue                        trades   hit     PF    fees  maxDD%      P&L   equity  exits
Binance.US                      180  0.28   0.78    4.26    12.8   -40.94   459.06  gap_stop=66 gap_target=23 stop=71 target=20
Kraken                          180  0.22   0.34   72.56    36.0  -173.21   326.79
Coinbase Advanced               180  0.07   0.08  159.73    69.3  -340.81   159.19
Perp (generic, base tier)       180  0.27   0.73   10.52    14.7   -53.08   446.92
```

## What the table says

1. **The entry is wrong, not the fees.** On Binance.US the whole round trip costs about $8 over
   180 trades; the loss is $41. With fees at zero the book still loses about $32. Every earlier
   intraday failure in this repo was "an edge smaller than the cost"; this one is a negative edge.
2. **Hit rate 28% against a break-even of 40%.** With a 2-ATR stop and a 3-ATR target the
   strategy needs two wins in five. It got 43 targets against 137 stops. Not one trade reached the
   3-hour time stop: every position was resolved by the stop or the target within the hour or two.
3. **66 of the 137 stops were gaps.** A gap stop means the bar *after* the fill opened more than
   2 ATR below the entry, i.e. the breakout bar's spike reversed inside the next five minutes.
   That is the signature of a climax print: the 2-sigma volume bar is where the move ends, and the
   rule buys it at the next open, at the top. It is the same short-horizon reversal #9b measured
   with a t-statistic of 14, seen from the losing side.
4. **Coinbase's 120 bps taker fee turns a bad strategy into a wipe-out** (−68% in a month), which
   the spec predicted and excluded from the criteria. The perp row is Binance.US plus funding.
5. The drawdown criterion passing is not a consolation: a 1%-of-equity risk budget per trade
   keeps the losses slow, it does not make them stop.

## What this changes

The degen drawer stays in the CLI **as a scanner**: `espero degen scan` is a useful view of what
is moving, and the ATR column next to the venue's round-trip cost is a fair way to look at a coin
before doing anything. The paper loop remains available for the forward test the spec committed
to, but the backtest's verdict is recorded now and does not wait for it.

If anyone picks this up again, the data points the other way: a rule that *fades* the 2-sigma
breakout bar (sells it, or buys the first pullback after it) is the hypothesis the table suggests.
It would be #11, pre-registered, with the reversal control from #9b in the table next to it.

## Transparency

One run. No parameter changed after the fetch. The 60-coin universe was chosen by the frozen rule
on 2026-10-27 at about 19:10 UTC and is cached under `data/degen/`. The replay fills entries at the
next open plus 5 bps, exits at the stop or target price (at the open when the open gaps through),
and charges the venue's taker fee on both sides; perp funding is charged at each 8-hour settlement.

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
| 9b | BTC lead-lag, beta-scaled, hourly | fail — the spread is the bid-ask bounce |
| **10** | **打板 altcoin breakout, 5m** | **fail** — negative before fees; the breakout bar is the climax |

Eleven tests, two passes, both risk-construction. Still no predictive edge at any horizon.

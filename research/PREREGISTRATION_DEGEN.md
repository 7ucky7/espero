# Pre-registration — 打板: altcoin breakout chasing on 5-minute bars (#10)

Committed **before** any 5-minute candle is fetched for the backtest and before the forward
paper loop starts. This is the "degen" experiment: the Chinese retail quant playbook of hitting
the board (打板) — buy the name that is breaking out on abnormal volume, with a tight stop that
scales with the coin's own volatility and a fast exit. Everything intraday tested in this repo so
far has lost to fees ([RESULTS_LEADLAG2.md](RESULTS_LEADLAG2.md)); this document exists so that
the result, pass or fail, is read against criteria written down first.

## Universe — frozen

Every Coinbase Exchange product quoted in USD that is `online` and not `trading_disabled`,
minus BTC, ETH and stablecoins (the exchange's `fx_stablecoin` flag plus USDT, USDC, DAI, PYUSD,
USDP, GUSD, EURC, TUSD, PAX). Ranked by 24-hour dollar volume (`stats.volume × stats.last`),
**top 60**, refreshed hourly in the live loop. A coin is entered only if its 24-hour dollar
volume is at least $2M.

Survivorship is disclosed: the backtest universe is the top 60 on the day of the fetch. A coin
that was hot three weeks ago and is now dead is not in it. That biases the backtest *for* the
strategy, not against it, which is one more reason the forward test decides.

## The signal — frozen

On closed 5-minute bars, per coin, all causal:

```
burst     = log(close / close[-12])                 the last hour's return
vol_z     = ts_zscore(log(volume + 1), 48)          volume surprise vs the coin's own 4 hours
atr       = ATR(14), Wilder smoothing
range_x   = (high - low) / atr                      range expansion
breakout  = close > max(high[-48 .. -1])            a new 4-hour high, the 打板 trigger
score     = mean of cs_rank(burst), cs_rank(vol_z), cs_rank(range_x) across the universe
```

**Entry candidate** iff `breakout` and `vol_z ≥ 2` and `burst > 0` and the liquidity floor
holds. Candidates are taken in descending `score` while slots remain. Long only.

## Exits — frozen, in ATR units

| exit | rule |
|---|---|
| initial stop | `entry − 2.0 × ATR` |
| trailing stop | `max(high since entry) − 2.5 × ATR`, ratchets up only |
| target | `entry + 3.0 × ATR` (1.5 R) |
| time stop | 36 bars (3 hours) if nothing else has fired |

Exits fill at the stop or target price when the bar's range crosses it, and at the open when
the open gaps through it, exactly as in `paper.py`. Entries fill at the **next** bar's open plus
5 bps slippage, never on the bar that signalled. Fees are the venue's **taker** fee per side.

## Sizing — frozen

Risk 1% of equity at the initial stop: `notional = 0.01 × equity / (2 × ATR / price)`, capped at
25% of equity, through `risk.check_buy`. At most **3** open positions, one per coin. Starting
equity $500.

## Evaluation and pass criteria

**Backtest:** the last 30 days of 5-minute Coinbase candles for the universe, replayed once
through the same code the live loop runs. **Forward:** the live paper loop on `degen.db` for
14 days from its start.

On Binance.US fees (2 bps taker), all required, in both the backtest and the forward test:

1. at least 30 closed trades
2. profit factor > 1.3
3. net P&L > 0
4. max drawdown shallower than 15% of starting equity
5. net P&L > 0 **also on Kraken fees** (40 bps taker) — a result that survives only the
   cheapest venue is noise with a fee discount

All five, or FAIL. Coinbase fees (120 bps taker) are reported but are not a criterion: at this
horizon a 240 bps round trip cannot be cleared by anything, and that is stated now rather than
discovered later.

**On FAIL** the section stays in the CLI as a scanner and the result is recorded. **On PASS**
the strategy stays paper; passing a 30-day backtest and a 14-day forward test is a reason to keep
watching, not a reason to fund it.

## Multiple testing

Eleventh test in the repo. No parameter in this document (12, 48, 14, 2.0, 2.5, 3.0, 36, the
60-coin cut, the $2M floor, the vol_z ≥ 2 trigger) was searched; each is the first value written
down. One backtest run, one forward run, no re-tuning on either. If anything is changed after
the fetch, that is a new hypothesis with a new number.

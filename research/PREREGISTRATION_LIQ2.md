# Pre-registration — #18's rule on every day of Binance's COIN-M liquidations (#26)

Committed **before** any COIN-M liquidation file for this test is downloaded (one file's header row
was looked at, below). The twenty-seventh test in this repo.

## Why

#18 ([RESULTS_LIQ.md](RESULTS_LIQ.md)) asked whether breakouts made of liquidations fade more than
organic ones. It passed two criteria and failed two: the effect was in the predicted direction but
reached only t −2.1 on its 82 free days, and all of it came from June 2023 onward. Binance's public
archive keeps a **COIN-M liquidation file for every day from 25 June 2023 to 14 October 2024**
(found by the user's script; Binance stopped publishing it after that day). That is #18's own kind
of data, every day, over the era where #18's effect appeared. This reruns #18's rule unchanged on it.

## Data — fixed

- **Days**: UTC days **2023-06-26 → 2024-10-14**, excluding the first day of every month and the days
  before and after it (#18's days). About 430 days.
- **Coins**: the coins of `espero/xs.py::UNIVERSE` with a COIN-M perpetual, `{COIN}USD_PERP`: BTC, ETH,
  SOL, BNB, XRP, ADA, DOGE, AVAX, LINK, DOT, TRX, LTC, BCH, ATOM, ETC, XLM, NEAR, OP, FIL, RUNE, AAVE,
  EOS, THETA, XTZ, ALGO, WLD (26). A coin-day without a file contributes no liquidations; a coin-day
  whose file is missing has no forced share (#18's amendment, kept).
- **Liquidations**: `data/futures/cm/daily/liquidationSnapshot` from data.binance.vision. Every row
  appears twice in Binance's file; rows are de-duplicated on (time, price, last_fill_quantity), which
  the user's script verified reproduces Tardis's feed row for row (2024-01-01, BTCUSD_PERP). `side`
  is the liquidation order's side: SELL is a long liquidated, BUY a short liquidated. **Dollar value
  = last_fill_quantity × the contract size: $100 for BTCUSD_PERP, $10 for every other coin**, Binance's
  documented COIN-M sizes.
- **Prices and volume**: #18's, from Binance USDⓈ-M: the monthly 5-minute klines #20 downloaded
  (quote volume and taker-buy quote volume included), not COIN-M's own bars.

## The rule — #18's, unchanged

`espero.liq` as #18 ran it: the 打板 trigger and its mirror on 5-minute bars (breaks closing 01:00 →
24:00 UTC, one per coin per direction per hour), the forced share s = liquidations on the break's
side in the hour before ÷ the hour's Binance USDⓈ-M quote volume, y = the 1-hour return in the
break's direction from the next bar's open, within-day terciles of s, D(day) = forced − organic, days
with fewer than 6 events left out.

**PASS requires #18's four criteria**, with one change: the halves are this window's
(2023-06-26 → 2024-02-15 and 2024-02-16 → 2024-10-14), since #18's split date falls before it.

1. mean D < 0, **t ≤ −3**
2. D on the coin-centred share < 0
3. D < 0 in both halves
4. a long leg (forced down-breaks, or organic up-breaks) earns > 18 bps an hour with t > 2

**Information only**: #18's variants (15-minute window, 15-minute and 4-hour horizons, global
terciles, taker-flow agreement), and both legs net of costs.

## Outcomes — fixed now

- **PASS**: #18's idea is confirmed on new days; a forward-test document follows before anything trades.
- **1–3 hold, 4 fails**: real, not tradable.
- **Anything else: FAIL.** Not re-tuned on this data.

## Known confounds

- **COIN-M is not #18's market**: inverse contracts, a smaller market with different traders.
  #18 used Binance USDⓈ-M plus Bybit.
- **Sampled**: Binance reported at most one liquidation per coin per second, as in #18.
- **Already seen**: #20 measured the average 1-hour bounce of these days' down-breaks; #25 (running)
  is measuring the open-interest version over these days. Neither has measured the split by
  liquidations, which is all this test looks at.
- **Contract sizes are documented values**, not read from Binance's API, which is blocked from here.

## Transparency — what was seen before this commit

The user's script, the header row of the BTCUSD_PERP file for 2024-10-14, response codes for a few
dates (to find the archive's first and last days), the archive's symbol list, #18's, #20's and #21's
results, and #25's design.

## Amendment before any download (2026-10-29)

The *Coins* line above says both that a coin-day without a file "contributes no liquidations" and
that one whose file is missing "has no forced share". Binance's archive appears to publish a file
only for days with liquidations, so the two cases cannot be told apart by the file alone. Resolved,
before any file is fetched: **between a coin's first and last file in the window, a day without a
file counts as no liquidations (s = 0)**; before its first file or after its last, the coin has no
forced share (its events are not grouped).

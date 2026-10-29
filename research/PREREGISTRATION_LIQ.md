# Pre-registration — liquidations sort breakouts into forced and organic (#18)

Committed **before** any data from the test days is downloaded, except the probe listed under
*Transparency*. Hypothesis #18, the nineteenth test in this repo (#9 and #9b both count; #16 and #17
were registered earlier today and are still running).

## Why this hypothesis

The question was whether the liquidations that aggr (github.com/Tucsky/aggr) shows can decide which
way a breakout goes. aggr listens to the exchanges' public liquidation feeds and draws them beside
the trades; it keeps no history. The bot can listen to the same feeds, but a live-only signal
cannot be tested, so this test uses the free history that exists.

Liquidations are forced trades. A short position that is liquidated is bought back by the
exchange's engine whatever the price, and a liquidated long is sold the same way. They cannot say
where a breakout will go before it happens, because they print as it happens. What they may say is
**what kind** of breakout it is:

- **forced**: an up-break where much of the buying was shorts being liquidated, or a down-break
  made of long liquidations. Nobody chose to trade at those prices, and the forced traders are gone
  once they are liquidated. Forced trades move prices temporarily and the move reverses: Coval &
  Stafford (2007, *Asset fire sales (and purchases) in equity markets*) showed it for mutual-fund
  fire sales. **Expected: the break fades.**
- **organic**: a break with few liquidations behind it, so the volume came from traders who chose to
  pay up or sell down. **Expected: it fades less, or continues.**

This also tests a filter the 打板 rule never had. #10 and #13 bought every new 4-hour high and lost
before fees, and today's Hyperliquid replay of #10 stopped out on 335 trades against 116 targets:
most breakouts reverse. If the forced share separates the ones that reverse from the ones that
run, it is the missing filter.

## Data — fixed

- **Days**: the first UTC day of every month from **2020-01-01 to 2026-10-01**, 82 days. These are
  the days Tardis.dev serves without a key; any other day needs a paid key.
- **Coins**: the 42 coins of `espero/xs.py::UNIVERSE`, each on the days it had a Binance USDⓈ-M
  perpetual. Symbols are `{COIN}USDT`, except SHIB: `1000SHIBUSDT` on Binance, `SHIB1000USDT` on
  Bybit. Today's list is used, so survivorship is disclosed, not fixed.
- **Liquidations**: Tardis `liquidations` files for `binance-futures` and `bybit` (USDT linear
  perpetuals) on the test day. Tardis documents `side = buy` as *short position was liquidated* and
  `sell` as *long position was liquidated*; `unknown` rows are dropped. Dollar value = price ×
  amount (linear contracts: amount in the coin, or in thousands of SHIB at a per-thousand price).
- **Prices and volume**: Binance's public archive (data.binance.vision), USDⓈ-M futures 1-minute
  bars for the day before, the test day and the day after, combined into UTC-aligned 5-minute bars.
  Quote volume and taker-buy quote volume come from the same files.
- **Missing files**: a coin-day without Binance bars for the test day is dropped; a venue without a
  liquidation file that day contributes none (recorded as "no market"). Other download errors stop
  the run, to be fixed and rerun before any number is printed. Nothing is substituted.
- The event table, the run's output and a manifest of what was missing are committed
  (`research/liq_events.csv`, `liq_run.txt`, `liq_manifest.json`); the downloaded files are
  cached in `data/liq/` (not committed: a few hundred MB, re-downloadable).

## Events — frozen

On each coin's 5-minute bars, with `degen.features` unchanged (#10's frozen definitions):

- **up-break** at bar *t*: exactly `degen.is_candidate`: close above the highest high of the 48
  previous bars, volume z-score ≥ 2.0 (log volume over 48 bars), the last hour's return (`burst`)
  above 0, ATR above 0.
- **down-break**: its mirror: close below the lowest low of the 48 previous bars, volume z ≥ 2.0,
  `burst` below 0, ATR above 0.
- Only breaks whose bar **closes from 01:00 to 24:00 UTC** of the test day, so the hour before
  each break lies inside the day the liquidation file covers.
- **One event per coin per direction per hour**: after an event at bar *t*, that coin's breaks in
  the same direction at bars *t+1 … t+12* are ignored.

## Measures — frozen

Over the hour ending at the close of the breakout bar (the 12 bars *t−11 … t*), with *d* = +1 for
an up-break and −1 for a down-break:

- **forced** = dollar value of liquidations on the break's side (short liquidations for an
  up-break, long liquidations for a down-break), Binance plus Bybit, timestamps from the open of bar
  *t−11* up to the close of bar *t*
- **volume** = Binance quote volume over the same 12 bars
- **s = forced / volume**, the forced share. It is an index, not a true share: the volume is one
  venue's
- **outcome y** = *d* × (close of bar *t+12* ÷ open of bar *t+1* − 1): the return in the break's
  direction from the next bar's open to the close one hour after the break. A long trade earns *y*
  on an up-break and −*y* on a down-break

## Evaluation — fixed

**Grouping.** On each day, every event (all coins, both directions) is ranked by *s* (percentile
ranks, ties averaged). **Forced** = rank above ⅔; **organic** = rank ⅓ or below. Days with fewer
than **6** events, or with an empty forced or organic group, are not used.

**The statistic.** D(day) = mean *y* of the day's forced events − mean *y* of its organic events.
Each day is one observation, so events that move together on one day are counted once:
t = mean(D) ÷ (sd(D) ÷ √days).

**PASS requires all four:**

1. **Forced breaks fade relative to organic ones**: mean D < 0 and **t ≤ −3**.
2. **Not the coin mix**: the same D with *s* replaced by *s* minus the coin's own mean *s* over all
   its events (some coins are always more leveraged than others) has mean < 0. This uses the whole
   sample to centre each coin and is a check on the grouping, not a tradable rule.
3. **Not one era**: mean D < 0 in each half of the days (2020-01 → 2023-05, 41 days; 2023-06 →
   2026-10, 41 days).
4. **A long-only trade pays**: at least one leg earns a mean one-hour long return **above 18 bps**
   (two Hyperliquid taker round trips of 9 bps, a cushion for the wide spreads around a break) with
   day-clustered **t > 2** (each day's mean over that leg's events is one observation; days with no
   such event are skipped). The two legs are:
   - (a) **buy the flush**: forced down-breaks, long
   - (b) **buy the organic break**: organic up-breaks, long

**Information only, cannot change the verdict:**

- each venue's liquidations alone (Binance; Bybit)
- forward horizons of 15 minutes (*t+3*) and 4 hours (*t+48*)
- a 15-minute measurement window (bars *t−2 … t*)
- **aggressor agreement**, *d* × (2 × taker-buy quote volume − quote volume) ÷ quote volume over the
  hour: the taker flow aggr draws as CVD. Its within-day terciles are shown the same way
- the mean *y* of all breaks (does the 打板 trigger fade on average on this data, as #10 found?)
- D with global terciles instead of within-day ones
- event counts by year and direction, and the share of events with no liquidations at all
- both long legs net of a Binance.US (4 bps) and a Hyperliquid (9 bps) taker round trip

## Outcomes — fixed now

- **PASS**: `research/FORWARD_LIQ.md` is written before anything trades on it. Then a live
  recorder (`espero liq`) listening to Binance's and Bybit's public liquidation feeds, as aggr does,
  and a forced/organic column in `espero degen scan`.
- **Criteria 1–3 hold, 4 fails**: "real, not tradable after costs". It is reported, and nothing
  ships, as with #9b's reversal.
- **Anything else: FAIL.** aggr in the browser stays a tool for watching by eye, not a signal.
  Nothing is re-tuned on this data: another window, threshold, horizon, venue or day set is a new
  document.

## Known confounds

- **Sampled feeds.** Binance's `forceOrder` stream sends at most one liquidation per coin per second
  (the probe below found 1,133 rows for BTC on 2025-10-01, never two in the same second). Bybit's
  older `liquidation` channel is also sampled; its `allLiquidation` channel is complete (the same
  day: more than one per second in 2,312 seconds). So *s* is a **lower bound**, its bias changes
  over the years as the feeds changed, and it is worst in a cascade, exactly where the effect
  should be strongest. Ranking within each day is the answer to the drift; the cascade cap biases
  toward finding nothing.
- **Mixed venues**: liquidations from two exchanges over one exchange's volume.
- **82 calendar days chosen by the data's price**, not by the market. Month starts are not
  obviously special for intraday crypto, but they are not a random sample.
- **Binance perpetual prices**, not Hyperliquid perps or Binance.US spot, where the bot trades.
- **Survivorship**: October 2026's coin list.
- **Entry at the next bar's open** after a violent bar is optimistic: spreads are widest there.
  Criterion 4's 18 bps hurdle (two round trips) is the allowance for it.

## Transparency — what was seen before this commit

- **Probe of 2025-10-01**, made while answering whether this could be tested: Tardis's BTCUSDT
  liquidation files for Binance and Bybit (row counts, the per-second check above, and Binance's
  BTC totals that day: $38.4M of short liquidations, $2.9M of long), and the first two rows of
  Binance's 1-minute BTCUSDT file (the column layout). No price path, breakout or return was looked
  at. 2025-10-01 stays in the sample.
- File sizes only, for BTCUSDT on 2020-01-01, 2021-06-01 and 2026-10-01, SOLUSDT on 2025-10-01 and
  OKX's BTC file on 2025-10-01; the response codes of eleven exchanges' public APIs; OKX's
  liquidation orders from today (not a test day); Binance's, Bybit's and Tardis's symbol lists.
- aggr's source code, which feeds it listens to.
- #10's and #13's results, and today's Hyperliquid replay of #10: breakouts mostly reversed. That
  bears on the mean of *y*, which is information only, not on D.

## The multiple-testing note

Nineteenth test; three thin passes so far, all risk construction, and no intraday signal has
passed. Liquidations are a different kind of information (who is forced to trade, not another
price pattern), which is the reason to test it, not a reason to expect it to pass. The t ≤ −3
hurdle is kept, and the test is run once.

## Amendment before the run (2026-10-29, after a crash, before any number)

The first run stopped on its first day, before printing anything. Tardis answers **HTTP 400 with
code 140** ("Requested dataset is not available for '2020-01-01'") for a symbol-day it did not
record, where this document assumed a 404. Both now mean "no file".

That exposed an ambiguity in the text above, which says both that a venue without a file
"contributes none" and that "nothing is substituted". Tardis began recording some Binance symbols
after Binance listed them: ADAUSDT has Binance bars on 2020-01-01, but Tardis's recording starts
on 2020-01-31. There, a missing file means liquidations happened and were not recorded, and
counting them as zero would label those breaks organic. Resolved before any result, in favour of
"nothing is substituted":

- **a coin-day without Binance's liquidation file has no forced share**: its events keep their
  returns (they count in the information-only mean of all breaks) but their *s* is empty, so they
  are never grouped
- a missing **Bybit** file still contributes none: before a symbol's Bybit listing, which is the
  usual reason, there was nothing to record

Only 2020-01-01 had been reached (30 coin-days cached). The cache was deleted and the run started
again from the beginning.

The second start stopped too, before any number: Binance's archive dropped a connection halfway
through a file (`IncompleteRead`), which the downloader did not retry. Dropped reads are now retried
like timeouts. The cache of finished coin-days was kept, since they are the same files either way.

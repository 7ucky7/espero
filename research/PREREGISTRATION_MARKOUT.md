# Pre-registration — what our fills actually cost, measured on ticks (#39)

Committed and pushed **before any tick is downloaded**. A measurement, not a strategy: nothing
trades. The fortieth test in this repo.

## Why

Every test since #9 prices its trades with an assumed cost. The 18 bps hurdle (two Hyperliquid taker
round trips: 4.5 bps fee and 2 bps slippage a side, doubled) was never measured. And the one time a
test watched its own fills, they were picked off. In #30, bids that filled went on to lose 21.7 bps,
while bids that never filled would have gained 63.9 bps.

Five-minute bars cannot see why. Whether a fill is good is decided in the seconds around it: which
side traded, how wide the spread was, and whether the price went through the level. This test goes
to the prints and answers three questions:

1. **What does a trade cost here, measured?** That means fees, the spread actually paid, and, for
   resting orders, the adverse selection of being filled. The answer is broken out by venue, coin and
   condition, and written as a table the rest of the repo can import.
2. **Do the open leads survive that cost?** #29, #31 and #38 are re-priced on their own historical
   events. #34 and #37 are out of reach (see Scope).
3. **Is there any condition in which resting orders earn money?** That is a yes or no: does a
   passive fill have a positive markout after the maker fee, under a fill model that does not flatter
   us?

## What the request assumed, and what exists (checked 2026-10-29, before this file)

The request this test answers named three inputs that are not available as described. The design
below uses what exists:

- **Binance `bookTicker` (best bid and ask) stops in 2024.** The archive holds daily files from
  2023-05-16 to 2024-03-30 and nothing later. There is no archived Binance quote for 2026.
  `aggTrades`, which records every trade with its aggressor side, runs to 2026-10-27. So the 2026 mid
  is **derived from trades** (the proxy below). The proxy is **validated against real quotes** on
  named days before any of its numbers count.
- **The Hyperliquid collector records no trades and no order book.** It records asset contexts, HLP,
  positions and 1-minute candles. Hyperliquid ticks come from **Tardis.dev's free days** instead: the
  1st of each month, trades and quotes, from 2024-11-01.
- **`hftbacktest` has no order book to run on** for the main window, because no Level 2 data exists
  for it. The fill model that decides the answer is a **pair of bounds written here** (optimistic and
  conservative). `hftbacktest` runs only as information, on one free day of real Level 2 data, and
  decides nothing.

"No 5-minute bars" applies to costs. The leads' **triggers** stay on the 5-minute bars their own
frozen rules use; only their **costs** come from ticks.

## Data — fixed

| set | source | coins | days | use |
|---|---|---|---|---|
| **B** (main) | data.binance.vision, USDⓈ-M daily `aggTrades` | BTC, ETH, SOL, XRP (USDT perps) | every UTC day 2026-04-01 → 2026-10-27 | Binance cost table, lead re-pricing |
| **V1** | data.binance.vision `bookTicker` + `aggTrades` | same | 2023-06-01, 07-01, … 2024-03-01 (the 1st of 10 months) | proxy validation on Binance's own quotes |
| **V2** | Tardis.dev free days, `binance-futures` `quotes` + `trades` | same | 2026-04-01, 05-01, … 10-01 (7 days) | proxy validation in the 2026 regime; second-source replay of B |
| **H** | Tardis.dev free days, `hyperliquid` `quotes` + `trades` | BTC, ETH, SOL, XRP | 2024-11-01, 12-01, … 2026-10-01 (24 days) | Hyperliquid cost table (real quotes, no proxy) |
| **L** | `data/aggr/` hourly liquidations (as #26 and #27 read them) | same | 2026-04 → 2026-10 | the liquidation condition |
| **E** | committed event files: `research/levetf_days.csv.gz` (#28 → #29), `research/bids_events.csv.gz` (#30 → #31), `research/fillcost_events.csv.gz` (#33 → #38, Mondays 00:00); for every 00/08/16 UTC settlement, #38's rule rebuilt on set-B days from `data/lows/` 5-minute bars and `fundsplit.rates` (#38's own inputs) | the four coins only | as recorded | lead re-pricing |

- **Gaps**: a missing day or file is dropped and listed, never filled in. A coin-day with fewer than
  1,000 prints is dropped.
- Raw files are reduced day by day to per-day aggregates and then deleted. The aggregates are
  committed (`research/markout_days.csv.gz`), so every table can be rebuilt without the downloads.

## Definitions — fixed

**Prints.** One row per aggregated trade: time (ms), price, quantity, and aggressor side. The
aggressor is a buyer when Binance's `is_buyer_maker` is false; Tardis gives `side` directly. The
maker's side is the opposite: s_maker = +1 when the maker bought (a seller hit the bid).

**Mid.**
- Sets V1, V2 and H: the true mid, (bid + ask) / 2, from the last quote at or before t.
- Set B: the **trade proxy** m̃(t) = (A(t) + S(t)) / 2. A(t) is the price of the last buyer-aggressor
  print at or before t, and S(t) the last seller-aggressor print. The proxy is missing when either
  is more than 60 s old, or when A < S.
- "Just before a print" means the mid computed from strictly earlier timestamps.

**Tick.** Each coin-day's tick is the smallest positive gap between distinct print prices that day.

**Horizons.** h ∈ {1 s, 10 s, 60 s, 300 s}. The mid at t + h is the last mid at or before t + h.

**Three fill measures, all in bps of the fill price:**
1. **Taker cost.** Effective half-spread: c = s_taker × (p − m(t⁻)) / m(t⁻), one value per print.
2. **Maker markout, optimistic.** Every print is a fill for whoever rested at p:
   M_h = s_maker × (m(t + h) − p) / p. This is what the average liquidity provider earned, including
   those at the front of the queue.
3. **Maker markout, conservative (back of the queue).** A resting order at p is certain to fill only
   when the price trades **through** p. For each such event, the fill is at p and the clock starts at
   the first through-print:
   - for a resting bid, the first seller-aggressor print below p, after a seller-aggressor print at p;
   - for a resting ask, the same in reverse.

   It counts once per level and side, each time that level is cleared, and is measured with M_h from
   that time. This is the tick version of the repo's existing rule that a bar's low must trade 1 bp
   through the bid (`espero/bids.py`).

**Fees, per side.**
- Binance VIP 0: taker 5.0 bps, maker 2.0 bps.
- Hyperliquid base tier: taker 4.5 bps, maker 1.5 bps.

Each venue's maker fee is the one subtracted from its markouts. The request's "1.5 bps" is
Hyperliquid's.

**Conditions**, known at the fill time t. Each fill carries one level of each:

| condition | levels |
|---|---|
| spread | **tight**: the spread just before the fill is ≤ 1 tick (proxy spread A − S on B; quoted on H). **wide**: more than 1 tick. |
| flow | Trade imbalance TI = (buy − sell notional) / total over the 10 s before t, with a = s_maker × TI for maker fills (s_taker × TI for takers). **against**: a ≤ −⅓. **neutral**: \|a\| < ⅓. **with**: a ≥ ⅓. |
| funding | **settlement**: t within 5 minutes either side of 00:00, 08:00 or 16:00 UTC. **other**: everything else. |
| liquidations | **liquidation hour**: the hour's aggr liquidation notional (lbuy + lsell) is in that coin's top 5% of hours over 2026-04 → 10. **other**: everything else. Set B only, since L covers only that window. |

Plus **all**, which ignores conditions. TI is trade imbalance from prints, not Cont-Kukanov-Stoikov
order-flow imbalance: that needs quote updates, which set B does not have.

**Aggregation.** Fills are averaged equally, not by size: a small account's outcome is per fill.
Each coin-day-condition cell's mean is one observation. The t-statistic is over days (day
clustering, as `liq.clustered` does).

## Validation of the proxy — before any set-B number counts

On V1 and V2, the full table (all, by coin × horizon × measure: taker c, optimistic M_h,
conservative M_h) is computed twice from the same prints: once with the true mid and once with the
proxy.

A **(coin, horizon) is validated** when every one of its cells agrees within the tolerance on
**both** V1 and V2. The tolerance is

  |proxy − true| ≤ max(0.25 bps, 20% of |true|).

Taker c has no horizon. It must pass for the coin to count at all.

Only validated (coin, horizon) pairs from set B enter any criterion. The rest are printed, marked
"proxy not validated".

## Second source — fixed tolerance

- **Binance.** On the V2 days, the set-B code is run on Binance's archive `aggTrades` and again on
  Tardis's `trades` for the same coin-days, both with the proxy. The tables must agree within the
  same tolerance in every "all" cell. If they don't, set B's numbers are reported but **fail
  replication**, and Q3's answer for Binance is "not established".
- **Hyperliquid.** Tardis is the only tick source available without the user's AWS credentials
  (Hyperliquid's S3 archive is requester-pays). Its trades are checked against the collector's
  1-minute candles on days both exist: closes within 1 bp in ≥ 99% of minutes. If no day overlaps,
  that is reported, and the Hyperliquid table stands on one source.

## The pass bar — set by everything tried so far

This repo has run 39 tests. Q3 looks at 320 cells: 2 venues × 4 coins × 10 condition levels (all,
plus 9) × 4 horizons. Nothing in the record holds trial Sharpe ratios, so the deflated Sharpe ratio
of Bailey and López de Prado (2014) is applied **in t units, with a null variance of 1 across
trials**:

- N = 39 + 320 = 359 trials.
- The expected maximum of N null t-statistics is E = (1 − γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)) =
  2.952, with γ the Euler-Mascheroni constant.
- The bar is **t ≥ E + Φ⁻¹(0.95) = 4.60**, computed in the code from this formula and checked
  against 4.596.

The bar is above the repo's Harvey-Liu-Zhu hurdle of 3.0, so it is the binding one.

## Evaluation — once

### Q3 — can resting orders earn here? A yes or no.

**YES** requires at least one cell (venue × coin × condition level × horizon, validated if on B)
where all three hold:

1. the **conservative** maker markout minus the venue's maker fee is > 0, with day-clustered
   **t ≥ 4.60**;
2. it is > 0 in **each half**:
   - B: 2026-04-01 → 06-30 and 07-01 → 10-27;
   - H: 2024-11 → 2025-10 and 2025-11 → 2026-10;
3. on B, the replication check above passed.

Otherwise **NO**.

A cell that passes only on the optimistic bound does not count; it is reported as "the front of the
queue earns, we would not be there".

### Q1 — the measured cost table. Not a pass or fail; it is the deliverable.

For each venue × coin × condition level, it reports:
- taker c (mean and median);
- the fee;
- the measured taker round trip, 2 × (fee + mean c);
- optimistic and conservative maker markouts at each horizon, with their day-clustered t.

It also prints this measured round trip next to the assumed 18 bps.

### Q2 — the leads, re-priced. Information only; no forward test changes.

Each lead's in-sample events on the four coins are re-priced with the Q1 table. The cost of each leg
is taken from the cell for its coin, its side type (taker, or maker conservative) and its condition
levels at the event time. Where a condition is not observable from the event file, the coin's "all"
cell is used. Gross returns come from the event file unchanged.

| lead | trade as its rule states | legs priced |
|---|---|---|
| **#29** | BTC and ETH, fade the session's move at 16:00 ET, close at 16:15 ET (and 17:00 ET) | 2 taker legs (`levetf_days`, post15 and post60, sign as recorded) |
| **#31** | maker bid 2 ATR under #20's breakdowns, exit at a resting target or a 4-hour taker timeout | maker entry at the conservative markout (its bar rule already demands a trade-through); target exit as a maker leg; timeout exit as a taker leg (`bids_events`, 4 coins only) |
| **#38** | short at a 00:00, 08:00 or 16:00 UTC settlement when shorts paid ≥ 0.05%, cover 30 minutes later | 2 taker legs, entry under the "settlement" level (`fillcost_events` 2020–26 Mondays priced by the table; the every-day events on set-B days priced by the table at their own settlement time; 4 coins only) |

A lead **survives the measured cost** when its mean net return is > 0 with day t ≥ 2, its own
standard. A second column reports whether it also clears 4.60.

This is information about leads whose forward verdicts are frozen. Their pre-registered criteria,
hurdles and windows do not change.

#31 is re-priced on 4 of its 40 coins. That is not a test of its breadth claim, and it is said so
next to the number.

## Scope — what this model cannot price, said plainly

- **#34** (2× funds pushing small coins into the US close) trades coins outside these four. Its cost
  would need those coins' `aggTrades`. It is not imputed from the majors.
- **#37's minute 15** is a Polymarket binary. Its cost is Polymarket's order book, which has no
  public history. Pricing it needs a recorder on Polymarket's CLOB book channel, run forward.
- Coins outside BTC, ETH, SOL and XRP get **no** number from `espero/costs.py`. It raises instead of
  guessing.

## Information only — decides nothing

- **`hftbacktest`**: one free Tardis day (2026-10-01, BTCUSDT, `incremental_book_L2` + `trades`).
  A bid joins the best bid every 60 s; its fill rate and 60 s markout are printed against the
  optimistic/conservative band. If it does not install or run, that is reported and it is dropped.
- Markouts by hour of day, and by print size (above vs below the coin-day median).
- The V1 era (2023–24) table next to 2026, for drift in costs over time.

## Confounds, stated now

- **The proxy is the weakest link.** After a sweep, the last buyer-aggressor print can sit above the
  new ask. That is why it must pass validation, cell by cell, before counting.
- **The conservative bound may be too harsh.** A back-of-queue order can fill without the price
  trading through, when the queue ahead cancels. The truth for a small resting order lies between
  the two bounds. The answer leans on the harsh one on purpose.
- **Sizes.** Measured costs are for a fill of a size that does not walk the book. Above the
  displayed size at the touch, impact is extra and not measured here.
- **Hyperliquid's sample is small.** It has 24 days, so day-clustered t-statistics there are weak.
  A NO there is weaker evidence than a NO on B.
- **Regime.** V1 is 2023–24; B and V2 are 2026. The validation asks the proxy to work in both.

## Multiple testing

Covered by the bar above: 39 earlier tests plus every Q3 cell, counted before any data. Q1 and Q2
are measurement and information, not hypothesis tests. Their t-statistics are printed with no
pass/fail claim except Q2's stated standard.

## Transparency — what I saw before writing this

- **Archive listings** (file names only) for `bookTicker`, monthly `bookTicker` and October 2026
  `aggTrades`. **HEAD sizes** for four zips. **101-byte range requests** on Tardis files, which
  confirmed they exist and returned compressed bytes, never decoded. One Tardis file was opened by
  mistake, a binary gzip printed to the terminal for 300 bytes; it was not decoded and nothing was
  read from it.
- **Hyperliquid's symbol list** from Tardis's API.
- **The header and one or two rows** of `data/aggr/holdout/2026-10.csv.gz` (ADA, two hours),
  `levetf_days`, `bids_events`, `fillcost_events` and `settle_events` (#19's; not used).
- **The results of #28, #30 and #33**, as published in this repo.
- No tick, quote or markout from any set above has been computed or seen.

## Outcomes, fixed now

- **`espero/costs.py` ships either way.** It holds the measured table and
  `round_trip(venue, coin, entry, exit, condition)` in bps, raising for unmeasured coins. Frozen
  tests keep their own hurdles. New tests may import it.
- **YES on Q3**: the next test pre-registers a forward paper quoting rule in the passing cell. It is
  paper only, as always.
- **NO on Q3**: rules that depend on maker fills are priced at the conservative bound from now on,
  and "rest a bid and wait" ideas are closed for this account's size and venues unless a new data
  source changes the picture.
- **The venue note**: `research/VENUE_CONFIRMATION.md` is written either way. It covers what it
  would take to confirm these costs with real fills on a venue a US person may legally use:
  instrument, minimum size, and how fills would be reconciled against the exchange's statements.
  Nothing is placed.

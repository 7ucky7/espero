# Forward paper test — #26's rule live, both sides (#27)

Committed **before** any bar of the forward window is recorded. A paper test: nothing trades. The
twenty-eighth test in this repo.

## Why

#26 ([RESULTS_LIQ2.md](RESULTS_LIQ2.md)) passed: on 429 days of Binance COIN-M liquidations
(June 2023 → October 2024), breaks made of liquidations faded 23.6 bps more over the next hour than
organic ones, and buying the forced down-breaks earned +23.5 bps an hour. Its pre-registration
requires a forward test before anything trades, and #25 adds a reason: the forced/organic split, as
open interest measures it, has weakened since 2024, after #26's window ends. A look at #26's events
after its verdict (information only, not claimable) also suggested the other side: organic
down-breaks did not bounce, and up-breaks faded over 4 hours whether forced or not. This test records
all of it on data that does not exist yet.

## Data — fixed

- **Liquidations**: aggr's public **5-minute** bars (`api.aggr.trade`, as #22), longs (`lsell`) and
  shorts (`lbuy`) liquidated, summed over Binance futures (USDⓈ-M), Bybit and OKX, for aggr's 14
  coins (`espero/aggr.py`). aggr keeps 5-minute bars only for days, so the daily job saves each
  complete UTC day into `data/aggr/forward5m/`.
- **Prices and volume**: Binance USDⓈ-M 5-minute klines from the daily archive, as recorded for #24
  (`data/lows/forward/`).
- **Forward window**: events on UTC days **2026-10-30 → 2027-03-31**.

This is not #26's data: USDⓈ-M plus Bybit and OKX instead of COIN-M, aggregated into 5-minute bars
instead of single liquidations, 14 coins instead of 26. A liquidation counts toward a break's hour
when its 5-minute bar opens inside it, as `liq.events` counts single liquidations by time.

## The rule — #26's (`espero.liq`, unchanged)

The 打板 trigger and its mirror, one per coin per direction per hour, breaks closing 01:00 → 24:00
UTC; forced share s = liquidations on the break's side in the hour before ÷ the hour's Binance quote
volume; within-day terciles of s (days with at least 6 events); y = the return in the break's
direction from the next bar's open, at 15 minutes, 1 hour and 4 hours.

## Evaluation — once, after 2027-03-31

Each UTC day's mean is one observation.

**PASS requires all four** (the trade #26 would make: buy forced down-breaks, hold 1 hour):

1. **The trade**: the long 1-hour return of forced down-breaks has a mean **> 0, t ≥ 3**.
2. **It pays**: that mean is **above 18 bps** with **t > 2**.
3. **The rule's own claim**: D (forced − organic, both directions, as #18 and #26) **< 0**.
4. **Not one stretch**: criterion 1's mean > 0 in each half (Oct 30 → Dec 31; Jan 1 → Mar 31).

**Recorded beside it, judged on their own, information only unless a later document says otherwise:**
the six groups (forced, middle, organic × up-breaks, down-breaks) at 15 minutes, 1 hour and 4 hours;
in particular **organic down-breaks** (the "do not buy" filter) and **up-breaks at 4 hours as a
paper short** (the inverse side, which this account cannot trade).

## Outcomes — fixed now

- **PASS**: a document for real-money sizing and execution, written before any order.
- **2 fails, 1, 3, 4 hold**: real, not tradable; nothing ships.
- **Anything else: FAIL.** No stopping early on the running numbers.

## Known confounds

- Different liquidation source from #26 (above); Binance's feed is sampled (one a second per coin).
- 14 coins, mostly majors; five months.
- aggr is one person's free server; a gap of more than a week in its 5-minute bars ends the test early
  as inconclusive.

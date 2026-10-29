# Result — leveraged ETFs push crypto into the US close (#28)

**Verdict: FAIL on all four criteria.** BTC and ETH do not drift with the day's move in the last 15
minutes before 16:00 ET: −1.5 bps (t −1.44) on 596 trading days since June 2024. That is no
different from weekends, and below the years before the funds existed.

What the run showed instead is the opposite end of the same flow, and the pre-registration had
listed it as information only: **after the close, the US session's move reverses.** It is −6.0 bps
in the first 15 minutes (t −5.6) and −8.1 bps by 17:00 (t −3.7), on trading days only. It was found
on data already read, so it is a lead, not a result. #29 tests it forward.

Spec: [PREREGISTRATION_LEVETF.md](PREREGISTRATION_LEVETF.md) (`cd74280`, before any bar at these
times was read); code `3a56a02`. One run, output in [levetf_run.txt](levetf_run.txt), rows in
[levetf_days.csv.gz](levetf_days.csv.gz).

## Data

- Binance USDⓈ-M 5-minute bars for BTC and ETH, 2020-01-01 → 2026-10-27, from #20's cache plus the
  monthly and daily archives. 28 October was not yet published, so the last date has no bars.
- The hard-coded NYSE calendar matched SPY's sessions on every date.
- Dates with a primary observation:

  | era | trading days | closed days |
  |---|---|---|
  | *with* | 596 | 274 |
  | *ramp* | 234 | 107 |
  | *before* | 871 | 396 |

## Criteria

| # | criterion | required | actual | met |
|---|---|---|---|---|
| 1 | the push | *with*-era trading days > 0, t ≥ 3 | −1.5 bps, t −1.44, 596 days | **no** |
| 2 | only when the ETFs trade | minus closed days > 0, t ≥ 2 | −1.1 bps, t −0.81 | **no** |
| 3 | only since the ETFs exist | minus *before*-era trading days > 0 | −2.6 bps, t −1.38 | **no** |
| 4 | it pays | \|r\| ≥ 2% days > 18 bps, t > 2 | −0.8 bps, t −0.46, 379 days | **no** |

## What the tables say

1. **No push into the close on BTC or ETH.** There is a hint of one in the year the first 2x bitcoin
   fund was new: 2023 +5.2 bps (t 2.8), the ramp era +3.9 bps (t 2.6). By 2025 it is gone, and in
   2026 the last 15 minutes go *against* the day's move: −5.1 bps (t −3.6). Either the flow is now
   hedged earlier in the afternoon, or it is too small for these markets.

2. **The reversal after the close.** Information only, and the strongest number in the run. On
   *with*-era trading days, the move since the previous close reverses:

   | | 16:00 → 16:15 | 16:00 → 17:00 |
   |---|---|---|
   | trading days | −6.0 bps (t −5.6) | −8.1 bps (t −3.7) |
   | closed days | −1.1 bps (t −0.9) | −0.5 bps (t −0.2) |
   | *before*-era trading days | −2.8 bps (t −1.9) | −2.8 bps (t −1.0) |

   An exploration after the verdict, on the same data (BTC and ETH only, the other coins left unread),
   found three things:
   - **It grows with the day's move**, about as a price impact should. At 15 minutes, by fifth of
     |r|: +0.2, −7.3, −4.4, −9.1, −11.2 bps.
   - **It holds in every year**: 2024 −6.4 (t −2.9), 2025 −6.7 (t −3.8), 2026 −4.9 (t −3.0).
   - **It holds on every weekday.**

   The reading is that the US session's flows (spot ETF creations, leveraged-ETF hedges, US desks)
   push the price during the session, and part of that push wears off once they stop at 16:00. It is
   the forced-flow reversal of #26, on a clock.

   It is small. On days with |r| ≥ 2% it is −6.9 bps at 15 minutes and −10.5 bps at 1 hour: under a
   9 bps taker round trip, never mind the 18 bps bar. As found, it is an **execution edge**: on an
   up day, a buyer pays about 6–10 bps less by waiting until after 16:00 ET, and on a down day a
   seller gets that much more.

3. **Where the push does appear: smaller coins with large leveraged funds.** From 2025-04-08, when
   2x SOL and XRP funds trade:

   | | trading days | closed days |
   |---|---|---|
   | XRP | +8.1 bps (t 4.0) | −2.3 bps |
   | SOL | +3.3 bps (t 1.9) | −0.6 bps |

   This is the predicted push, where the funds are large next to the coin's market rather than on
   BTC and ETH. Information only, about 400 dates.

4. **Crypto's own daily close used to have a push.** At 23:45 → 00:00 UTC it was +5.5 bps (t 5.3) in
   2020–23, and −0.2 bps since June 2024. An effect that existed and is gone.

5. **No clock effect.** The placebo windows (11:45 ET, closed days) are flat.

## What this changes

Nothing ships. The reversal after the close is pre-registered as a forward test (#29,
[FORWARD_POSTCLOSE.md](FORWARD_POSTCLOSE.md)), on the 5-minute files #24's recorder already
saves every day. The push on SOL and XRP is recorded beside it, as information.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 26 | #18's rule on every day of COIN-M liquidations | PASS: forced breaks fade 23.6 bps more, t −4.1 |
| **28** | **Leveraged-ETF rebalancing pushes BTC/ETH into the 4 pm ET close** | **fail**: −1.5 bps, t −1.4. Lead: the session's move reverses after the close, −6.0 bps in 15 min (t −5.6) |

# Pre-registration — leveraged ETFs push crypto into the US close (#28)

Committed **before** any bar is read at the times this test uses. The twenty-ninth test in this repo.

## Why this hypothesis

The two effects that survived here, #26 (liquidations) and #12 (funding), both trade **flow someone
is forced to make**. This test looks for a forced flow that is scheduled and can be computed in
advance.

**The mechanism.** Take a fund that promises L times an asset's daily return and holds assets A. After
the asset moves r during the day, the fund's exposure has drifted. To restore L for the next day, it
must trade

  ΔE = A · L · (L − 1) · r / (1 + L·r)  ≈  A · L(L − 1) · r

- For a 2x fund (L = 2) that is 2·A·r. For a −1x fund (L = −1) it is also 2·A·r. For −2x it is 6·A·r.
- Every leveraged or inverse fund therefore **buys after up days and sells after down days**: the
  same direction as the day's move, in an amount known before the close.
- The US 2x and inverse bitcoin and ether ETFs rebalance to their 4 p.m. ET valuation. They hold CME
  futures and swaps, and CME's crypto futures settle daily on trades just before 15:00 CT
  (16:00 ET). Counterparties hedge into that minute, and arbitrage carries the flow to Binance and
  the rest within seconds.
- The first 2x bitcoin ETF (BITX) began trading on 2023-06-27. 2x ether ETFs followed in June 2024.
  By 2025 the group held billions of dollars, so a 3% day asks for hundreds of millions of dollars
  of futures in the last minutes.

In US stocks this effect is documented: late-day momentum from leveraged-ETF rebalancing (Cheng &
Madhavan 2009; Bai, Bond & Hatch 2015) and intraday momentum into the close (Gao, Han, Li & Zhou
2018). I know of no test of it in crypto, where the funds are new and most traders never look at
the US close.

**The prediction.** On NYSE trading days since the funds exist, BTC and ETH drift in the direction
of the day's move in the last 15 minutes before 16:00 ET. They do not do so at the same clock time
on weekends and holidays (no ETF trades), nor before the funds existed.

## Data — fixed

- **Bars**: Binance USDⓈ-M perpetual **5-minute** klines, BTCUSDT and ETHUSDT (primary); SOLUSDT and
  XRPUSDT (information only).
  - 2020-01 → 2026-03: #20's cache, `data/lows/`. #20 used these bars for 4-hour lows; nobody has
    looked at the US-close windows.
  - 2026-04 → 2026-09: the monthly archive; 2026-10-01 → 2026-10-28: the daily archive. Both are new
    downloads into `data/levetf/` (not committed).
  - A missing bar leaves that coin's day empty, never filled in.
- **Days**: Eastern-time calendar dates **2020-01-01 → 2026-10-28**, classified with a hard-coded NYSE
  calendar in `espero/levetf.py` (full holidays and 13:00 early closes):
  - **trading**: a full NYSE session;
  - **early**: a 13:00 close;
  - **closed**: weekends and holidays.

  The calendar is checked against SPY's daily bars in `data/trend/` (#15's snapshot). Any mismatch
  stops the run before a number is printed and is fixed as a bug.
- **Clock**: America/New_York through `zoneinfo`, so daylight saving moves 16:00 ET between 20:00
  and 21:00 UTC.

## The rule — frozen

For each date d and coin. P(t) is the **open** of the 5-minute bar opening at t, and P⁻(t) is the
**close** of the bar ending at t.

- **Reference** R(d):
  - on a trading day, the close of the previous trading or early day: 16:00 ET, or 13:00 ET after an
    early close;
  - on a closed day, 16:00 ET of the previous calendar date.
- **The day's move**: r = P⁻(15:45 ET) / P(R) − 1, known at 15:45.
- **Signed late return**: y = sign(r) × (P(16:00 ET) / P(15:45 ET) − 1). Enter at the open of the
  15:45 bar, after the signal's bar has closed. Exit at the first trade at or after 16:00. r = 0 is
  dropped.
- **Each date's observation** is the mean of the coins' y that date (BTC and ETH).
- **Eras**:
  - **before**: 2020-01-01 → 2023-06-26 (no 2x fund; a −1x bitcoin fund of about $0.1B from mid-2022);
  - **ramp**: 2023-06-27 → 2024-06-03 (information only);
  - **with**: 2024-06-04 → 2026-10-28.
- Early-close days are never targets.

## Evaluation — fixed

Dates are the observations: t = mean ÷ (sd ÷ √dates). For differences, Welch's t on the two sets of
dates.

**PASS requires all four:**

1. **The push**: on *with*-era trading days, mean y > 0, **t ≥ 3**.
2. **Only when the ETFs trade**: the *with*-era trading-day mean minus the *with*-era closed-day mean
   (same clock, same construction) **> 0, t ≥ 2**.
3. **Only since the ETFs exist**: the *with*-era trading-day mean minus the *before*-era trading-day
   mean **> 0**.
4. **It pays**: on *with*-era trading days, coin-days with |r| ≥ 2% have a mean y **above 18 bps** (two
   Hyperliquid taker round trips, the bar #18, #20, #21 and #26 used) with **t > 2**, each date's
   mean one observation.

**Information only:**
- each coin; each year; the ramp era; the *before* era's closed days;
- other windows: 15:30 → 16:00, 15:55 → 16:00 (the last bar), and after the close 16:00 → 16:15
  and 16:00 → 17:00, signed by r up to 16:00. A temporary push should reverse;
- placebo clocks:
  - 11:45 → 12:00 ET on trading days, signed by r from R to 11:45;
  - 23:45 → 00:00 UTC on every date, crypto's own daily close, signed by r from the previous
    00:00 UTC;
- quintiles of |r| on *with*-era trading days (the flow is proportional to r);
- SOL and XRP on 2025-04-08 → 2026-10-28 (2x funds from spring 2025);
- net of one Hyperliquid round trip (9 bps).

## Outcomes — fixed now

- **PASS**: `research/FORWARD_LEVETF.md` before anything trades. Then a paper ledger in the daily job:
  decide at 15:45 ET, exit at 16:00 ET.
- **Criteria 1–3 hold, 4 fails**: "real, not tradable after costs". A maker-execution version may be
  pre-registered next.
- **Anything else: FAIL.** Not re-tuned on this data.

## Known confounds

- **Equity late-day momentum** can reach crypto through correlation. Criterion 3 and the 11:45
  placebo separate part of it. A pass from that source is still a flow into the US close, the same
  trade.
- **Timing of the hedge**: issuers' counterparties may trade over the afternoon or at the settlement
  price, so 15 minutes may catch only part of the flow.
- **AUM is not measured.** The eras stand in for it.
- **Binance perpetual prices**, not CME or spot. **The day after an early close** uses 13:00 as its
  reference; the early day itself is never a target.
- **16:00 ET is also the top of an hour** (Hyperliquid settles funding hourly). The closed-day
  placebo at the same clock covers clock effects.

## Multiple testing

One primary measure, on two coins pooled into one observation per date. The information rows are
reported as such.

## Transparency — what was seen before this commit

No bar at the times this test uses. The 5-minute bars were downloaded for #20 and read only for
4-hour lows. I know of general talk about bitcoin's US-hours seasonality, the equity literature
above, and the repo's earlier results.

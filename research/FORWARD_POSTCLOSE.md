# Forward test — the US session's move reverses after the close (#29)

Committed **before** any bar of the forward window exists. A paper test: nothing trades. The
thirtieth test in this repo.

## Why

#28 ([RESULTS_LEVETF.md](RESULTS_LEVETF.md)) failed its own hypothesis, that leveraged ETFs push BTC
and ETH into the 4 p.m. ET close. As information, it showed the other end of the flow.

On NYSE trading days since June 2024, the move from the previous US close to this one **reverses
after 16:00 ET**:
- −6.0 bps in 15 minutes (t −5.6) and −8.1 bps by 17:00 (t −3.7);
- not on weekends and holidays (−1.1 bps);
- weaker before the ETFs existed (−2.8 bps).

An exploration after the verdict found it growing with the size of the day's move, present in 2024,
2025 and 2026, and on every weekday.

The reading: the US session's flows (spot-ETF creations, leveraged-ETF hedges, US desks) push the
price while they run, and part of the push wears off once they stop at the close. That is #26's
forced-flow reversal, on a clock. All of it was seen on #28's data; this test runs on days that do
not exist yet.

## Data — fixed

- **Bars**: Binance's daily 5-minute USDⓈ-M archive, as #24's job (`espero/lowsfwd.py`) records it
  into `data/lows/forward/` for the 42 coins of `xs.UNIVERSE`, 2026-10-29 (the first reference close)
  → 2027-03-31. No new recording.
- **Window**: Eastern dates **2026-10-30 → 2027-03-31**.
- **Calendar**: `espero/levetf.py`'s NYSE calendar, with 2027's holidays added in this test's code
  commit, before the window opens. At judgment it is checked against SPY's daily bars. A session the
  calendar gets wrong (an unscheduled closure) is corrected from SPY, as a fact, before any number.
- **Gaps**: a day's file still missing after a week (#24's rule) drops that coin's dates; nothing is
  filled in.

## The rule — #28's code, unchanged

For each date and coin:
- r = P⁻(16:00 ET) / P(R) − 1: the move from the previous session's close to 16:00 ET. R is 13:00
  after an early close; on a closed day it is 16:00 ET the day before.
- post15 = sign(r) × (P(16:15 ET) / P(16:00 ET) − 1), and post60 likewise to 17:00.
- A negative post is a reversal; fading the move earns −post.
- Early-close days are never targets. Each date's observation is the mean of BTC's and ETH's.

## Evaluation — once, after 2027-03-31

Dates are the observations.

**PASS requires all four:**

1. **The reversal holds**: on trading days, mean post15 < 0, **t ≤ −3**.
2. **Only when the US trades**: the trading-day mean is below the closed-day mean (same construction).
3. **Not one stretch**: mean post15 < 0 in each half (2026-10-30 → 2026-12-31; 2027-01-01 →
   2027-03-31).
4. **It pays**: on trading days with |r| ≥ 2%, fading from 16:00 to 16:15 earns **more than 18 bps**
   (two Hyperliquid taker round trips) with **t > 2**, each date's mean one observation.

**Information only:**
- post60;
- each coin;
- SOL and XRP: the push into the close (#28's 15:45 → 16:00) and their reversal;
- all 42 recorded coins' post15, equal-weighted per date;
- by month; closed days alone;
- net of one Hyperliquid taker round trip (9 bps) and of a maker round trip (3 bps).

## Power, said in advance

#28's estimate is −6.0 bps, with a date's mean varying by about 26 bps. At that size, about 100
trading days give an expected t near −2.3. Criterion 1 needs the effect about 30% larger, or luck.
A FAIL on criterion 1 alone would not prove the reversal gone.

Criterion 4 is not expected to hold (#28's big days gave −6.9 bps). It is there so that nothing is
called tradable that is not.

## Outcomes — fixed now

- **PASS**: a document for sizing and execution, before any order.
- **1–3 hold, 4 fails**: real, not tradable as a trade. It is recorded as an **execution rule** for
  the repo's own orders: near the US close, wait for the reversal before buying on an up day or
  selling on a down day. Any account that uses it needs its own document first.
- **Anything else: FAIL.** No stopping early on the running numbers.

## Known confounds

- **Five months, winter only** (EST: 16:00 ET is 21:00 UTC). One observation per trading day.
- **Found on BTC and ETH.** The other 40 coins move with them, so their rows are information, not
  independent evidence.
- **The flows are not measured** (ETF creations, hedges).
- **Binance perpetual prices.** Hyperliquid's differ by its spread.
- **Early closes** (2026-11-27, 2026-12-24) are excluded; the days after use 13:00 as their reference.

## Transparency — what was seen before this commit

#28's run, and its exploration of BTC and ETH after the verdict (by size of move, year and weekday).
The SOL and XRP rows of #28's run. No bar from the forward window, which starts tomorrow. The other 38
coins' bars at these times have not been read.

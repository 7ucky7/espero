# Pre-registration — resting bids catch forced sellers (#30)

Committed **before** any breakdown event in this test's months is computed and before any fill is
simulated. The thirty-first test in this repo.

## Why this hypothesis

Three effects here are real but die on taker costs:
- #19: the swing around funding settlement;
- #20: the bounce after new 4-hour lows, +14.8 bps in an hour (t 9.8) against an 18 bps bar;
- #29's lead: the reversal after the US close.

#26 says the selling behind such breaks is forced, and forced sellers must hit whatever bids exist.
A scalper does not buy the bounce at the market afterwards. They **rest bids below the price while
the forced selling is still running**, and let it fill them at the overshoot, paying a maker fee.
On Hyperliquid a maker fill costs 1.5 bps; a taker fill costs 4.5 bps plus the spread.

**The risk is adverse selection.** A resting bid fills most often when the fall keeps going. #20
measured the bounce from the next bar's open, on every event. A bid fills only on the events that
fall further, and only those count here. Whether that subset still bounces, and by enough, is the
question.

## Data — fixed

- **Bars**: Binance USDⓈ-M **5-minute** klines for the 42 coins of `espero/xs.py::UNIVERSE`, #20's
  symbols.
  - March 2026 is warm-up only, from #20's cache.
  - April → September 2026: monthly archives. 1 → 27 October 2026: daily archives.
  - The files come from #20's cache (`data/lows/`) and #28's (`data/levetf/`) where present, and are
    downloaded into `data/bids/` otherwise (not committed).
  - A missing file is recorded and never substituted.
- **Events**: UTC days **2026-04-01 → 2026-10-26**, excluding #18's days (the first of each month
  with the day before and after), as #20 did.

## The rule — frozen

- **Trigger**: #20's exactly (`liq.triggers`' `down`). The close is below the lowest low of the
  previous 48 bars, volume z ≥ 2, the last hour is down, ATR(14) > 0. One event per coin per hour,
  as `lows.events` counts them.
- **The bid**: at the trigger bar's close C, rest a bid at **L = C − 1 × ATR** (the trigger bar's
  14-bar ATR) for the next **12 bars** (one hour).
- **Fill**: in the first of those bars whose low is **below L × (1 − 0.0001)**, at **L**.
  - The price must trade at least 1 bp through the bid, a margin for queue position.
  - A resting bid never fills below its own price, even on a gap down.
- **Exit**, whichever comes first, looking only at bars **after** the fill bar:
  - a resting sell at **C** (the trigger close) fills in the first bar whose high is above
    C × (1 + 0.0001), at C (maker);
  - otherwise the position is sold at the close of the **12th bar after the fill bar** (taker).
- **Costs** (Hyperliquid's base fees): 1.5 bps per maker fill; 4.5 bps plus 2 bps of slippage per
  taker fill.
- **The taker baseline**, on the same events (#20's trade): buy at the next bar's open and sell at
  the close of bar t+12, both as taker. That is #20's 1-hour return minus 13 bps.
- **Gaps**: an event whose 24 bars after the trigger are not all present is dropped, from both
  rules.

## Evaluation — fixed

Each UTC day's mean is one observation: t = mean ÷ (sd ÷ √days).

**PASS requires all four:**

1. **It pays**: filled trades' mean net return **≥ 5 bps, t ≥ 3**.
2. **The bid beats taking**: per event, the bid's result (its net return if filled, 0 if not) minus
   the taker baseline's net return: mean **> 0, t ≥ 2**.
3. **Not one stretch**: filled trades' mean net > 0 in each half, 2026-04-01 → 06-30 and
   07-01 → 10-26.
   - These are the months of the aggr exploration, where liquidation reversals showed, and of #21,
     where they did not.
4. **Not one coin**: among coins with at least 20 fills, **more than half** have a positive mean net.

**Information only:**
- bid depths of 0.5 and 2 ATR;
- fills on a touch (no 1 bp margin);
- a 4-hour exit instead of 1 hour;
- a target of the entry plus 1 ATR instead of the trigger close;
- the fill rate and the exit mix;
- **adverse selection**: #20's gross 1-hour return on filled against unfilled events;
- the taker baseline alone;
- by month, by coin, BTC and ETH.

## Power, said in advance

About 190 days. If a day's mean net varies by about 40 bps, t ≥ 3 needs a mean of roughly 9 bps per
fill. Criterion 1's 5 bps floor is a margin for what a 5-minute fill model cannot see (queue
position, partial fills).

## Outcomes — fixed now

- **PASS**: `research/FORWARD_BIDS.md` before anything trades. Then a paper ledger of the same rule
  on #24's recorded bars from 2026-10-30, with #27's forced breaks recorded beside it.
- **Anything else: FAIL.** If 1, 3 and 4 hold and 2 fails, the result is described as "it pays, but
  no better than taking". Not re-tuned on these months.

## Known confounds

- **A 5-minute fill model.** A bar's low says the price traded there, not that our bid was reached
  in the queue. The 1 bp margin and the 5 bps floor are the allowance. Within the fill bar, the
  target is never allowed: the order of the low and the high is unknown, and assuming the low came
  first would flatter the rule.
- **Overlap.** A fill can come up to an hour after the trigger and be held an hour more, so a coin
  can hold two positions at once. The test measures per-trade results, not an account.
- **No stop-loss.** The timed exit is the only protection, and a crash can run through it.
- **Binance perpetual prices with Hyperliquid's fees.** Hyperliquid's book is thinner.
- **Survivorship**: today's coin list.

## Transparency — what was seen before this commit

- #20's result (2020 → March 2026, the bounce from the next open); #26 and #27.
- The aggr exploration of April–June 2026 (prices came back after the biggest liquidation hours).
- #21's result on July–October 2026 (that reversal did not hold).
- #28's reads of BTC, ETH, SOL and XRP at US-close clock times in these months.

No breakdown event in April–October 2026 has been computed, and no fill model has ever been run in
this repo.

# Forward test — deep resting bids under breakdowns (#31)

Committed **before** any bar of the forward window exists. A paper test: nothing trades. The
thirty-second test in this repo.

## Why

#30 ([RESULTS_BIDS.md](RESULTS_BIDS.md)) rested a maker bid one ATR under each of #20's breakdowns
and failed: +1.7 bps net per fill. The run measured why. A shallow bid fills on ordinary
continuation, and the breakdowns that came down to it went on to fall (−21.7 bps), while the ones
that never did bounced (+63.9 bps).

Its information rows, and an exploration after the verdict on the same months (April → October
2026), found that **deeper bids pay**:

| variant | fills | net per fill | halves | coins positive |
|---|---|---|---|---|
| 2 ATR, 1-hour exit | 41% | +12.5 bps (t 5.2) | both > 0 | 23 of 40 |
| **2 ATR, 4-hour exit** | 41% | **+20.0 bps (t 6.4)** | both > 0 | **34 of 40** |
| 3 ATR, 1-hour exit | 26% | +18.4 bps (t 5.4) | both > 0 | 30 of 40 |

A deep bid fills only when forced selling overshoots, and buying the overshoot paid in every month.
This test takes the 2-ATR bid with a 4-hour exit: the row with the widest breadth, at a depth with
twice #30's fills at 3 ATR.

It was the best of five variants looked at, so its forward size should be expected smaller than
+20 bps. That is the price of choosing it on old data. As precedent, #24 likewise took #20's
information-only 4-hour horizon forward.

## Data — fixed

- **Bars**: Binance's daily 5-minute USDⓈ-M archive, as #24's job (`espero/lowsfwd.py`) records it
  into `data/lows/forward/` for the 42 coins of `xs.UNIVERSE`. 2026-10-29 is warm-up; the window
  runs to 2027-03-31. No new recording.
- **Events**: UTC days **2026-10-30 → 2027-03-31**. Nothing is excluded: #18's days were left out of
  #20 and #30 only because #18 had used them.
- **Gaps**: a day still missing after a week (#24's rule) drops the events whose bars it holds.
  Events too late on 2027-03-31 to finish inside the window are dropped.

## The rule — #30's code (`espero/bids.py`), with #31's settings

- **Trigger**: #20's breakdown, one per coin per hour.
- **Bid**: **2 ATR** below the trigger close, resting 12 bars. It fills at its price when the low
  trades 1 bp through it.
- **Exit**: a resting sell at the trigger close (the price must trade 1 bp through it, never in the
  fill bar). Otherwise the close **48 bars (4 hours)** after the fill bar.
- **Costs**: 1.5 bps per maker fill; 4.5 bps plus 2 bps of slippage per taker fill.
- **The taker baseline** on the same events is #24's trade: buy at the next bar's open, sell at the
  close 48 bars after the trigger, taker costs on both sides.

## Evaluation — once, after 2027-03-31

Each UTC day's mean is one observation.

**PASS requires all four:**

1. **It pays**: filled trades' mean net **≥ 5 bps, t ≥ 3**.
2. **The bid beats taking**: per event, the bid's result (net if filled, 0 if not) minus the taker
   baseline's net: mean **> 0, t ≥ 2**.
3. **Not one stretch**: filled trades' mean net > 0 in each half (2026-10-30 → 12-31; 2027-01-01 →
   03-31).
4. **Not one coin**: among coins with at least 20 fills, **more than half** are positive.

**Information only:**
- the 1-hour exit; 3-ATR bids;
- the fill rate and the exit mix;
- adverse selection (#20's 1-hour return, filled against unfilled);
- by month, by coin, BTC and ETH;
- the forced share of #27's events where both cover a coin.

## Power, said in advance

#30's months gave +20.0 bps with a day's mean varying by about 43 bps. At that size, about 150 days
give an expected t near 5.7; at half the size, about 2.8. Criterion 2 may fail even if the bid pays:
over 2020–26, #20's 4-hour bounce at the market averaged +37.8 bps gross, about +25 bps net per
event. If taking is better per event, #24 is the trade to pursue, and this test says so.

## Outcomes — fixed now

- **PASS**: a document for sizing and execution before any order, starting on Hyperliquid's testnet.
- **1, 3 and 4 hold, 2 fails**: "FAIL (it pays, but no better than taking)"; #24 is the better trade.
- **Anything else: FAIL.** No stopping early on the running numbers.

## Known confounds

- **The 5-minute fill model** (#30's): a bar's low is not our place in the queue. The 1 bp margin and
  the 5 bps floor are the allowance.
- **Selection**: chosen as the best of five variants on old data (above).
- **Overlap**: with 4-hour holds a coin can hold several positions at once. Per-trade results, not
  an account.
- **Winter months**, one market regime. Binance prices with Hyperliquid's fees.
- **Survivorship**: today's coin list.

## Transparency — what was seen before this commit

#30's run and its exploration after the verdict (2 ATR at 1 and 4 hours, 3 ATR at 1 hour, on
April → October 2026). No bar from the forward window, which starts tomorrow.

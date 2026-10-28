# Pre-registration — funding carry with a swap gap and maker execution (#12)

Committed before the run. **This is a post-hoc hypothesis** and says so: it exists because #11
([RESULTS_CARRY.md](RESULTS_CARRY.md)) showed that 55 of 75 exits were the rule swapping a held
coin for one paying marginally more, and that fees took 55% of the funding collected. The data is
the same data #11 ran on; nothing new is fetched. That makes this a test of two specific,
pre-stated changes on a sample that has already been looked at once, and the result must be read
with that discount. If it passes here it has earned a forward test, not a conclusion.

## What changes from #11 — frozen

Everything in [PREREGISTRATION_CARRY.md](PREREGISTRATION_CARRY.md) holds (universe, data, entry
above 15% annualised on the trailing week, exit below 5%, 30-day time stop, five coins, 1×, half
the capital on each leg, the primary window where the basis can be marked) except:

**1. Hysteresis on swaps.** A held coin is replaced by a candidate only if

```
candidate f_ann  −  held f_ann  ≥  5 percentage points      (the gap)
and the held coin has been held  ≥  7 days                  (the minimum hold)
```

Exits for `funding_low` and the 30-day time stop are unchanged and ignore the minimum hold. A
free slot is still filled by any qualifying candidate without a gap test.

**2. Maker execution on both legs.** Resting limit orders, filled at the hour's close:

| leg | #11 (taker) | #12 (maker) |
|---|---|---|
| spot, Binance.US | 2 bps + 5 bps slippage | **0 bps + 0 slippage** |
| spot, Kraken (criterion 5) | 40 bps + 5 bps | **25 bps + 0** |
| perp, Hyperliquid base tier | 4.5 bps + 5 bps | **1.5 bps + 0** |

A round trip falls from 33 bps to **3 bps** on Binance.US. This is the optimistic end: a resting
order is not guaranteed to fill at the close, and the hour it waits is unhedged. The model does not
charge for that, and the result is therefore an **upper bound** on what maker execution can do;
the gap between it and #11 is the most that execution is worth. Both numbers are written down
before the run.

## Criteria — unchanged

The five of #11, all required, on the primary window: net annualised on equity > 8%, max drawdown
< 5%, Sharpe > 1.5, funding paid < 25% of received, net > 4% with the spot leg on Kraken (maker)
fees. Also reported, not criteria: the same rule with #11's taker costs (isolates the gap's
effect) and #11's rule with maker costs (isolates execution's effect).

**On PASS** the strategy earns a 30-day paper forward test on Hyperliquid data with live hourly
funding, at these costs; the pass is provisional until then. **On FAIL** carry is closed in this
repo at retail scale and `carry scan` stays as a view.

## Multiple testing

Thirteenth test, the second on this sample. The gap (5 points), the minimum hold (7 days) and the
maker assumptions are the first values written down. One run, no re-tuning. If this fails, no
#13 on carry is run on this data.

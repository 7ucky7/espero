# Liquidity provision — paper simulation

**Verdict: at $500 the rewards do not cover the inventory risk on a moving market.** Not a bug in the
simulation — a property of the trade.

Code: [lp_sim.py](lp_sim.py), scanner: [lp_scan.py](lp_scan.py). Public data only, no keys, no orders.

## What was simulated

Quote a bid and an ask around the mid on one Polymarket market, accrue the market's reward pool
pro-rata to your size, mark inventory to market. Fills are inferred from midpoint crossings (crude,
and generous to the strategy — see caveats).

Market: *Will Likud win the most seats in the 2026 Israeli election?* — $1,023/day pool, $284,729 of
liquidity, hourly price history for 30 days, $500 bankroll, $125 per side.

| half-spread | bid fills | ask fills | rewards | trading P&L | total |
|---|---|---|---|---|---|
| 1¢ | 37 | 34 | $12.48 | −$258.32 | **−$245.85 (−49.2%)** |
| 2¢ | 12 | 10 | $12.48 | −$128.18 | **−$115.71 (−23.1%)** |
| 4¢ | 5 | 2 | $12.48 | −$80.32 | **−$67.84 (−13.6%)** |

*Erratum 2026-10-28:* the trading P&L column first printed here subtracted the rewards a second
time (lp_sim.py counted them out of a cash balance they were never added to); each row was $12.48
too low. The totals were right and are unchanged; the conclusion is unchanged.

Rewards are ~$0.42/day. The inventory loss is $2.3–$9/day. Tightening the spread buys more fills and
more reward eligibility, and loses faster — the classic adverse-selection shape.

## Why the ratio does not improve with capital

Rewards scale with your notional. Inventory risk scales with your notional. **The ratio between them is
a property of the market, not of your bankroll.** Moving from $500 to $5,000 multiplies both sides by
ten; it does not make liquidity provision profitable. What changes the ratio:

- **volatility** — quote markets that are not resolving tomorrow (this one resolved the day after the
  sample ended, so the price trended, which is the worst path for a two-sided quote)
- **reward subsidies** — new markets pay outsized rates to bootstrap liquidity, which is why the
  scanner's top row showed a 131% implied pool APY
- **inventory limits and hedging** — stop quoting one side when inventory is too large, or hedge with
  the complementary token; both reduce reward eligibility and require real engineering

## Caveats

- Fills are inferred from midpoint crossings, not from the book: no queue position, no partials, and
  probably too many fills. Treat the trading P&L as a lower bound on the pain, not a forecast.
- Rewards assume full uptime, two-sided quoting, and constant liquidity — all optimistic.
- One market, one 30-day window, one regime.
- No gas, no withdrawal costs, no resolution P&L.

## What this does not invalidate

The scanner's finding stands: Polymarket pays ~$9,500/day across reward markets, and the implied yield
on qualifying liquidity is 10–130% annualised. Somebody earns that. The simulation says it is not a
passive $500 account quote-and-forget; it is a market-making job with inventory risk, exactly like the
LP tool repo we reviewed — which is why that repo is a *repricer with anti-sniping*, not a "set it and
earn" bot.

# Pre-registration — Ethena's USDe flows forecast funding (#36)

Committed before USDe's supply is set against funding. The thirty-seventh test in this repo.

## Why

#12's carry collects funding. USDe, Ethena's synthetic dollar, is backed by spot crypto plus short
perpetuals (mostly BTC and ETH), billions of dollars of them.
- **Minting USDe opens shorts**, which absorbs long demand and should push funding **down**.
- **Redeeming closes them** and should push funding **up**.

USDe's supply is public daily. If its flows move funding, they forecast what #12 earns. "Ethena
compresses funding" is often said; I know of no test of it as a timing signal. Idea 5 in
[IDEAS_NOVEL.md](IDEAS_NOVEL.md).

## Data — fixed

- **USDe supply**: DefiLlama's stablecoin history (`stablecoins.llama.fi/stablecoin/146`, Ethena
  USDe), daily `circulating.peggedUSD`. It is fetched once and committed with the run.
- **Binance funding**: BTCUSDT and ETHUSDT from #19's cache (`data/settle/funding/`), each rate
  scaled to 8 hours by the time since the previous settlement.
- **Hyperliquid funding**: BTC and ETH hourly (`fundingHistory`, public), as the second venue.
- **Weeks**: Monday 00:00 → Monday 00:00 UTC, from the week starting **2024-03-04** (USDe's first
  full weeks after its public launch) to the week ending **2026-10-26**.

## The measure — frozen

For week t:
- **flow(t)** = S(t) / S(t−1) − 1, with S the last daily supply in the week;
- **F(t)** = the mean funding over the week, BTC and ETH averaged, annualized: an 8-hour rate × 1095,
  an hourly rate × 8,760;
- **the regression**: ΔF(t+1) = a + **b · flow(t)** + c · F(t) + d · ΔF(t) + e, by least squares,
  with Newey-West standard errors (4 lags).
  - F(t) and ΔF(t) are the controls. USDe is minted when funding is high (its yield attracts), and
    funding mean-reverts by itself.
  - Only the part of the flow they do not explain is credited.

## Evaluation — fixed

**PASS requires all three:**

1. **Binance**: b **< 0** with t **≤ −2**. Redemptions (flow < 0) come before funding rises.
2. **Not one stretch**: b < 0 in each half of the weeks (split at the middle week).
3. **A second venue**: b < 0 on Hyperliquid's funding too.

**Information only:**
- b without the controls;
- BTC and ETH separately;
- the 2-week horizon (ΔF from t to t+2);
- the size: what a one-sd weekly flow moves funding by, in annualized percentage points.

## Power, said in advance

About 138 weekly observations with noisy funding. Only an effect strong enough to show through the
controls will reach t ≤ −2. A FAIL would not prove Ethena irrelevant to funding, only that its
flows are not a usable weekly forecast.

## Outcomes — fixed now

- **PASS**: after #12's verdict (2026-11-27), a document proposing a carry-timing filter: enter on
  redemption weeks, hold back on mint surges. #12 itself stays frozen until then.
- **Anything else: FAIL.** #12's timing stays as it is.

## Known confounds

- **Ethena is one of many shorts.** Its share of open interest has varied, and other basis traders
  respond to the same yields.
- **Supply at week's end** misses flows inside the week.
- **Overlapping incentives**: Ethena's own reserve and hedging choices (which venues, which coins)
  change over time.

## Transparency — what was seen before this commit

#12's, #19's and #33's results; DefiLlama's endpoint answering (1,054 daily rows from December 2023;
values not examined); #19's Binance funding cache. USDe's supply has not been set against funding.

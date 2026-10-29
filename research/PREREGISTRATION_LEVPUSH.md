# Pre-registration — 2x funds push small coins into the US close (#34)

Committed before any bar of this test's placebo coins is read at these times, and before the
forward window opens. The thirty-fifth test in this repo.

## Why

A fund promising 2x a coin's day must trade A·L(L−1)·r in the direction of the day's move at its
4 p.m. ET valuation. #28 found no push on BTC and ETH, which are too deep. As information, it found
one where the funds are large next to the coin:
- **XRP +8.1 bps** (t 4.0) in the last 15 minutes before 16:00 ET on trading days since 2025-04-08;
- **SOL +3.3 bps** (t 1.9);
- nothing on weekends.

A push caused by the funds must scale with their size. The issuer's list (Volatility Shares,
2026-10-29), Cboe's listings and 21Shares' release give:

| coin | US 2x funds | assets | first trading day |
|---|---|---|---|
| SOL | SOLT (Volatility Shares), SLON (ProShares), SOLX (T-REX) | SOLT alone $180M | 2025-03-20 |
| XRP | XXRP (Teucrium), XRPT (Volatility Shares), UXRP (ProShares), XRPK (T-REX) | XRPT alone $84M | 2025-04 |
| ADA | CRDX | $1.2M | 2026-04-01 |
| XLM | STLU | $2.3M | 2026-04-01 |
| LINK | CHNU | $3.0M | 2026-04-01 |
| AVAX | AVAZ | $1.0M | 2026-05-15 |
| DOGE | TXXD (21Shares) | not found | 2025-11-20 |

Funds of $1–3M rebalance a few hundred thousand dollars on a big day, which is nothing next to these
coins' volume. So the mechanism predicts **no push on ADA, XLM, LINK and AVAX**, and a push on SOL
and XRP that **continues on new data**.

## Two parts, both fixed now

**A. The placebo, historical.** ADA, XLM and LINK on 2026-04-01 → 2026-10-27, and AVAX on
2026-05-15 → 2026-10-27.
- #28's rule unchanged (`espero/levetf.py`): y = sign(r) × (P(16:00) / P(15:45) − 1) on NYSE
  trading days, with r the move from the previous session's close to 15:45.
- Binance USDⓈ-M 5-minute bars from #20's and #30's caches (`data/lows/`, `data/bids/`), nothing
  downloaded.
- Each date's mean over the placebo coins is one observation.

**B. The forward test.** SOL and XRP on trading days **2026-10-30 → 2027-03-31**, from the rows
#29's daily step builds out of #24's recorded bars (`postclose_days.csv`). Each date's mean over the
two coins is one observation.

## Evaluation

**PASS requires all three:**

1. **The placebo is flat** (part A): the placebo coins' mean y is **below 3 bps**. #28 measured
   +8.1 bps on XRP and +3.3 bps on SOL; a push that shows equally where the funds are tiny is not
   the funds'.
2. **The push continues** (part B, after 2027-03-31): SOL and XRP's mean y on trading days
   **> 0, t ≥ 2**.
3. **Only when the funds trade** (part B): that mean is above the same coins' closed-day mean.

Criterion 1 is read now; 2 and 3 after the window. A placebo that fails ends the test now as FAIL.

**Information only:**
- part A coin by coin, and its closed days;
- DOGE since 2025-11-20 (its fund's size is unknown);
- the after-close reversal (#29's measure) on the placebo coins;
- part B coin by coin.

## Power, said in advance

Part B has about 100 trading days. At #28's size for the two coins together (about 5.7 bps) and a
date's mean varying by about 30 bps, the expected t is near 1.9. Criterion 2 is a coin flip even if
the push is real. A FAIL there would not prove the funds push nothing; a PASS would be meaningful.

## Outcomes — fixed now

- **PASS**: a document for a paper rule (on SOL and XRP, buy or sell with the day's move at 15:45
  ET, out at 16:00) before anything trades.
- **Anything else: FAIL.**

## Known confounds

- **Fund sizes are a snapshot** (2026-10-29). SOL's and XRP's funds were smaller in 2025, and the
  placebo coins' may grow.
- **Other US-hours flows** (spot ETFs: SOL, XRP, LTC, DOGE, LINK and more have spot funds) push at
  the same clock time. Spot creations are not tied to the day's move the way leveraged rebalancing
  is, but they are not ruled out.
- **Binance perpetual prices.**

## Transparency — what was seen before this commit

#28's run, including its SOL and XRP rows, and #29's design. The issuer, exchange and news pages
listed above (fund sizes and dates, no prices). No bar of ADA, XLM, LINK, AVAX or DOGE at these
times.

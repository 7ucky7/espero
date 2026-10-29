# Pre-registration — what the accounts' 00:00 UTC fills cost (#33)

Committed before the measure is computed. An execution study for the running accounts, not a new
signal. The thirty-fourth test in this repo.

## Why

XS (weekly top-10) and #8 (multifactor) book their Monday fills at the **00:00 UTC price**. That
instant is a Binance funding settlement. #19 found prices swinging about 15.5 bps against whichever
side pays high funding around a settlement (t 3.5): holders who will not pay exit before it, and
collectors enter.

If that is true at the fill's own minute, then 00:00 is a biased fill:
- **Longs paying** (positive funding): the price is pushed down into the settlement and recovers
  after it. A buy at 00:00 is cheap; a sell at 00:00 is dear.
- **Shorts paying** (negative funding): the reverse.

#19 measured this on hourly bars. This asks the accounts' question, at 5 minutes on Mondays: how much
does the price move in the half hour after the 00:00 fill, and is it worth moving the fill?

## Data — fixed

- **Bars**: Binance USDⓈ-M 5-minute klines for the 42 coins of `xs.UNIVERSE`, already cached:
  - #20's months (`data/lows/`, 2020-01 → 2026-03);
  - #28's and #30's months and days (`data/levetf/`, `data/bids/`, 2026-04 → 2026-10-27).
  - Nothing is downloaded.
- **Funding**: #19's cache (`data/settle/funding/{SYMBOL}.json`, Binance's settlements 2020 →
  2026-10-28).
- **Events**: every **Monday 00:00 UTC** settlement, 2020-01-06 → 2026-10-26, for each coin with a
  settlement within a minute of 00:00 and bars at the needed times.

## The measure — frozen

- P(t) is the open of the 5-minute bar opening at t. The fill price is P(00:00).
- **The drift after the fill**: m(h) = P(00:00 + h) / P(00:00) − 1, for h = 15, **30** (primary)
  and 60 minutes.
- **Funding at that settlement**, scaled to 8 hours: rate × 8 ÷ the hours since the coin's previous
  settlement (4-hour coins settle twice as often).
- **Buckets**:
  - longs paying hard, rate ≥ +0.0005 (#19's 0.05%);
  - shorts paying hard, rate ≤ −0.0005;
  - normal, everything else.
- Each Monday's mean within a bucket is one observation.

## Evaluation — fixed

**PASS (the fill time matters enough to act on) requires all four:**

1. **Longs paying**: mean m(30) **> 0, t ≥ 3**. The price recovers after the 00:00 fill.
2. **Big enough to move a fill**: that mean is **≥ 5 bps**.
3. **Shorts paying**: mean m(30) **< 0**. The mirror holds.
4. **Not one era**: criterion 1's mean > 0 in both halves (2020-01 → 2023-05; 2023-06 → 2026-10).

**Information only:**
- m(15) and m(60);
- the normal bucket (most fills: is the 00:00 fill unbiased for them?);
- every day's 00:00 settlement, not just Mondays;
- the 08:00 and 16:00 settlements;
- each bucket's share of coin-Mondays;
- by year.

## Outcomes — fixed now

- **PASS**: a document for XS's fill rule before any change. Buy hard-paying-longs coins at 00:00
  and sell them later, or simply fill 30 minutes later. **#8 stays frozen** (FORWARD_MF.md); its
  record gets an ERRATA note with the size of the bias.
- **Anything else: FAIL.** The 00:00 fill stays, and the cost is recorded as measured.

## Known confounds

- **#19 measured the same settlements on hourly bars**, so the direction is not new information.
  This test is about size at the accounts' own fill minute.
- **The accounts' real trade directions are not simulated.** The buckets give the cost per
  direction; the accounts' mix of buys and sells decides what they actually pay.
- **Perpetual prices**: XS and #8 mark on Yahoo and Hyperliquid spot-like series; the perpetual
  leads them by seconds.
- **Survivorship**: today's coin list.

## Transparency — what was seen before this commit

#19's result and its hourly settlement study (2020–2026, all 42 coins); the 5-minute bars as used by
#20, #28 and #30 (none at Monday 00:00 for this question); XS's and #8's fill code.

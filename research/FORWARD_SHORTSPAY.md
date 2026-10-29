# Forward test — the price falls after settlements where shorts pay hard (#38)

Committed **before** any bar or settlement of the forward window exists. A paper test: nothing
trades. The thirty-ninth test in this repo.

## Why

#33 ([RESULTS_FILLCOST.md](RESULTS_FILLCOST.md)) measured the price in the 30 minutes after Binance
funding settlements, 2020–2026. It found the fill time unbiased for ordinary funding. As
information, it found one strong effect: when **shorts paid at least 0.05%** (8-hour equivalent),
the price **fell** after the settlement.

| settlement | price change in the next 30 minutes |
|---|---|
| Mondays 00:00 | −34.0 bps (t −2.6) |
| every day 00:00 | −18.6 bps (t −3.7) |
| every day 08:00 | −21.0 bps (t −4.4) |
| every day 16:00 | −4.2 bps (t −0.7) |

The mechanism is #19's swing against the paying side: shorts buy back before the settlement so as
not to pay, pushing the price up into it, and the push wears off after. It was seen on #33's data,
so this test runs on settlements that have not happened yet.

## Data — fixed

- **Funding**: Binance's public archive, monthly files (`espero/fundsplit.py::rates`, the reader #32
  uses, rates scaled to 8 hours), for the 42 coins of `xs.UNIVERSE`. It lags by up to a month, so
  the verdict waits for March 2027's file.
- **Bars**: Binance USDⓈ-M 5-minute bars as #24's job records them (`data/lows/forward/`).
- **Settlements**: **00:00, 08:00 and 16:00 UTC** each day, 2026-10-30 → 2027-03-31.

## The rule — #33's measure (`espero/fillcost.py`), unchanged

- m30 = P(t + 30 min) / P(t) − 1, with P the open of the 5-minute bar.
- **Shorts paying hard**: the 8-hour rate settled at t is **≤ −0.0005**.
- **Normal**: the rate is between −0.0005 and +0.0005.
- **The paper trade**: short at P(t), cover at P(t + 30 min). Its return is −m30.
- Each UTC day's mean is one observation.

## Evaluation — once, after 2027-03-31

**PASS requires all four:**

1. **The fall**: shorts-paying settlements' mean m30 **< 0, t ≤ −2**.
2. **Only when shorts pay**: that mean is below the normal settlements' mean (Welch on day means,
   difference < 0).
3. **Not one stretch**: mean m30 < 0 in each half (2026-10-30 → 12-31; 2027-01-01 → 03-31).
4. **It pays**: the paper short's mean return **above 18 bps** (two Hyperliquid taker round trips),
   **t > 2**.

**Outcomes, fixed now:**
- **PASS**: a document for the paper short book, plus an execution note for XS (buy such coins 30
  minutes after a settlement). The account is long-only, so nothing shorts.
- **1–3 hold, 4 fails**: real, not tradable; the execution note only.
- **Anything else: FAIL.**

**Information only:**
- each settlement hour;
- the 15- and 60-minute horizons;
- longs paying hard (#33's other bucket);
- by coin.

## Power, said in advance

#33 had about 1.7 shorts-paying events a day at each of 00:00 and 08:00. Over 153 days that is a few
hundred events. At #33's size (about −20 bps) the expected t is near −3. At half the size, about −1.5.

## Known confounds

- **Rare events, often in sell-offs**: negative funding comes after falls, and some of the drift may
  be the sell-off continuing. Criterion 2 compares within the same days' market only partly.
- **Winter months; perpetual prices; monthly funding files.**

## Transparency — what was seen before this commit

#33's run (2020–2026, the table above) and #19's. No settlement or bar of the forward window.

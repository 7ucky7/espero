# Result — #12's carry rule on Kraken Futures (#14)

**Verdict: FAIL.** Four of the five criteria missed. On Kraken, in the months #12 never saw,
funding rarely paid enough to open a position, and the six positions it did open earned their
funding back in basis losses. The book finished flat.

Spec: [PREREGISTRATION_CARRY3.md](PREREGISTRATION_CARRY3.md) (`5a58224`, amended before the
fetch in `a01a68a`). Code: `espero/kraken_futures.py`, `research/carry_kraken.py` (`8c4fa9e`,
committed before the fetch), the same `carry.simulate` #12 ran on. One run; raw output in
[carry_kraken_run.txt](carry_kraken_run.txt).

## Data

Top 20 Kraken Futures `PF_` perpetuals by open interest on 2026-10-28; XAUT and XMR have no
Coinbase spot pair, leaving 18: BTC ETH HYPE XRP SOL ZEC NEAR SUI LINK LTC ADA DOGE BNB DOT UNI
CRV AAVE XLM. Kraken serves about a year of history: 9,064 funding rates per coin, from
2025-10-15. **The rates are hourly**, so the funding-unit amendment did not change any number;
it would only have mattered for 4-hour periods. Primary window: 2025-10-15 → 2026-04-01, 4,043
hours, 17 coins (HYPE's Coinbase spot is too short).

## Criteria, primary window, #12's rule and maker costs

| criterion | required | actual | met |
|---|---|---|---|
| net annualised return on equity | > 8% | −0.0% | **no** |
| max drawdown | < 5% | 2.5% | yes |
| Sharpe, hourly, annualised | > 1.5 | 0.02 (daily −0.01) | **no** |
| funding paid / received | < 25% | 36% | **no** |
| net annualised, Kraken spot fees | > 4% | −1.7% | **no** |

At taker costs the same window loses 1.0% a year (−3.6% on Kraken spot fees).

## What the table says

1. **The entry bar was rarely reached.** Six trades in 4,043 hours, 909 hours in a position: the
   book was flat 78% of the time. The spec said this in advance: Kraken has no ~11% idle funding
   floor like Hyperliquid, so the same 15% bar is a stricter test there.
2. **When it did enter, the basis took the funding back.** Funding +0.53%, basis −0.47%, fees
   0.06% of equity. Every exit was `funding_low`: each position opened on a spike that faded
   within a week, and the perp-spot gap closed against the hedge as it faded.
3. **The months #12 ran on, as information:** +5.1% a year on Kraken (Sharpe 0.99 hourly, 3.51
   daily), against #12's +10.9% on Hyperliquid in the same months. 40% of the funding received was
   paid back in negative hours (#12's criterion is 25%). Even in its best months, the edge on Kraken
   is half of what it was on Hyperliquid, and it fails on Kraken spot fees.

## What this changes

#12's edge is now recorded as **seen on Hyperliquid only**. That is not a verdict on #12, whose
forward test on Hyperliquid runs to 2026-11-27 and decides it. It does settle the practical
question that #14 was for: on a venue this account could plausibly use, the rule does not clear
the bar, in the months it was not designed on or in the months it was.

## Transparency

One run, no parameter changed. Before the spec was written, only HTTP status codes were read. The
spec's funding-unit definition was corrected before the fetch, from Kraken's contract
specification; on this data it made no difference. Survivorship (today's top 20 by open interest)
biases the test *for* the strategy. Whether Kraken's perpetuals can be traded from a US account
was never checked and did not need to be.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 12 | Carry with swap gap + maker execution (Hyperliquid) | pass, provisional — forward test to 2026-11-27 |
| 13 | 打板 on 1h bars, one entry per bar, beats BTC | fail — negative before fees |
| **14** | **#12's carry rule on Kraken Futures** | **fail** — funding rarely clears the bar; basis takes the rest |

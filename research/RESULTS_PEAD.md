# Result — post-earnings announcement drift (PEAD)

**Verdict: FAIL.** Sharpe below zero on the holdout, CAGR negative, while SPY made +13.4% a year.

Spec: [PREREGISTRATION_PEAD.md](PREREGISTRATION_PEAD.md) (committed `f9b8b5f`, before any filing was
fetched). Code: [pead.py](pead.py).

## Headline

| period | trades | CAGR | Sharpe | max DD | total | SPY CAGR | SPY Sharpe |
|---|---|---|---|---|---|---|---|
| design 2010–2020 | 220 | +6.41% | 0.47 | −38.95% | +97.94% | +11.47% | 0.71 |
| **holdout 2021–2026** | **112** | **−1.64%** | **−0.05** | **−28.25%** | **−9.12%** | +13.43% | 0.84 |

| pass criterion (holdout) | required | actual | met |
|---|---|---|---|
| Sharpe > SPY | > 0.84 | −0.05 | **no** |
| CAGR > 0 | > 0 | −1.64% | **no** |
| ≥ 30 trades | ≥ 30 | 112 | yes |

## What was built

- **5,351** 8-K item 2.02 filings parsed from SEC EDGAR across 60 large caps, 1994–2026, using each
  filing's `acceptanceDateTime` — the moment it became public, not a crawl time.
- Reaction day derived from that timestamp: before 09:30 ET → same session, at/after 16:00 → next
  session. Signal is the market's own one-day reaction. Entry next open, 40-session hold.
- The filter kept ~20% of events; the five largest reactions per day competed for five slots.

## Why it failed

**1. It lost in the design period too.** +6.41% vs SPY's +11.47%. This is not a regime story like
funding extremes — the rule never worked, in any window.

**2. Large caps are the wrong pond.** PEAD is documented as strongest in small caps with low analyst
coverage, where information diffuses slowly. The 60 largest US companies are the most scrutinised
equities on earth; by the time the 8-K lands, the surprise is priced and the drift is arbitraged.

**3. The reaction proxy is noisy.** A +3% move on earnings day can be guidance, a sector rally, a
buyback announcement, or a headline about the CEO. Consensus-EPS surprise would be a cleaner signal;
this design deliberately avoided that vendor.

**4. Concentration.** Five positions at 20% produced a −39% drawdown in the design period. Even a
working signal would be hard to hold.

**5. Survivorship bias helped and it still lost.** The universe is 2026 survivors, which flatters
absolute returns. It wasn't enough.

## Fidelity note

The first execution took the first five signals of the day by ticker order; the pre-registration said
**the five largest reactions**. Fixed to match the document and re-run: −0.72% → −1.64% CAGR. The fix
is disclosed because it changed the number, even though it was a fidelity correction rather than a
tuning change.

## Pilot — small caps (exploratory, not pre-registered)

60 random current S&P 600 names, same rule, 50 bps costs (small-cap spreads, not 10):

| period | trades | CAGR | Sharpe | max DD |
|---|---|---|---|---|
| design 2010–2020 | 211 | −3.66% | −0.07 | −58.93% |
| holdout 2021–2026 | 112 | +3.61% | 0.28 | −31.07% |

This is **not evidence about PEAD** and should not be read as a second test:

- **Survivorship bias runs the wrong way.** The universe is 2026 index members, so every small cap
  that failed is excluded — the bias inflates returns, and the rule still lost in the design period.
- It is a 60-name sample of a 600-name universe.
- Costs are assumed at 50 bps; real small-cap spreads can be worse.

What it does suggest is that the weak link is the **signal**, not the pond. A one-day price reaction
is not an earnings surprise: it fires on guidance, sector moves and buybacks as often as on a beat.
A real small-cap PEAD test needs consensus-EPS surprise (paid) and a delisting-inclusive universe
(paid). That is a different project with a different budget, not a retune.

## What this retires

- **Large-cap PEAD as a retail strategy.** Not without a cleaner surprise measure (consensus EPS) and
  a small-cap universe with delisting data.
- **"News + price reaction" as a short cut.** The timestamp plumbing worked exactly as designed; the
  effect simply isn't there in this pond.

## What it does not retire

PEAD itself, in the population where it was found — small caps, thin coverage, slow diffusion. Testing
that properly needs a survivorship-free small-cap universe and a paid consensus feed. That is a
different project with a different budget, and it would need its own pre-registration.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 1 | Funding extremes | fail — 7.5y, t=0.91 |
| 2 | Cross-sectional crypto momentum | fail — −29.75%/yr holdout |
| 3 | Polymarket liquidity provision | fail — rewards < inventory |
| 4 | Cross-asset TSMOM | pass — thin, drawdown control |
| **5** | **PEAD (large-cap)** | **fail — Sharpe −0.05 on holdout** |

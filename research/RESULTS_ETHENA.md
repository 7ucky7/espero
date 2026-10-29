# Result — Ethena's USDe flows forecast funding (#36)

**Verdict: FAIL** on all three criteria. Once funding's own level and last change are controlled,
this week's USDe supply flow says nothing about next week's funding:
- Binance: b **+0.025** (t 0.75), the wrong sign;
- both halves: positive;
- Hyperliquid: positive (t 0.90).

The naive regression, without controls, shows the predicted sign (b −0.144, t −2.22). That is the
trap the controls were registered for: **USDe is minted when funding is high** (its yield
attracts), and **high funding falls back on its own**. Ethena follows funding; it does not lead it.

Spec: [PREREGISTRATION_ETHENA.md](PREREGISTRATION_ETHENA.md) (`95ca073`); code `50da968`. One run,
output in [ethena_run.txt](ethena_run.txt). USDe's history as fetched is in
[ethena_usde.json.gz](ethena_usde.json.gz). Hyperliquid's funding endpoint rate-limited a few
requests (HTTP 429, while the collector shares the address); each was retried and succeeded.

## Data

138 weeks, 2024-03-04 → 2026-10-19. USDe's weekly supply flow has a standard deviation of 8.2%.
Binance BTC/ETH funding averaged 6.3% a year.

## Criteria

| # | criterion | required | actual | met |
|---|---|---|---|---|
| 1 | Binance | b < 0, t ≤ −2 | b +0.025, t 0.75 | **no** |
| 2 | not one stretch | b < 0 in each half | +0.038, +0.028 | **no** |
| 3 | a second venue | b < 0 on Hyperliquid | +0.064, t 0.90 | **no** |

## What the tables say

1. **The raw correlation is real and misleading.** Without controls: b −0.144, t −2.22. Weeks of
   heavy minting come when funding is high, and funding then falls, so a forecaster that ignores
   funding's own reversion would think minting caused the fall.
2. **The size, with controls**: a one-sd weekly flow moves next week's funding by +0.2 percentage
   points a year. That is nothing against a 6% average.
3. BTC alone +0.076 (t 1.98, wrong sign), ETH alone −0.007; 2-week horizon +0.022.

## What this changes

#12's timing stays as it is. "Ethena compresses funding" is on record here as a story without a
forecast in it. For #12, what matters is funding's own level, which its rule already uses.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 12 | Carry with swap gap + maker execution (Hyperliquid) | pass, provisional; forward to 2026-11-27 |
| **36** | **Weekly USDe supply flows forecast next week's funding** | **fail**: b +0.025 with controls; the raw −0.144 is funding's own reversion |

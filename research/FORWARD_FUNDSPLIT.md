# Forward test — forced down-breaks bounce more when longs were crowded (#32)

Committed **before** #27's window opens: no break of 2026-10-30 → 2027-03-31 exists yet, and
none will be read until the verdict. A paper test: nothing trades. The thirty-third test in this
repo.

## Why

#26 passed: down-breaks made of long liquidations bounce, +23.5 bps an hour (t 7.1). #12 and #19
say funding measures how crowded and how costly a side is. A long that is liquidated while paying
above-normal funding was crowded twice: levered, and paying rent to stay so. More of the selling
behind its break should be forced, so its overshoot, and the snap-back, should be larger. Idea 7 in
[IDEAS_NOVEL.md](IDEAS_NOVEL.md).

## Data — fixed

- **Breaks**: #27's ledger exactly (`espero/liqbreak.py`). That means aggr's 5-minute liquidations
  on its 14 coins, Binance 5-minute bars, #26's rule and its within-day forced/organic groups, on
  UTC days 2026-10-30 → 2027-03-31. Only **forced down-breaks** count here.
- **Funding**: Binance USDⓈ-M funding history (`fapi/v1/fundingRate`, public), fetched for each
  coin's perpetual (`liq.symbol`) and cached in `data/funding/`.

## The rule — frozen

- **Funding before a break**: the rate of the last Binance settlement **at or before** the break
  bar's close. It is known when the break happens.
- **Crowded**: that rate is **above 0.0001** (0.01% per 8 hours), Binance's default rate. Above it,
  longs are paying a premium to stay long. At or below it, they are not.
- **The outcome**: the long return of buying the forced down-break, −y60 in #27's ledger (from the
  next bar's open, 1 hour), and −y240 at 4 hours.
- A break whose funding is missing is dropped.

## Evaluation — once, after 2027-03-31

Within each group, each UTC day's mean is one observation. Differences use Welch's t on the two
groups' day means.

**PASS requires all four:**

1. **The crowd matters**: D = crowded minus not crowded, long 1-hour return: **D > 0, t ≥ 2**.
2. **The crowded breaks pay**: their mean long 1-hour return **above 18 bps** (two Hyperliquid
   taker round trips), **t > 2**.
3. **Not one stretch**: D > 0 in each half (2026-10-30 → 12-31; 2027-01-01 → 03-31).
4. **It lasts**: D > 0 at 4 hours too.

**Information only:**
- the crowded share of forced down-breaks;
- D on organic down-breaks (does funding sort them too?);
- the mirror: forced up-breaks after negative funding (shorts crowded), as a paper short;
- funding in terciles instead of the baseline split;
- Hyperliquid's hourly funding in place of Binance's.

## Power, said in advance

#26 counted 19,737 down-breaks on 26 coins over 429 days. This window has 14 coins and 153 days, so
several hundred forced down-breaks are likely, of which perhaps a third are crowded. A t ≥ 2 on D
needs the gap to be large, about 20 bps or more. A FAIL would not prove funding irrelevant; a PASS
would be strong.

## Outcomes — fixed now

- **PASS**: if #27 passes too, its sizing document weights crowded breaks. #32 trades nothing alone.
- **Anything else: FAIL.** No stopping early on the running numbers.

## Known confounds

- **Funding and price trend go together.** High funding follows rallies, so crowded breaks are
  breaks after a run-up, and some of the difference may be "after a rally", not "crowded". The
  information rows (organic breaks, terciles) help separate the two.
- **Binance's funding, aggr's liquidations, Binance's prices**: three sources, one clock.
- **Five winter months, 14 coins.**

## Amendment, 2026-10-29, before the window opens

Binance's live API (`fapi.binance.com`) answers this machine with HTTP 451: it refuses US
addresses. The same settlements are published in Binance's public archive, which this repo already
reads for prices: monthly files at
`data.binance.vision/data/futures/um/monthly/fundingRate/{SYMBOL}/`, with columns
`calc_time, funding_interval_hours, last_funding_rate`. **The funding comes from there.**

- Some perpetuals settle every 4 hours, not 8. The rate compared with 0.0001 is **scaled to
  8 hours** (rate × 8 ÷ interval). For an 8-hour coin that is the rate itself.
- The archive is monthly, so the running numbers lag by up to a month. The verdict waits for March
  2027's file.

Nothing else changes. No break and no rate from the window had been read.

Seen while testing the parser, outside the window: in September 2026 neither BTCUSDT nor 1000SHIBUSDT
settled above 0.01% even once (90 settlements each). In calm months the crowded group may be small,
and criterion 1 may then lack the breaks to reach t ≥ 2.

## Transparency — what was seen before this commit

#26's result and events (2023–24), #19's settlement study, #27's design, and today's funding rates
on Hyperliquid (the collector's first snapshot). No break and no funding rate from the window: it
opens at 00:00 UTC tonight.

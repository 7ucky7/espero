# Pre-registration — multi-asset trend, sized by volatility (#15)

Committed **before** any series in this universe was fetched for this test. Hypothesis #15, the
sixteenth test in this repo (#9 and #9b both count). The transparency section lists everything that
was seen anyway; the multiple-testing note is at the bottom.

## Why this hypothesis

The request was for signals that *work* for getting into stocks, commodities, crypto and altcoins.
Nothing is known to work in advance, and this repo shows why: every fast entry signal it tried lost
before fees or tied with them (#9b lead-lag was the bid-ask bounce, #10 five-minute breakouts broke
even gross, #13 hourly breakouts lost gross). The three passes were slow, and the decompositions say
what did the work: **holding less when volatility rises** (#4, #8).

The entry signal with the longest out-of-sample record across these asset classes is time-series
trend. Moskowitz, Ooi & Pedersen (JFE 2012) found it in 58 futures markets; Hurst, Ooi & Pedersen
(*A Century of Evidence on Trend-Following Investing*, 2017) found the equal-weighted 1-, 3- and
12-month rule positive in every decade since 1880; Liu & Tsyvinski (RFS 2021) found time-series
momentum in crypto. This hypothesis takes that published rule, long/flat only (a small retail
account does not short), sizes every position to the same volatility, and asks the question #4 and
#8 left open: **does the trend timing add anything beyond the volatility sizing?** A book that only
rediscovers vol targeting fails criterion 1 by design.

## Universe — fixed

Four classes, chosen with the user before this document (index ETFs for stocks, bonds included,
liquid altcoins included):

| class | members (Yahoo symbols) |
|---|---|
| equity | SPY, QQQ, IWM, EFA, EEM |
| bonds | TLT, IEF |
| commodities | GLD, SLV, USO, UNG, DBA, CPER |
| crypto | BTC-USD, ETH-USD, SOL-USD, and **ALTS** |

**ALTS** is one member of the crypto class. It holds the 39 coins of `espero/xs.py::UNIVERSE` other
than BTC, ETH and SOL, priced `{coin}-USD` on Yahoo, split equally among the eligible ones.

**Eligibility**, on each decision date, using only that date's past:

- every asset: a complete close on or before the last close minus 364 days (all three lookbacks
  exist), and a fresh bar (see *Calendar*)
- alts, in addition, #8's rule as `panel.eligible` computes it: at least **365 closes** so far, and
  the mean of close × volume over the **30 calendar days** ending at the last close at least
  **$1,000,000**, with all 30 days present
- ALTS is an eligible crypto member when at least one alt is eligible

**Survivorship** is disclosed, not fixed: the coin list is October 2026's, so the alts sleeve is an
upper bound. The ETFs all trade today and have for the whole window.

## The signal — frozen

On adjusted closes (dividends and splits, Yahoo `adjclose`), for each eligible asset with last
complete close P_t:

- for h in **28, 91, 364 calendar days**: P_ref = the last close on or before t − h
- **f = the share of the three horizons with P_t > P_ref**, so f ∈ {0, ⅓, ⅔, 1}

Calendar days, not rows, so a 5-day ETF and a 7-day coin measure the same span; multiples of 7 keep
ETF references on the same weekday. This is `tsmom.signals`' convention extended to three horizons.

## The portfolio — frozen

- **Budgets**: each class gets **¼**, split equally among its eligible members. A class with no
  eligible member holds that ¼ in cash. An eligible member with f = 0 keeps its share in cash; it
  is not handed to the others.
- **Volatility**: σ = std of the asset's daily log returns (consecutive complete closes) whose end
  date is in the last **60 calendar days**, × √(number of its closes in the last 364 days). Fewer
  than 20 returns in the window: no estimate, weight 0.
- **Weight**: w = f × budget × min(**0.20** / σ, **2.0**). If the weights sum above 1, all are
  scaled down to sum to 1; the rest is cash earning **0%**. 0.20 and 2.0 are #8's frozen constants.
- **No-trade band**: an asset is traded only if |target − current| > **1% of equity**, or it enters
  (current 0, target > 0) or exits (current > 0, target 0).
- **Accounting**: positions are dollar values marked by adjusted-price ratios, so dividends accrue
  and splits cannot break the book.

## Calendar and fills — frozen

- **Cutoff**: a run on date D uses only bars dated D − 1 or earlier (crypto bars close at 00:00 UTC
  of the next day; ETF sessions close at 16:00 New York, both before 00:00 UTC of D).
- **Decision**: weekly, at the cutoff of every **Monday** (crypto through Sunday, ETFs through their
  last session). Targets in dollars = w × equity marked at the cutoff.
- **Fresh bar**: crypto needs Sunday's bar; an ETF needs a session in the 5 days before the cutoff.
  An asset without one is not traded that week (a held one keeps its position and is marked at its
  last price).
- **Fills**, after the 07:30 New York run that sends the decision:
  - ETFs at the **open of the first session dated D or later** (normally Monday 09:30 New York;
    Tuesday after a Monday holiday)
  - crypto at the **close of Monday's bar** (00:00 UTC Tuesday)
  - an order computed at decision marks executes as the same number of shares at the fill price.
    Fills are processed in time order; if a moment's buys plus their costs exceed the cash
    available after that moment's sells, the buys are scaled down pro rata.
- **Costs**: **5 bps** a side for ETFs, **10 bps** for crypto, on traded value.
- The live account fills a run late (after an ETF open, or a missed Monday) at the next bar and notes
  it `late`; the simulator assumes on-time runs. Decisions always use the Monday cutoff.

## Data — frozen

`data.yahoo_daily(symbol, "10y", adjusted=True)` for the 55 symbols above plus **BIL** (information
only), fetched once and committed to `data/trend/` before the results are read, so the run can be
reproduced offline. Gaps stay gaps; nothing is forward-filled.

## Evaluation — fixed in advance

**Window**: decisions at every Monday cutoff from **2018-01-01** to **2026-10-26**, equity marked at
every daily cutoff in that range, starting all-cash. 2018 onward is after the rule was published, so
it is out-of-sample for the *rule* (see the transparency section for the data).

**Books**, all through the same simulator:

- **trend**: the rule above
- **volonly**: the same with f = 1 for every eligible asset (vol-sized, always invested)
- **static**: f = 1 and no vol scaling (w = budget)
- **60/40**: SPY 0.6 / TLT 0.4, rebalanced weekly the same way, ETF costs

**Metrics**: weekly returns between Monday cutoffs; Sharpe = mean / std × √52 (rf = 0); CAGR; max
drawdown on the daily marks; turnover; trades.

**PASS requires all four:**

1. **Trend adds return beyond vol sizing.** With k = min(1, σ_trend / σ_volonly) on weekly returns,
   the excess e = r_trend − k · r_volonly has mean > 0 and a Newey-West t ≥ **1.28** (13 lags,
   `factor_eval.newey_west_t`).
2. **Trend protects beyond vol sizing.** The trend book's max drawdown is shallower than that of
   k · volonly + (1 − k) · cash.
3. **It beats the default portfolio.** Sharpe above 60/40's.
4. **It survives costs.** CAGR > 0 with every cost doubled.

**Information only** (cannot change the verdict): each horizon alone and the 364-day sign alone
(≈ #4's rule); no crypto; no alts; alts as a fifth class (budgets ⅕); P&L by class; 2018–2021 vs
2022–2026; costs ×3; idle cash earning BIL's return; no band; static; BTC and SPY buy-and-hold.

## Outcomes — fixed now

- **PASS**: a forward paper account and weekly alerts, with its own forward-test document committed
  before the account exists. A pass is a reason to watch it trade forward, not a reason for money.
- **FAIL** (anything else): the board ships as an unsized scanner with no alerts. If only criteria 1
  and 2 fail, the result is reported as "construction, not signal": the sizing works, the timing
  does not. A failure is not re-tuned on this data; the next idea gets a new document.

## Known confounds

- **Contamination**: #4 tested 12-month TSMOM on SPY, TLT, GLD, USO, BTC and ETH over 2021–2026,
  and the person writing this has read that result and #8's. The holdout is weakened, not clean.
- **Survivorship**: the alts are today's coins. Upper bound.
- **Short crypto history**: Yahoo's ETH and most alt histories start in November 2017, so the crypto
  class is BTC alone until about November 2018 and ALTS is empty until then.
- **Decaying ETFs**: USO and UNG lose to contango over time, which flatters any rule that holds them
  less than buy-and-hold does.
- **Yahoo**: unofficial endpoint; adjusted closes are restated as dividends arrive (the committed
  snapshot fixes the input); coin tickers can collide (a different token under the same symbol), and
  the $1M filter is #8's, computed the same way, whether or not it binds; whether it binds is
  reported.
- **Costs**: 5 and 10 bps assume a commission-free broker for ETFs and a low-fee crypto venue.
  Coinbase retail (60–120 bps) would be a different result.
- **Long/flat only**: no shorting, so the published long/short rule's 2022 and 2008 short gains are
  not available; flat earns 0%.

## Transparency — what was seen before this commit

- The six cached two-year Yahoo series the #4 account writes (SPY, TLT, GLD, USO, BTC-USD, ETH-USD
  in `data/cache/`), whose first and last rows were read while planning the calendar rules.
- Ten-year multiples, price-only vs dividend-adjusted, checked to decide on adjusted closes:
  TLT ×0.62 vs ×0.83, SPY ×3.62 vs ×4.24. These are buy-and-hold totals, not trend results.
- One futures check for a carry signal that was then dropped: crude, gold and corn contract prices
  for December 2026 to March 2027, and that expired contracts are not served.
- The published results of #4 and #8, and ordinary knowledge of the period (2018 and 2022 crypto
  bears, the 2020 crash, the 2022 stock and bond bear). The rule's parameters come from the papers
  above and #8's frozen constants, not from any of this.

## The multiple-testing note

This is the **sixteenth** test. At a 5% false-positive rate, sixteen independent tries produce at
least one false pass 56% of the time. Criterion 1's hurdle is one-sided at 10%, which on 8.8 years of
weekly data needs an information ratio of about 0.43 against the vol-matched book; together with the
other three it is a real bar, but one pass among sixteen tests is still weak evidence. That is why a
pass leads to a forward paper test and nothing else.

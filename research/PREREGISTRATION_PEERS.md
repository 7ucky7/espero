# Pre-registration — altcoins led by their peers, and ETH-ecosystem coins led by ETH (#16, #17)

Committed **before** any candle in the test window is fetched. Two hypotheses, judged separately,
the seventeenth and eighteenth tests in this repo. The scan (`espero scan`) measures every coin
against BTC only; the question asked was why, and whether a coin's own peer group or its home chain
would be a better leader. This document is how that question gets answered without fooling anyone.

## Why these hypotheses, and what #9 and #9b already settled

#9 and #9b ([RESULTS_LEADLAG2.md](RESULTS_LEADLAG2.md)) taught two things that shape everything
below:

1. **An unscaled gap is reversal in disguise.** Within one hour a leader's return is one number for
   every coin, so `r_leader − r_i` ranks coins exactly as `−r_i` does. That stays true when the
   leader is an alt basket (with or without coin *i* left out: the left-out mean is
   `(S − r_i)/(n − 1)`, which still ranks as `−r_i`) and when it is ETH. Neither idea can be
   tested as a plain gap.
2. **One-hour reversal is the bid-ask bounce.** t-statistics of 14 and a 4 bps payoff. Any signal
   that leans on a coin's own last-hour return inherits that bounce.

So the test isolates the part of the idea that is about the **leader**, and asks whether it adds
anything once the bounce is controlled for.

**Mechanism, as claimed.** Information reaches the most-traded coins of a group first; members
with thinner books reprice later. If true, a coin with a high trailing beta to its group should do
better in the hours after the group rose than one with a low beta, beyond what its own last hour
says. For ETH-ecosystem tokens the same story is told with ETH as the leader: their collateral,
gas and DeFi flows are denominated in ETH.

**Prior: low.** #9b's beta term subtracted information when the leader was BTC. Nothing in this
repo has found a predictive edge at any horizon from one hour to one month.

## Data — fixed

- **Source**: Coinbase Exchange public hourly candles (granularity 3600), the endpoint #9 and #9b
  used.
- **Window**: **2024-10-27 00:00 UTC → 2025-10-27 00:00 UTC**, the year *before* #9b's. No hourly
  bar from it has been examined for any test in this repo. Fetched once into `data/panel_peers/`
  (committed) and not refreshed during the analysis.
- **Universe**: the coins of `espero/xs.py::UNIVERSE` that Coinbase lists as `{COIN}-USD`. Coins it
  does not list, or that have no bars in the window, are recorded, never substituted.
- **Eligibility on each hour**, from that hour's past only, as in #9: at least **720 hourly closes**
  and trailing **168-hour mean dollar volume ≥ $50,000 per hour**.
- **BTC** is in neither cross-section nor basket.

Survivorship is disclosed: the coin list is October 2026's. One year, no full cycle.

## The two hypotheses — frozen

Common pieces, for coin *i* at the close of hour *t*:

- `r_x(t)` = one-hour simple return of *x* from the close of *t − 1* to the close of *t*
- `beta_i,L(t)` = cov(r_i, r_L) / var(r_L) over the trailing **168** one-hour returns ending at
  *t*, causal; #9b's window, reused, not searched

### #16 — the peer basket leads (all eligible altcoins)

- **Leader of coin i**: `B_−i(t)`, the equal-weighted mean of `r_j(t)` over every coin *j* eligible
  at *t*, excluding BTC and *i* itself. Each coin's beta is to its own leave-one-out series.
- **Cross-section**: every eligible coin other than BTC (ETH included).
- **Signal**: `push_peers(i, t) = beta_i,B(t) × B_−i(t)`
- Quantiles for criterion 3: **5**.

### #17 — ETH leads its ecosystem

- **Group, fixed by where the token lives, before any data**: the coins of `UNIVERSE` that are
  Ethereum ERC-20 tokens or Ethereum L2 native tokens: **ARB, OP, LINK, AAVE, MKR, CRV, SNX, SUSHI,
  YFI, SHIB, WLD** (11). ETH is the leader and is not in the cross-section.
- **Signal**: `push_eth(i, t) = beta_i,ETH(t) × r_ETH(t)`
- Quantiles for criterion 3: **3** (the group is small; the evaluator needs two coins per bucket).
  Hours with fewer than 6 eligible coins are not evaluated.

**Sign: positive** for both. After the leader rose, high-beta members are expected to beat
low-beta ones.

**Why the bounce cannot manufacture a pass.** `push` is positively correlated with the coin's own
last-hour return (a high-beta coin moved with the leader). The bounce makes the own return predict
the next hours *negatively*. So the bounce biases `push`'s IC **down**: a positive result is not
the bounce.

## The control — pre-registered

`rev_1` (minus the coin's own last-hour return, already in the zoo), on the same cross-section.
`push` must add information **beyond** it, tested by Fama-MacBeth: in each evaluated hour, the
cross-sectional OLS of the forward return's rank on the ranks of `push` and `rev_1` (each rank
centred and scaled to unit variance), and the mean of the hourly coefficients on `push`.

## Evaluation — fixed

- **Primary horizon: 3 hours**, the forward return from the close of *t* to the close of *t + 3*.
  1, 6 and 12 hours are reported for information.
- **Out of sample**: the union of the test blocks of the purged walk-forward, **4 blocks**,
  **24-hour embargo**, **720 hours minimum training** (passed explicitly this time; see ERRATA,
  2026-10-28, for #9b's slip).
- **Costs**: Hyperliquid, the venue the scan and fast screen now quote: taker **4.5 bps a side**
  (9 bps round trip), maker 1.5 bps (3 bps). Reported against the spread; the hurdle is fixed below.

**Each hypothesis PASSES only with all four:**

1. out-of-sample rank IC **t > 3** for `push`
2. out-of-sample Fama-MacBeth **t > 3** for the `push` coefficient with `rev_1` in the regression
3. mean top-minus-bottom quantile spread **> 10 bps** per 3 hours (as in #9; about one taker round
   trip on Hyperliquid, so a pass would still need maker execution to be worth anything)
4. hit rate (share of hours with positive IC) **> 0.52**

Plain t, as in #9 and #9b; the Newey-West t (4 lags, `2 × (h − 1)` as `evaluate` uses) is printed beside every one.

**Information only, cannot change a verdict:**

- the #9b-style gap with each leader, `beta_i,L × r_L − r_i`, and the unscaled gap (whose
  statistics must equal `rev_1`'s exactly: the check that the evaluator does what point 1 says)
- `push` over three hours (`r_L(t − 3, t)`, same beta)
- `push` with BTC as the leader, on each cross-section
- IC decay at 1, 2, 3, 6, 12, 24 hours
- the same table on Hyperliquid perp hourly bars (the ~208 days the API serves, ending at the fetch).
  That window **overlaps #9b's**, and these perps are the market the scan quotes; it is shown so a
  pass on Coinbase spot can be checked against the venue, not as a second test

## Outcomes — fixed now

- **PASS (either)**: the scan gets the passing leader as an option, labelled with this result, and
  a forward-test document (`FORWARD_PEERS.md`) is written before any paper book trades it.
- **FAIL**: nothing ships; the scan keeps BTC as its only reference and says why. A fail is not
  re-tuned on this data: another window, beta length, horizon or group is a new document.

## Known confounds

- **Survivorship**: today's list; coins that died in 2024–25 are absent. Upward bias.
- **The ETH group is a judgement.** LINK, SHIB and WLD trade on several chains; they are in because
  their main token contract is on Ethereum. The list is frozen above, before data.
- **MKR became SKY in 2024–25**; if Coinbase's `MKR-USD` ends inside the window, the coin drops out
  of eligibility when its bars stop, as the rules say. Nothing is spliced.
- **Coinbase spot is not where the scan trades.** That is why the Hyperliquid table is printed;
  the verdict is on the cleaner, unseen window.

## Transparency — what was seen before this commit

- #9b's whole year of Coinbase hourly bars (2025-10-27 → 2026-10-27) and its results.
- One hour of Hyperliquid bars in today's `espero scan` (alts up 40–110 bps, BTC −3 bps).
- No bar of the 2024-10-27 → 2025-10-27 window, for any coin.
- The design choices above (leave-one-out basket, beta window, the ETH list, quantile counts, the
  Fama-MacBeth control) were made from #9b's post-mortem and reasoning, not from a look at data.

## The multiple-testing note

Seventeenth and eighteenth tests; three thin passes so far, all risk construction. This is the
third and fourth document on lead-lag. Two hypotheses are run, so the chance of one passing by luck
roughly doubles; the t > 3 hurdles (about 1 in 700 for one null comparison) are kept, not relaxed,
and the expected best t among the comparisons printed is shown next to the observed ones.

# Forward test — hypothesis #8, six months of paper

Committed **before** the account exists and before it has seen a single price. This document is
the forward half of `PREREGISTRATION_MF.md`, which says a pass "means: paper trade it forward for six
months through a new weekly account alongside the existing XS account, same cost, and compare". It
did not say what "compare" passes on. This document fixes that now, with no forward data seen.

## The rule — unchanged

Exactly the rule in `PREREGISTRATION_MF.md` as run in `research/multifactor.py`: the 42-coin
universe, dated eligibility (365 closes, 30-day mean dollar volume ≥ $1M), the equal-weight rank
average of `mom_30`, `rev_3`, `lowvol_30`, top 10 with a top-20 turnover buffer, each position scaled
to 20% / its 30-day vol (scale ≤ 2×, gross ≤ 100%, rest in cash), 10 bps a side, decided at Sunday's
close, filled at Monday's open. No parameter changes during the six months. A change is a new
hypothesis with a new document.

The account is `espero mf` (`espero/mf.py`, state `mf.db`), run by the existing `espero daily` job.
A test checks that it reproduces `research/multifactor.py`'s simulator day by day on the same data.

## Window

- **Start**: the first Monday after this commit, **2026-11-02** (decision at the close of Sunday
  2026-11-01). Until then the account holds cash.
- **End**: **2027-05-03**, 26 weekly rebalances later. The verdict is computed on the daily marks
  from the start through the end, inclusive.
- **Cash**: $100, the same as the XS account.

## Operational rules, fixed in advance

- **Missed Monday** (the Mac was off): the pending Sunday decision is filled at the first run after,
  at that run's latest price, and recorded as `late`. It is never filled at a historical Monday open
  the account could not have traded at.
- **Bad data**: fewer than 30 of 42 coins loaded → mark only, no trade, retried on the next run.
- **A held coin that stops reporting** is marked at its last known price, never dropped from equity.
- Every late fill, skipped day and data failure is counted in the result.

## Amendment 2026-10-29, before the first fill — the Monday fill price, disclosed

An on-time Monday fills at **Monday's 00:00 UTC open**, as the backtest and the simulator do, but the
scheduled job runs at 07:30 New York (11:30–12:30 UTC). The decision reads nothing after Sunday's
close, so no later information enters it, and a job run at 00:00 UTC could have traded that price;
this schedule cannot. The rule is not changed (the account must stay equal to the simulator, which
tests/test_mf.py enforces). The sentence above about missed Mondays applies to missed Mondays only.

At the verdict, for every Monday's fills, the result reports the gap between that 00:00 UTC open and
the price at the 07:30 run (from hourly bars), information only, so the reader can see what the
timing assumption was worth over the 26 weeks.

## Amendment 2026-10-29, before the first fill — a Hyperliquid shadow book, information only

A second account (`mf-hl.db`, the daily job's `mf-hl` step) runs this exact rule on Hyperliquid
perp prices instead of Yahoo's: the 35 of the 42 coins Hyperliquid lists (MKR, YFI, XTZ, EOS, KSM,
VET and THETA are not), daily bars from its mainnet, dollar volume as close × coins traded. It
starts and decides on the same calendar. It cannot change the verdict, which is computed on
`mf.db` only; it is reported beside it, so the reader can see how much the price source matters.

## Pass criteria — all three, over the forward window

Measured on the account's daily equity marks (rf = 0, √365):

1. Sharpe greater than BTC buy-and-hold over the same days
2. max drawdown shallower than BTC buy-and-hold
3. positive return net of fees

The holdout's fourth criterion (composite rank IC t > 3) is not testable on 26 weeks and is reported
for information only, as is the comparison with the XS account and with equal-weight eligible.

A pass on six months is still not a reason for capital: 26 weekly decisions is a small sample, and
the backtest's decomposition says most of the return came from holding cash when vol rose and a tilt
to calm coins. A fail ends #8.

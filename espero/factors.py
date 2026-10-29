"""The factor zoo: named, pure, signed.

Each factor is a function of a MarketPanel returning a panel where a HIGHER
value is the factor's claim of a higher forward return. The sign is part of
the definition, fixed here before any evaluation, so a factor cannot be
flipped after the fact to make its IC positive. Where the literature's sign
is contested the docstring says so and the factor is listed as *unsigned*.

Names are stable: the pre-registration documents refer to them.
"""
from __future__ import annotations

from typing import Callable, Dict

import numpy as np
import pandas as pd

from . import ops
from .panel import MarketPanel

Factor = Callable[[MarketPanel], pd.DataFrame]


# -------------------------------------------------------------- momentum
def momentum(p: MarketPanel, n: int = 30, skip: int = 1) -> pd.DataFrame:
    """Return over the n days ending `skip` days ago. The skip leaves out the
    most recent day(s), where short-term reversal lives."""
    c = p.close
    return c.shift(skip) / c.shift(n + skip) - 1


def mom_7(p):
    return momentum(p, 7, 1)


def mom_30(p):
    return momentum(p, 30, 1)


def mom_90(p):
    return momentum(p, 90, 1)


# -------------------------------------------------------------- reversal
def rev_3(p: MarketPanel) -> pd.DataFrame:
    """Negative of the trailing 3-day return: yesterday's losers are expected
    to bounce. Sign from the equity and crypto short-horizon literature."""
    return -ops.returns(p.close, 3)


def rev_1(p: MarketPanel) -> pd.DataFrame:
    return -ops.returns(p.close, 1)


# ------------------------------------------------------------------ risk
def lowvol_30(p: MarketPanel) -> pd.DataFrame:
    """Negative realized volatility: the low-vol anomaly, signed so that
    calmer assets rank higher."""
    return -ops.ts_std(ops.log_returns(p.close, 1), 30)


def maxret_30(p: MarketPanel) -> pd.DataFrame:
    """Negative of the largest daily return in the window (the lottery
    effect, Bali-Cakici-Whitelaw): big recent jackpots underperform."""
    return -ops.ts_max(ops.returns(p.close, 1), 30)


# ------------------------------------------------------------- liquidity
def amihud_30(p: MarketPanel) -> pd.DataFrame:
    """Amihud illiquidity, |return| per dollar traded, averaged over 30 days.
    Signed positive: the literature's illiquidity premium. Contested in
    crypto, where illiquid often means dying -- treat as unsigned evidence."""
    dv = p.dollar_volume.replace(0, np.nan)
    return ops.ts_mean(ops.returns(p.close, 1).abs() / dv, 30)


def volume_z_20(p: MarketPanel) -> pd.DataFrame:
    """Abnormal volume: today's dollar volume as a z-score of the last 20
    days. Unsigned; attention can mean either continuation or exhaustion."""
    return ops.ts_zscore(np.log(p.dollar_volume.replace(0, np.nan)), 20)


# -------------------------------------------------------------- alpha101
def alpha101_6(p: MarketPanel) -> pd.DataFrame:
    """Alpha#6: -1 * correlation(open, volume, 10)."""
    return -ops.ts_corr(p.open, p.volume, 10)


def alpha101_12(p: MarketPanel) -> pd.DataFrame:
    """Alpha#12: sign(delta(volume, 1)) * (-1 * delta(close, 1))."""
    return np.sign(ops.ts_delta(p.volume, 1)) * (-ops.ts_delta(p.close, 1))


def alpha101_101(p: MarketPanel) -> pd.DataFrame:
    """Alpha#101: (close - open) / ((high - low) + .001). Intraday strength."""
    return (p.close - p.open) / ((p.high - p.low) + 0.001)


# --------------------------------------------------------------- lead-lag
def leadlag(p: MarketPanel, n: int = 1, leader: str = "BTC") -> pd.DataFrame:
    """The gap between the leader's last-n-bar return and each coin's own:
    r_leader(t-n, t) - r_i(t-n, t). Sign positive: a coin that has not yet
    moved with the leader is expected to catch up. The leader itself is NaN
    (it cannot lag itself)."""
    if leader not in p.close.columns:
        raise KeyError(f"leader {leader} not in panel")
    r = ops.returns(p.close, n)
    out = (-r).add(r[leader], axis=0)
    out[leader] = np.nan
    return out


def rolling_beta(p: MarketPanel, window: int = 168, leader: str = "BTC") -> pd.DataFrame:
    """Each coin's trailing beta to the leader from one-bar returns: cov / var
    over `window` bars, causal. The leader's own beta is 1 by construction."""
    r = ops.returns(p.close, 1)
    lead = r[leader]
    cov = r.rolling(window, min_periods=window).cov(lead)
    var = lead.rolling(window, min_periods=window).var()
    return cov.div(var.replace(0, np.nan), axis=0)


def leadlag_beta(p: MarketPanel, n: int = 1, window: int = 168, leader: str = "BTC") -> pd.DataFrame:
    """beta_i * r_leader(t-n, t) - r_i(t-n, t): how far coin i fell short of
    the move its own beta says it should have made. Unlike the unscaled gap,
    this varies across coins within an hour, so it can be ranked."""
    if leader not in p.close.columns:
        raise KeyError(f"leader {leader} not in panel")
    r = ops.returns(p.close, n)
    beta = rolling_beta(p, window, leader)
    out = beta.mul(r[leader], axis=0) - r
    out[leader] = np.nan
    return out


def push(p: MarketPanel, n: int = 1, window: int = 168, leader: str = "BTC") -> pd.DataFrame:
    """beta_i * r_leader(t-n, t): only the part of #9b's gap that is about the
    leader (#17, research/PREREGISTRATION_PEERS.md). It leaves out the coin's own
    return, where the bid-ask bounce lives, and since a high-beta coin moved with
    the leader, the bounce biases its IC down, not up."""
    if leader not in p.close.columns:
        raise KeyError(f"leader {leader} not in panel")
    out = rolling_beta(p, window, leader).mul(ops.returns(p.close, n)[leader], axis=0)
    out[leader] = np.nan
    return out


def peer_basket(p: MarketPanel, members: pd.DataFrame, n: int = 1,
                exclude=("BTC",)) -> pd.DataFrame:
    """Each coin's own leader for #16: the equal-weighted mean n-bar return of
    the coins in `members` (a dated boolean panel, the eligibility mask) on that
    bar, leaving out `exclude` and the coin itself. NaN where no other member
    has a return."""
    r = ops.returns(p.close, n)
    m = members.reindex_like(r).fillna(False).astype(bool) & r.notna()
    for c in exclude:
        if c in m.columns:
            m[c] = False
    own = r.where(m, 0.0)
    total, count = own.sum(axis=1), m.sum(axis=1)
    others = (-m.astype(int)).add(count, axis=0)
    return (-own).add(total, axis=0) / others.where(others > 0)


def beta_each(r: pd.DataFrame, lead: pd.DataFrame, window: int = 168) -> pd.DataFrame:
    """cov(r_i, lead_i) / var(lead_i) over `window` bars, column by column: each
    coin against its own leader series. Bars where the coin has no return are
    left out of the leader's variance too, so both use the same bars."""
    out = {}
    for c in r.columns:
        x, y = r[c], lead[c].where(r[c].notna())
        cov = x.rolling(window, min_periods=window).cov(y)
        var = y.rolling(window, min_periods=window).var()
        out[c] = cov / var.replace(0, np.nan)
    return pd.DataFrame(out, index=r.index)


def push_peers(p: MarketPanel, members: pd.DataFrame, n: int = 1, window: int = 168) -> pd.DataFrame:
    """#16: beta_i,B * B_-i(t-n, t), the coin's beta to its leave-one-out peer
    basket times the basket's last n-bar move. BTC is NaN: it is in neither."""
    beta = beta_each(ops.returns(p.close, 1), peer_basket(p, members, 1), window)
    out = beta * peer_basket(p, members, n)
    if "BTC" in out.columns:
        out["BTC"] = np.nan
    return out


def gap_peers(p: MarketPanel, members: pd.DataFrame, n: int = 1, window: int = 168,
              scaled: bool = True) -> pd.DataFrame:
    """#9b's gap with the peer basket as the leader: (beta_i,B *) B_-i - r_i.
    Unscaled, its ranks are -r_i's, exactly, on every bar. Information only."""
    lead = peer_basket(p, members, n)
    if scaled:
        lead = lead * beta_each(ops.returns(p.close, 1), peer_basket(p, members, 1), window)
    out = lead - ops.returns(p.close, n)
    if "BTC" in out.columns:
        out["BTC"] = np.nan
    return out


def leadlag_beta_1h(p):
    return leadlag_beta(p, 1)


def leadlag_beta_3h(p):
    return leadlag_beta(p, 3)


def leadlag_1h(p):
    return leadlag(p, 1)


def leadlag_3h(p):
    return leadlag(p, 3)


# ----------------------------------------------------------------- carry
def carry(p: MarketPanel, funding: pd.DataFrame, n: int = 7) -> pd.DataFrame:
    """Negative mean funding over n days: when longs pay shorts the long is
    expensive to hold. `funding` is a panel aligned to `p` that the caller
    has already made point-in-time with `features.attach`."""
    return -ops.ts_mean(funding.reindex_like(p.close), n)


# ------------------------------------------------------------------- zoo
ZOO: Dict[str, Factor] = {
    "mom_7": mom_7,
    "mom_30": mom_30,
    "mom_90": mom_90,
    "rev_1": rev_1,
    "rev_3": rev_3,
    "lowvol_30": lowvol_30,
    "maxret_30": maxret_30,
    "amihud_30": amihud_30,
    "volume_z_20": volume_z_20,
    "alpha101_6": alpha101_6,
    "alpha101_12": alpha101_12,
    "alpha101_101": alpha101_101,
    "leadlag_1h": leadlag_1h,
    "leadlag_3h": leadlag_3h,
    "leadlag_beta_1h": leadlag_beta_1h,
    "leadlag_beta_3h": leadlag_beta_3h,
}

UNSIGNED = {"amihud_30", "volume_z_20"}


def composite(p: MarketPanel, names, mask: pd.DataFrame = None,
              weights: Dict[str, float] = None) -> pd.DataFrame:
    """Rank-average of several factors on each date: the honest baseline
    before any model is allowed to pick the weights. Each factor is
    MAD-winsorized then cross-sectionally ranked so no single factor's scale
    dominates."""
    weights = weights or {n: 1.0 for n in names}
    total = sum(weights[n] for n in names)
    acc = None
    for n in names:
        f = ops.where_valid(ZOO[n](p), mask)
        r = ops.cs_rank(ops.winsorize_mad(f)) * (weights[n] / total)
        acc = r if acc is None else acc.add(r, fill_value=np.nan)
    return acc

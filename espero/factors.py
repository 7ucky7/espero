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

"""From a ranking to a set of weights that a small account can actually carry.

Three ideas, each written down because each is a place where a backtest can
quietly become unrealistic:

* **vol targeting** -- scale each position by target / realized vol so the
  book's risk does not double when crypto's does (Moskowitz, Ooi & Pedersen's
  TSMOM form). Never above 100% gross: this repo does not borrow.
* **weight caps** -- no single name above `max_weight`, excess redistributed.
* **turnover buffer** -- keep a holding until it drops out of the top
  `buffer * top`, enter only from the top `top`. This is the index-enhancement
  trick that lets a weekly cross-sectional book survive its own fees.

Nothing here is wired into a live paper account by default. A rule that
changes mid-track-record is a new hypothesis, and gets a new pre-registration.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from . import ops


def realized_vol(close: pd.DataFrame, window: int = 30, periods_per_year: int = 365) -> pd.DataFrame:
    """Annualized trailing volatility of daily log returns, per asset."""
    return ops.ts_std(ops.log_returns(close, 1), window) * np.sqrt(periods_per_year)


def vol_scaled(weights: pd.Series, vol: pd.Series, target: float = 0.20,
               max_gross: float = 1.0, max_scale: float = 2.0) -> pd.Series:
    """Scale each weight by target / vol, cap the scale, then cap gross exposure.

    Returns weights whose sum is <= max_gross; the remainder is cash. Assets
    with no vol estimate get weight 0 -- unknown risk is not a position.
    """
    w = weights.astype(float).copy()
    v = vol.reindex(w.index)
    scale = (target / v).clip(upper=max_scale)
    out = (w * scale).fillna(0.0)
    gross = out.abs().sum()
    if gross > max_gross and gross > 0:
        out = out * (max_gross / gross)
    return out


def cap_weights(weights: pd.Series, max_weight: float, iterations: int = 20) -> pd.Series:
    """Cap any weight above `max_weight`, redistributing the excess pro rata to
    the uncapped names until no weight is above the cap (or nothing can take it)."""
    w = weights.astype(float).clip(lower=0).copy()
    capped = pd.Series(False, index=w.index)
    for _ in range(iterations):
        over = (w > max_weight + 1e-12) & ~capped
        if not over.any():
            break
        excess = float((w[over] - max_weight).sum())
        w[over] = max_weight
        capped |= over
        room = w[~capped]
        if room.sum() <= 0:
            break
        w[~capped] = room + excess * room / room.sum()
    return w


def turnover_buffer(scores: pd.Series, held: Iterable[str], top: int, buffer: float = 2.0) -> List[str]:
    """Pick `top` names: keep every held name still ranked within `buffer * top`,
    then fill the remaining slots from the best non-held names.

    `scores`: higher is better, NaN is ineligible. Returns the names to hold.
    """
    s = scores.dropna().sort_values(ascending=False)
    if s.empty or top <= 0:
        return []
    rank = pd.Series(np.arange(1, len(s) + 1), index=s.index)
    keep = [c for c in held if c in rank.index and rank[c] <= buffer * top]
    keep = sorted(keep, key=lambda c: rank[c])[:top]
    for c in s.index:
        if len(keep) >= top:
            break
        if c not in keep:
            keep.append(c)
    return keep


def equal_weight(names: Iterable[str], universe: Iterable[str]) -> pd.Series:
    names = list(names)
    w = 1.0 / len(names) if names else 0.0
    return pd.Series({c: (w if c in names else 0.0) for c in universe}, dtype=float)


def portfolio_vol(weights: pd.Series, cov: pd.DataFrame, periods_per_year: int = 365) -> float:
    """Annualized ex-ante volatility of the book from a daily covariance."""
    w = weights.reindex(cov.index).fillna(0.0).to_numpy()
    return float(np.sqrt(max(0.0, w @ cov.to_numpy() @ w)) * np.sqrt(periods_per_year))


def target_portfolio_vol(weights: pd.Series, cov: pd.DataFrame, target: float = 0.20,
                         max_gross: float = 1.0, periods_per_year: int = 365) -> pd.Series:
    """Scale the whole book to a target ex-ante vol, never above max_gross."""
    v = portfolio_vol(weights, cov, periods_per_year)
    if v <= 0:
        return weights * 0.0
    scaled = weights * min(target / v, max_gross / max(weights.abs().sum(), 1e-12))
    return scaled


def daily_cov(close: pd.DataFrame, window: int = 60) -> Optional[pd.DataFrame]:
    r = ops.log_returns(close, 1).iloc[-window:]
    if len(r) < max(10, window // 2):
        return None
    return r.cov()


def describe(weights: pd.Series) -> Dict[str, float]:
    w = weights[weights > 0]
    return {"n": int(w.size), "gross": float(w.sum()), "max": float(w.max()) if w.size else 0.0,
            "cash": float(1 - w.sum())}

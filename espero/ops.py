"""Alpha operators, in the WorldQuant Alpha101 / Guotai Junan Alpha191 dialect.

Every function takes a *panel*: a DataFrame indexed by date with one column
per asset. Time-series operators (`ts_*`) look back along the index and are
causal by construction -- a value at date t uses rows <= t, and
`tests/test_ops.py` proves it by recomputing on a truncated panel. Cross-
sectional operators (`cs_*`) act within a single row and never look at
another date.

The dialect is deliberately the one the factor literature uses, so that an
expression such as

    -1 * cs_rank(ts_corr(cs_rank(volume), cs_rank(close), 10))

can be copied from a paper into `factors.py` without translation.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

Panel = pd.DataFrame


# --------------------------------------------------------------- time series
def ts_delay(x: Panel, n: int) -> Panel:
    return x.shift(n)


def ts_delta(x: Panel, n: int) -> Panel:
    return x - x.shift(n)


def ts_sum(x: Panel, n: int) -> Panel:
    return x.rolling(n, min_periods=n).sum()


def ts_mean(x: Panel, n: int) -> Panel:
    return x.rolling(n, min_periods=n).mean()


def ts_std(x: Panel, n: int) -> Panel:
    return x.rolling(n, min_periods=n).std()


def ts_min(x: Panel, n: int) -> Panel:
    return x.rolling(n, min_periods=n).min()


def ts_max(x: Panel, n: int) -> Panel:
    return x.rolling(n, min_periods=n).max()


def ts_argmax(x: Panel, n: int) -> Panel:
    """Days since the window's maximum (0 = today), as in Alpha101."""
    return x.rolling(n, min_periods=n).apply(lambda w: n - 1 - int(np.argmax(w)), raw=True)


def ts_argmin(x: Panel, n: int) -> Panel:
    return x.rolling(n, min_periods=n).apply(lambda w: n - 1 - int(np.argmin(w)), raw=True)


def ts_rank(x: Panel, n: int) -> Panel:
    """Percentile rank of today's value within the trailing window, in (0, 1]."""
    def last_rank(w: np.ndarray) -> float:
        if np.isnan(w).any():
            return np.nan
        return float((w <= w[-1]).sum()) / len(w)
    return x.rolling(n, min_periods=n).apply(last_rank, raw=True)


def ts_zscore(x: Panel, n: int) -> Panel:
    sd = ts_std(x, n)
    return (x - ts_mean(x, n)) / sd.replace(0, np.nan)


def ts_corr(x: Panel, y: Panel, n: int) -> Panel:
    return x.rolling(n, min_periods=n).corr(y)


def ts_cov(x: Panel, y: Panel, n: int) -> Panel:
    return x.rolling(n, min_periods=n).cov(y)


def decay_linear(x: Panel, n: int) -> Panel:
    """Linearly weighted mean, newest observation heaviest (weights n, n-1, ..., 1)."""
    w = np.arange(1, n + 1, dtype=float)
    w /= w.sum()
    return x.rolling(n, min_periods=n).apply(lambda v: float(np.dot(v, w)), raw=True)


def returns(close: Panel, n: int = 1) -> Panel:
    return close / close.shift(n) - 1


def log_returns(close: Panel, n: int = 1) -> Panel:
    return np.log(close / close.shift(n))


# ------------------------------------------------------------ cross section
def cs_rank(x: Panel) -> Panel:
    """Percentile rank across assets on each date, in (0, 1]. NaN stays NaN."""
    return x.rank(axis=1, pct=True)


def cs_demean(x: Panel) -> Panel:
    return x.sub(x.mean(axis=1), axis=0)


def cs_zscore(x: Panel) -> Panel:
    sd = x.std(axis=1).replace(0, np.nan)
    return cs_demean(x).div(sd, axis=0)


def cs_scale(x: Panel, k: float = 1.0) -> Panel:
    """Rescale each row so the sum of absolute values is k (Alpha101's `scale`)."""
    denom = x.abs().sum(axis=1).replace(0, np.nan)
    return x.div(denom, axis=0) * k


def winsorize_mad(x: Panel, k: float = 3.0) -> Panel:
    """Clip each row to median +/- k * 1.4826 * MAD. Robust to the one coin that
    did +400% on the day, which a mean/std clip is not."""
    med = x.median(axis=1)
    mad = (x.sub(med, axis=0)).abs().median(axis=1) * 1.4826
    lo = med - k * mad
    hi = med + k * mad
    return x.clip(lower=lo, upper=hi, axis=0)


def cs_neutralize(x: Panel, *exposures: Panel, add_intercept: bool = True) -> Panel:
    """Residual of a per-date OLS of `x` on the exposure panels.

    This is the "size/industry neutral" step: whatever part of a factor is
    explained by, say, log market cap or a sector dummy is removed, so the
    ranking that remains is the factor's own. One regression per row; assets
    missing any input on that date are left NaN.
    """
    out = pd.DataFrame(np.nan, index=x.index, columns=x.columns)
    for dt in x.index:
        y = x.loc[dt].to_numpy(dtype=float)
        cols = [e.loc[dt].to_numpy(dtype=float) if dt in e.index
                else np.full(len(y), np.nan) for e in exposures]
        X = np.column_stack(cols) if cols else np.empty((len(y), 0))
        if add_intercept:
            X = np.column_stack([np.ones(len(y)), X])
        ok = ~np.isnan(y) & ~np.isnan(X).any(axis=1)
        if ok.sum() <= X.shape[1]:
            continue
        beta, *_ = np.linalg.lstsq(X[ok], y[ok], rcond=None)
        resid = np.full(len(y), np.nan)
        resid[ok] = y[ok] - X[ok] @ beta
        out.loc[dt] = resid
    return out


# ------------------------------------------------------------------ helpers
def where_valid(x: Panel, mask: Optional[Panel]) -> Panel:
    """Apply an eligibility mask (True = tradable) without changing the shape."""
    if mask is None:
        return x
    return x.where(mask.reindex_like(x).fillna(False).astype(bool))

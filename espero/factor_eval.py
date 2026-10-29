"""How a factor is judged: rank IC, its stability, what the top quantile
actually earns, how much it churns, and whether any of that survives a
purged walk-forward split and a correction for the number of things tried.

The forward return is the only place in the package that looks at the
future, and it is computed here, named for what it is, and never attached to
a bar as a feature.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import ops
from .factors import ZOO, Factor
from .panel import MarketPanel

T_HURDLE = 3.0   # Harvey, Liu & Zhu (2016): a new factor needs t > 3, not 2


# -------------------------------------------------------------- building blocks
def forward_returns(close: pd.DataFrame, horizon: int = 1) -> pd.DataFrame:
    """Return from today's close to the close `horizon` days later, stamped
    today. This is the label, not a feature."""
    return close.shift(-horizon) / close - 1


def ic_series(factor: pd.DataFrame, fwd: pd.DataFrame, method: str = "spearman") -> pd.Series:
    """Per-date cross-sectional correlation between factor and forward return.

    Spearman is computed as the Pearson correlation of ranks, so the package
    does not need scipy for it.
    """
    f, r = factor.align(fwd, join="inner")
    out = {}
    for dt in f.index:
        a, b = f.loc[dt], r.loc[dt]
        ok = a.notna() & b.notna()
        if ok.sum() < 5:
            continue
        a, b = a[ok], b[ok]
        if method == "spearman":
            a, b = a.rank(), b.rank()
        out[dt] = float(np.corrcoef(a.to_numpy(dtype=float), b.to_numpy(dtype=float))[0, 1])
    return pd.Series(out, dtype=float).dropna()


@dataclass
class ICSummary:
    n: int
    mean: float
    std: float
    icir: float
    t: float
    hit: float          # fraction of dates with IC > 0
    t_nw: float = float("nan")   # Newey-West t: corrects for overlapping forward returns

    def as_dict(self) -> dict:
        return {"n": self.n, "ic": self.mean, "ic_std": self.std, "icir": self.icir,
                "t": self.t, "hit": self.hit, "t_nw": self.t_nw}


def newey_west_t(x: pd.Series, lags: int) -> float:
    """t-statistic of the mean of `x` with a Newey-West (Bartlett) long-run
    variance over `lags` lags. Daily ICs of h-day forward returns overlap, so
    neighbours share h-1 days of the label and are positively autocorrelated:
    the plain t = ICIR * sqrt(n) then overstates significance (about 2x at
    h = 5 for a persistent factor). Use lags >= h - 1; with Bartlett weights
    2 * (h - 1) gets a null's t close to unit variance."""
    v = np.asarray(x, dtype=float)
    n = v.size
    if n < 3:
        return float("nan")
    d = v - v.mean()
    lr = float(d @ d) / n
    for lag in range(1, min(lags, n - 1) + 1):
        lr += 2 * (1 - lag / (lags + 1)) * float(d[lag:] @ d[:-lag]) / n
    return float(v.mean() / math.sqrt(lr / n)) if lr > 0 else float("nan")


def summarize(ic: pd.Series, lags: int = 0) -> ICSummary:
    """`t` is the plain ICIR * sqrt(n) (what the pre-registrations use);
    `t_nw` the Newey-West t over `lags` lags (evaluate uses 2 * (horizon - 1))."""
    n = int(ic.size)
    if n < 2:
        return ICSummary(n, float("nan"), float("nan"), float("nan"), float("nan"), float("nan"))
    m, s = float(ic.mean()), float(ic.std(ddof=1))
    icir = m / s if s > 0 else float("nan")
    return ICSummary(n, m, s, icir, icir * math.sqrt(n) if s > 0 else float("nan"),
                     float((ic > 0).mean()), newey_west_t(ic, lags))


def ic_decay(factor: pd.DataFrame, close: pd.DataFrame,
             horizons: Sequence[int] = (1, 3, 5, 10, 20)) -> pd.Series:
    """Mean IC by forward horizon: a factor that only works at h=1 is a
    trading-cost problem, one that grows with h is a slow signal."""
    return pd.Series({h: summarize(ic_series(factor, forward_returns(close, h))).mean
                      for h in horizons})


def fama_macbeth(fwd: pd.DataFrame, regressors: Dict[str, pd.DataFrame], min_obs: int = 5) -> pd.DataFrame:
    """Per date, the cross-sectional OLS of the forward return's rank on each
    regressor's rank, every rank centred and scaled to unit variance; one
    coefficient column per regressor. A date needs `min_obs` assets with every
    value present, and some spread in each, or it is skipped."""
    names = list(regressors)
    frames = {k: v.reindex_like(fwd) for k, v in regressors.items()}
    rows = {}
    for dt in fwd.index:
        cols = [fwd.loc[dt]] + [frames[k].loc[dt] for k in names]
        ok = np.logical_and.reduce([c.notna().to_numpy() for c in cols])
        if ok.sum() < max(min_obs, len(names) + 2):
            continue
        z = []
        for c in cols:
            rk = c[ok].rank()
            sd = rk.std(ddof=0)
            if sd == 0:
                break
            z.append(((rk - rk.mean()) / sd).to_numpy(dtype=float))
        else:
            x = np.column_stack([np.ones(len(z[0]))] + z[1:])
            coef = np.linalg.lstsq(x, z[0], rcond=None)[0]
            rows[dt] = dict(zip(names, coef[1:]))
    return pd.DataFrame(rows, index=names, dtype=float).T.sort_index()


def quantile_returns(factor: pd.DataFrame, fwd: pd.DataFrame, q: int = 5) -> pd.DataFrame:
    """Mean forward return per factor quantile per date (columns 1..q, q = best)."""
    f, r = factor.align(fwd, join="inner")
    rows = {}
    for dt in f.index:
        a, b = f.loc[dt], r.loc[dt]
        ok = a.notna() & b.notna()
        if ok.sum() < q * 2:
            continue
        ranks = a[ok].rank(pct=True)
        bucket = np.minimum((ranks * q).apply(math.ceil), q)
        rows[dt] = b[ok].groupby(bucket).mean()
    out = pd.DataFrame(rows).T.sort_index()
    out.columns = [int(c) for c in out.columns]
    return out


def spread(qr: pd.DataFrame) -> pd.Series:
    """Top minus bottom quantile, per date."""
    q = max(qr.columns)
    return qr[q] - qr[1]


def top_quantile_turnover(factor: pd.DataFrame, q: int = 5) -> float:
    """Average fraction of the top quantile replaced from one date to the next."""
    top = ops.cs_rank(factor) > 1 - 1 / q
    prev = top.shift(1)
    both = top & prev.fillna(False).astype(bool)
    n_top = top.sum(axis=1).replace(0, np.nan)
    churn = 1 - both.sum(axis=1) / n_top
    return float(churn.iloc[1:].mean())


# ------------------------------------------------------------- walk-forward
def purged_walk_forward(index: pd.DatetimeIndex, n_splits: int = 4, horizon: int = 1,
                        embargo: int = 5, min_train: int = 180
                        ) -> List[Tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
    """Expanding-window splits with a purge gap of `horizon + embargo` days
    between the end of training and the start of the test block, so a label
    that reaches into the test period is never in the training set (López de
    Prado, ch. 7). Test blocks are contiguous and do not overlap."""
    index = pd.DatetimeIndex(index)
    n = len(index)
    if n <= min_train + n_splits:
        raise ValueError(f"{n} dates is too few for {n_splits} splits with {min_train} training days")
    edges = np.linspace(min_train, n, n_splits + 1).astype(int)
    out = []
    gap = horizon + embargo
    for i in range(n_splits):
        test = index[edges[i]:edges[i + 1]]
        train_end = max(0, edges[i] - gap)
        train = index[:train_end]
        if len(train) and len(test):
            out.append((train, test))
    return out


# ------------------------------------------------------ multiple testing
def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """E[max SR] of n_trials zero-skill strategies (Bailey & López de Prado)."""
    if n_trials <= 1 or var_sr <= 0:
        return 0.0
    nd = NormalDist()
    gamma = 0.5772156649
    return math.sqrt(var_sr) * ((1 - gamma) * nd.inv_cdf(1 - 1 / n_trials)
                                + gamma * nd.inv_cdf(1 - 1 / (n_trials * math.e)))


def deflated_sharpe(sr: float, n_trials: int, n_obs: int, skew: float = 0.0,
                    kurt: float = 3.0, var_sr: Optional[float] = None) -> float:
    """Probability that the observed per-period Sharpe `sr` beats the best of
    `n_trials` lucky draws. Above 0.95 is the usual bar. `var_sr` defaults to
    the sampling variance of a zero Sharpe over n_obs periods."""
    if n_obs < 3:
        return float("nan")
    var_sr = (1.0 / (n_obs - 1)) if var_sr is None else var_sr
    sr0 = expected_max_sharpe(n_trials, var_sr)
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr * sr))
    z = (sr - sr0) * math.sqrt(n_obs - 1) / denom
    return NormalDist().cdf(z)


# ---------------------------------------------------------------- the table
def evaluate(p: MarketPanel, names: Iterable[str] = None, horizon: int = 5, q: int = 5,
             mask: pd.DataFrame = None, n_splits: int = 4, embargo: int = 5,
             factors: Dict[str, Factor] = None, min_train: int = 180) -> pd.DataFrame:
    """One row per factor: in-sample and out-of-sample IC statistics under the
    purged split, the quantile spread, turnover, and the pass flag.

    OOS here means the union of the test blocks: each block's factor values
    are computed on history only (the operators are causal), and the
    evaluation of a block never informs the choice of what to evaluate on
    the next -- the names are fixed before the call.
    """
    factors = factors or ZOO
    names = list(names) if names is not None else list(factors)
    fwd = forward_returns(p.close, horizon)
    # dates before anything is eligible carry no information; splitting them
    # would make the first training block empty
    dates = p.index if mask is None else p.index[mask.reindex(p.index).fillna(False).any(axis=1)]
    splits = purged_walk_forward(dates, n_splits=n_splits, horizon=horizon, embargo=embargo,
                                 min_train=min_train)
    test_dates = pd.DatetimeIndex(sorted(set().union(*[set(t) for _, t in splits])))
    train_dates = splits[0][0]
    rows = []
    for name in names:
        f = ops.where_valid(factors[name](p), mask)
        ic = ic_series(f, fwd)
        lags = 2 * max(0, horizon - 1)    # Bartlett weights under-correct at h - 1 lags
        ins = summarize(ic.reindex(train_dates).dropna(), lags)
        oos = summarize(ic.reindex(test_dates).dropna(), lags)
        qr = quantile_returns(f.reindex(test_dates), fwd.reindex(test_dates), q)
        sp = spread(qr) if not qr.empty else pd.Series(dtype=float)
        rows.append({
            "factor": name, "horizon": horizon,
            "ic_is": ins.mean, "t_is": ins.t,
            "ic_oos": oos.mean, "icir_oos": oos.icir, "t_oos": oos.t, "t_oos_nw": oos.t_nw,
            "hit_oos": oos.hit,
            "n_oos": oos.n,
            "spread_oos": float(sp.mean()) if sp.size else float("nan"),
            "turnover": top_quantile_turnover(f.reindex(test_dates), q),
            # the pre-registered rule is the plain t; t_oos_nw is reported beside it
            "pass": bool(oos.t > T_HURDLE),
        })
    out = pd.DataFrame(rows).set_index("factor")
    out.attrs["n_trials"] = len(names)
    out.attrs["test_dates"] = test_dates
    out.attrs["splits"] = [(str(tr[0].date()), str(tr[-1].date()), str(te[0].date()), str(te[-1].date()))
                           for tr, te in splits]
    return out


def format_table(t: pd.DataFrame) -> str:
    lines = [f"{'factor':14s} {'IC is':>7s} {'t is':>6s} {'IC oos':>7s} {'ICIR':>6s} {'t oos':>6s} "
             f"{'t NW':>6s} {'hit':>5s} {'Q5-Q1':>7s} {'churn':>6s}  pass"]
    for name, r in t.iterrows():
        lines.append(f"{name:14s} {r['ic_is']:+7.3f} {r['t_is']:6.2f} {r['ic_oos']:+7.3f} "
                     f"{r['icir_oos']:6.2f} {r['t_oos']:6.2f} {r.get('t_oos_nw', float('nan')):6.2f} "
                     f"{r['hit_oos']:5.2f} "
                     f"{100 * r['spread_oos']:+6.2f}% {r['turnover']:6.2f}  {'YES' if r['pass'] else '-'}")
    n = t.attrs.get("n_trials", len(t))
    lines.append("")
    lines.append(f"{n} factors tried; pass = OOS t > {T_HURDLE:.0f} (Harvey-Liu-Zhu hurdle). "
                 f"Expected best t among {n} null factors over {int(t['n_oos'].max())} dates "
                 f"≈ {expected_max_sharpe(n, 1.0):.2f}, if dates were independent.")
    h = int(t["horizon"].iloc[0]) if "horizon" in t and len(t) else 1
    if h > 1:
        lines.append(f"t NW: Newey-West with {2 * (h - 1)} lags. Daily ICs of {h}-period returns overlap, so the "
                     f"plain t overstates; read the pass column against t NW as well.")
    for tr0, tr1, te0, te1 in t.attrs.get("splits", []):
        lines.append(f"  train {tr0}..{tr1}  test {te0}..{te1}")
    return "\n".join(lines)

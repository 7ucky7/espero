"""Perpetual funding carry, delta-neutral, hourly — hypothesis #11.

Short the perp, hold the same notional in spot, collect the funding longs pay.
Rule and costs are frozen in research/PREREGISTRATION_CARRY.md; the numbers
below are those numbers and nothing here tunes them.

The simulation is a plain hourly loop over aligned series so every dollar can
be traced: cash, spot inventory marked at the spot close, the short's unrealised
P&L against its entry price, funding credited at the venue's hourly rate on the
perp's current notional, fees and slippage on both legs at entry and exit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

HOURS_PER_YEAR = 8760
LOOKBACK_H = 168            # trailing week of hourly funding
ENTER_ANN = 0.15            # annualised funding to open
EXIT_ANN = 0.05             # annualised funding to close
MAX_HOLD_H = 30 * 24
MAX_COINS = 5
MIN_HISTORY_H = 90 * 24
SPOT_FEES = {"binanceus": 0.0002, "kraken": 0.0040}
PERP_FEE = 0.00045          # Hyperliquid base-tier taker
SLIPPAGE = 0.0005           # per leg per side

# #12 (research/PREREGISTRATION_CARRY2.md): swap hysteresis and maker execution.
# Defaults of 0 reproduce #11 exactly.
SWAP_GAP = 0.05             # candidate must pay 5 points more than the weakest held coin
MIN_HOLD_H = 7 * 24         # and the held coin must be at least a week old to be swapped
MAKER = {"spot": {"binanceus": 0.0, "kraken": 0.0025}, "perp": 0.00015, "slippage": 0.0}

CRITERIA = (
    ("net annualised return on equity", "> 8%", lambda m: m["ann_return"] > 0.08),
    ("max drawdown of equity", "< 5%", lambda m: m["max_dd"] < 0.05),
    ("Sharpe (hourly, annualised)", "> 1.5", lambda m: m["sharpe"] > 1.5),
    ("funding paid / received", "< 25%", lambda m: m["paid_ratio"] < 0.25),
    ("net annualised return, Kraken spot fees", "> 4%", lambda m: m["ann_return_kraken"] > 0.04),
)


@dataclass
class CoinData:
    """Hourly series on a UTC DatetimeIndex: funding rate per hour, perp close, spot close."""
    funding: pd.Series
    perp: pd.Series
    spot: pd.Series


@dataclass
class Position:
    coin: str
    entry_i: int
    qty_spot: float
    qty_perp: float
    perp_entry: float
    spot_entry: float
    fees: float = 0.0
    funding: float = 0.0


@dataclass
class Result:
    equity: pd.Series
    trades: List[dict] = field(default_factory=list)
    funding_received: float = 0.0
    funding_paid: float = 0.0
    fees: float = 0.0
    hours_in_position: int = 0


def annualised(funding: pd.DataFrame, lookback: int = LOOKBACK_H) -> pd.DataFrame:
    """Trailing mean hourly funding × hours per year. NaN until a full window exists."""
    return funding.rolling(lookback, min_periods=lookback).mean() * HOURS_PER_YEAR


def align(coins: Dict[str, CoinData]):
    """Union hourly index; prices forward-filled inside each coin's own range,
    funding left NaN where the venue has no settlement (no entry on NaN)."""
    # start from a real tz-aware index: an empty naive DatetimeIndex unioned with
    # tz-aware ones degrades to an object Index
    parts = [ix for c in coins.values() for ix in (c.funding.index, c.perp.index, c.spot.index)]
    idx = parts[0]
    for ix in parts[1:]:
        idx = idx.union(ix)
    idx = pd.DatetimeIndex(idx).sort_values()
    f = pd.DataFrame({k: c.funding.reindex(idx) for k, c in coins.items()})
    p = pd.DataFrame({k: c.perp.reindex(idx).ffill() for k, c in coins.items()})
    s = pd.DataFrame({k: c.spot.reindex(idx).ffill() for k, c in coins.items()})
    return idx, f, p, s


def simulate(coins: Dict[str, CoinData], spot_fee: float = SPOT_FEES["binanceus"],
             perp_fee: float = PERP_FEE, slippage: float = SLIPPAGE, initial: float = 1.0,
             enter: float = ENTER_ANN, exit_: float = EXIT_ANN, max_coins: int = MAX_COINS,
             max_hold: int = MAX_HOLD_H, swap_gap: float = 0.0, min_hold: int = 0) -> Result:
    idx, fund, perp, spot = align(coins)
    f_ann = annualised(fund)
    names = list(coins)
    F, P, S, A = fund.to_numpy(), perp.to_numpy(), spot.to_numpy(), f_ann.to_numpy()
    col = {n: j for j, n in enumerate(names)}

    cash = initial
    held: Dict[str, Position] = {}
    res = Result(equity=pd.Series(index=idx, dtype=float))
    eq = np.empty(len(idx))

    def mark(i: int) -> float:
        v = cash
        for pos in held.values():
            j = col[pos.coin]
            v += pos.qty_spot * S[i, j] + pos.qty_perp * (pos.perp_entry - P[i, j])
        return v

    def close(pos: Position, i: int, reason: str) -> None:
        nonlocal cash
        j = col[pos.coin]
        spot_val = pos.qty_spot * S[i, j]
        perp_val = pos.qty_perp * P[i, j]
        fee = spot_val * (spot_fee + slippage) + perp_val * (perp_fee + slippage)
        cash += spot_val + pos.qty_perp * (pos.perp_entry - P[i, j]) - fee
        pos.fees += fee
        res.fees += fee
        basis = pos.qty_spot * (S[i, j] - pos.spot_entry) - pos.qty_perp * (P[i, j] - pos.perp_entry)
        res.trades.append({"coin": pos.coin, "entry": idx[pos.entry_i], "exit": idx[i],
                           "hours": i - pos.entry_i, "funding": pos.funding, "basis": basis,
                           "fees": pos.fees, "pnl": pos.funding + basis - pos.fees, "reason": reason})

    for i in range(len(idx)):
        # 1. funding on open shorts at this hour's settlement
        for pos in held.values():
            j = col[pos.coin]
            rate = F[i, j]
            if np.isnan(rate):
                continue
            credit = rate * pos.qty_perp * P[i, j]
            cash += credit
            pos.funding += credit
            if credit >= 0:
                res.funding_received += credit
            else:
                res.funding_paid += -credit
        res.hours_in_position += len(held)

        # 2. exits: funding dried up, data gone, or held too long
        for name in list(held):
            j = col[name]
            a = A[i, j]
            pos = held[name]
            reason = None
            if np.isnan(a) or np.isnan(P[i, j]) or np.isnan(S[i, j]):
                reason = "no_data"
            elif a < exit_:
                reason = "funding_low"
            # As run and as pre-registered in code (research/ERRATA.md, 2026-10-28): the time stop
            # exits even when the coin still qualifies, then the same hour may re-enter it. The
            # PREREGISTRATION text says "without re-qualifying"; the forward books keep this rule.
            elif i - pos.entry_i >= max_hold:
                reason = "time"
            if reason:
                close(pos, i, reason)
                del held[name]

        # 3. entries: rank held + candidates by f_ann, keep the top max_coins
        cands = [n for n in names if n not in held and not np.isnan(A[i, col[n]])
                 and A[i, col[n]] > enter and not np.isnan(P[i, col[n]]) and not np.isnan(S[i, col[n]])]
        if cands:
            cands.sort(key=lambda n: -A[i, col[n]])
            ranked = list(held)
            free = max_coins - len(ranked)
            ranked += cands[:free]          # a free slot takes any qualifying candidate
            # swaps: the weakest held coin goes only if the candidate clears the gap and
            # the held coin has been held long enough (#12; gap 0 / hold 0 is #11)
            for cand in cands[free:]:
                swappable = [n for n in ranked if n in held and i - held[n].entry_i >= min_hold]
                if not swappable:
                    break
                weakest = min(swappable, key=lambda n: A[i, col[n]])
                if A[i, col[cand]] - A[i, col[weakest]] < max(swap_gap, 1e-12):
                    break
                close(held[weakest], i, "ranked_out")
                del held[weakest]
                ranked[ranked.index(weakest)] = cand
            equity_now = mark(i)
            n_slots = len(ranked)
            for name in ranked:
                if name in held:
                    continue
                j = col[name]
                notional = equity_now / (2 * n_slots)
                fee = notional * (spot_fee + slippage) + notional * (perp_fee + slippage)
                cash -= notional + fee
                res.fees += fee
                held[name] = Position(name, i, notional / S[i, j], notional / P[i, j],
                                      P[i, j], S[i, j], fees=fee)
        eq[i] = mark(i)

    for pos in list(held.values()):
        close(pos, len(idx) - 1, "end")
    held.clear()
    if len(idx):
        eq[-1] = mark(len(idx) - 1)     # the end-of-run exits pay their fees too
    res.equity = pd.Series(eq, index=idx)
    return res


def sharpe_of(eq: pd.Series, periods_per_year: float) -> float:
    r = eq.pct_change().dropna()
    return float(r.mean() / r.std() * np.sqrt(periods_per_year)) if len(r) > 1 and r.std() > 0 else 0.0


def daily_sharpe(eq: pd.Series) -> float:
    """Sharpe of the end-of-day equity, annualised by 365. Reported beside the
    pre-registered hourly Sharpe: hourly marks of a hedge carry two-venue basis
    noise that mean-reverts within hours (lag-1 autocorrelation about -0.5), so
    the hourly figure is far below the daily one. The criterion stays hourly."""
    eq = eq.dropna()
    if len(eq) < 3 or not isinstance(eq.index, pd.DatetimeIndex):
        return 0.0
    return sharpe_of(eq.resample("1D").last().dropna(), 365.0)


def metrics(res: Result) -> dict:
    eq = res.equity.dropna()
    if len(eq) < 2:
        return {"ann_return": 0.0, "max_dd": 0.0, "sharpe": 0.0, "sharpe_daily": 0.0, "paid_ratio": 0.0,
                "hours": 0}
    years = len(eq) / HOURS_PER_YEAR
    sharpe = sharpe_of(eq, HOURS_PER_YEAR)
    dd = (eq / eq.cummax() - 1).min()
    paid_ratio = res.funding_paid / res.funding_received if res.funding_received else float("inf")
    return {
        "ann_return": float((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1),
        "max_dd": float(-dd),
        "sharpe": sharpe,
        "sharpe_daily": daily_sharpe(eq),
        "paid_ratio": float(paid_ratio),
        "hours": len(eq),
        "trades": len(res.trades),
        "funding_received": res.funding_received,
        "funding_paid": res.funding_paid,
        "fees": res.fees,
        "hours_in_position": res.hours_in_position,
        "final": float(eq.iloc[-1]),
    }


def evaluate(coins: Dict[str, CoinData], initial: float = 1.0, maker: bool = False,
             swap_gap: float = 0.0, min_hold: int = 0, perp_fee: Optional[float] = None) -> dict:
    """Both runs the criteria need: Binance.US spot fees and Kraken spot fees.
    `maker=True` is #12's execution assumption (filled at the close, no slippage).
    `perp_fee` replaces Hyperliquid's perp fee for another venue (#14)."""
    costs = (dict(perp_fee=MAKER["perp"], slippage=MAKER["slippage"]) if maker
             else dict(perp_fee=PERP_FEE, slippage=SLIPPAGE))
    if perp_fee is not None:
        costs["perp_fee"] = perp_fee
    spot = MAKER["spot"] if maker else SPOT_FEES
    rule = dict(swap_gap=swap_gap, min_hold=min_hold, initial=initial)
    base = simulate(coins, spot_fee=spot["binanceus"], **costs, **rule)
    kraken = simulate(coins, spot_fee=spot["kraken"], **costs, **rule)
    m = metrics(base)
    m["ann_return_kraken"] = metrics(kraken)["ann_return"]
    m["result"] = base
    m["result_kraken"] = kraken
    return m


def verdict(m: dict) -> List[dict]:
    rows = []
    for name, req, test in CRITERIA:
        rows.append({"criterion": name, "required": req, "met": bool(test(m))})
    return rows


def scan(ctxs: List[dict], top: int = 20) -> pd.DataFrame:
    """What the market is paying right now: hourly funding annualised, top by open interest."""
    df = pd.DataFrame(ctxs)
    if df.empty:
        return df
    df = df.sort_values("open_interest", ascending=False).head(top).copy()
    df["funding_ann"] = df["funding"] * HOURS_PER_YEAR
    df["open_interest_m"] = df["open_interest"] / 1e6
    df["day_volume_m"] = df["day_volume"] / 1e6
    return df[["coin", "mark", "funding_ann", "open_interest_m", "day_volume_m"]].reset_index(drop=True)


def from_frames(funding: pd.DataFrame, perp: pd.DataFrame, spot: pd.DataFrame,
                perp_from_spot_before_candles: bool = False) -> Optional[CoinData]:
    """Build CoinData from the CSV frames the fetch stage writes. Returns None
    when the coin has less than the minimum funding history.

    Hyperliquid serves only its last 5000 candles per interval, so hourly perp
    closes cover about 200 days while funding goes back to 2023. By default the
    simulation runs only where all three series exist. With
    `perp_from_spot_before_candles` the perp close is taken as the spot close
    before the candles begin, which marks the basis at zero there: an
    information-only view of the funding income, not a test of the basis risk."""
    if len(funding) < MIN_HISTORY_H:
        return None
    f = pd.Series(funding["funding"].to_numpy(),
                  index=pd.to_datetime(funding["ts"], unit="s", utc=True)).sort_index()
    f = f[~f.index.duplicated()]

    def closes(df: pd.DataFrame) -> pd.Series:
        s = pd.Series(df["close"].to_numpy(), index=pd.to_datetime(df["time"], utc=True)).sort_index()
        return s[~s.index.duplicated()]

    s = closes(spot)
    p = closes(perp) if len(perp) else pd.Series(dtype=float)
    if perp_from_spot_before_candles:
        before = s[s.index < p.index.min()] if len(p) else s
        p = pd.concat([before, p]).sort_index()
    # the simulation only trusts hours where every series has a value
    common = f.index.intersection(p.index).intersection(s.index)
    return CoinData(funding=f.reindex(common), perp=p.reindex(common), spot=s.reindex(common))

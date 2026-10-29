"""#38's forward test (research/FORWARD_SHORTSPAY.md): does the price fall in the 30
minutes after a Binance settlement where shorts pay hard? #33's measure (espero/fillcost.py)
at 00:00, 08:00 and 16:00 UTC, on #24's recorded bars and Binance's funding archive (the
reader #32 uses). Nothing trades; the running numbers decide nothing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional, Sequence

import pandas as pd

from . import fillcost, fundsplit, liq, lows, lowsfwd
from .levetf import welch
from .liq import clustered
from .xs import UNIVERSE

FORWARD_FROM, FORWARD_TO = "2026-10-30", "2027-03-31"
HALF = "2027-01-01"
HOURS = (0, 8, 16)
LEG_HURDLE = 0.0018
LEDGER = "settle_fwd.csv"


def ledger(bars_data: Path = lowsfwd.DATA, funding_data: Path = fundsplit.DATA, coins: Sequence[str] = UNIVERSE,
           now: Optional[pd.Timestamp] = None, get: Optional[Callable] = None) -> pd.DataFrame:
    """Every 00/08/16 UTC settlement in the window with its bucket and drift, per coin."""
    out = []
    for c in coins:
        sym = liq.symbol("binance-futures", c)
        files = sorted((Path(bars_data) / sym).glob("*.zip"))
        if not files:
            continue
        fund = fundsplit.rates(sym, funding_data, now, get or fundsplit._get)
        if fund.empty:
            continue
        fund = fund.assign(ts=fund["ts"] // 60 * 60).rename(columns={"rate": "rate8"})
        b = lows.bars(pd.concat([lowsfwd.read(f.read_bytes()) for f in files], ignore_index=True))
        for h in HOURS:
            ev = fillcost.events(b, fund, FORWARD_FROM, FORWARD_TO, hour=h, mondays=False)
            out.append(ev.assign(coin=c, hour=h))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=fillcost.COLUMNS + ["coin", "hour"])


def criteria(ev: pd.DataFrame) -> List[dict]:
    sp, nm = ev[ev["bucket"] == "shorts pay"], ev[ev["bucket"] == "normal"]
    c1 = clustered(fillcost.by_day(sp))
    c2 = welch(fillcost.by_day(sp), fillcost.by_day(nm))
    h1 = clustered(fillcost.by_day(sp[sp["day"] < HALF]))
    h2 = clustered(fillcost.by_day(sp[sp["day"] >= HALF]))
    bps = lambda x: f"{1e4 * x:+.1f} bps"  # noqa: E731
    return [
        {"criterion": "the fall: shorts-paying settlements' mean m30 < 0, t <= -2",
         "actual": f"{bps(c1['mean'])}, t {c1['t']:.2f}, {len(sp)} settlements on {c1['n']} days",
         "met": c1["mean"] < 0 and c1["t"] <= -2},
        {"criterion": "only when shorts pay: below the normal settlements' mean",
         "actual": f"{bps(c2['diff'])}, t {c2['t']:.2f}", "met": c2["diff"] < 0},
        {"criterion": "not one stretch: < 0 in each half",
         "actual": f"{bps(h1['mean'])} (Oct-Dec), {bps(h2['mean'])} (Jan-Mar)",
         "met": h1["mean"] < 0 and h2["mean"] < 0},
        {"criterion": "it pays: the paper short above 18 bps, t > 2",
         "actual": f"{bps(-c1['mean'])}, t {-c1['t']:.2f}",
         "met": -c1["mean"] > LEG_HURDLE and -c1["t"] > 2},
    ]


def run(state_dir: Path, bars_data: Path = lowsfwd.DATA, funding_data: Path = fundsplit.DATA,
        get: Optional[Callable] = None) -> dict:
    ev = ledger(bars_data, funding_data, get=get)
    ev.to_csv(Path(state_dir) / LEDGER, index=False, float_format="%.8g")
    sp = ev[ev["bucket"] == "shorts pay"].dropna(subset=["m30"])
    note = f"mark: {len(sp)} shorts-paying settlements of {int(ev['m30'].notna().sum())}"
    if len(sp):
        note += f" ({1e4 * float(fillcost.by_day(sp).mean()):+.1f} bps in 30 min; decides nothing)"
    return {"note": note, "equity": None}

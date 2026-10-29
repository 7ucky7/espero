"""2x funds push small coins into the US close (#34, research/PREREGISTRATION_LEVPUSH.md).

#28's rule (espero/levetf.py), unchanged, in two parts. A placebo, now: coins whose US
2x funds hold only $1-3M (ADA, XLM, LINK, AVAX) must show no push into 16:00 ET. Then
forward: SOL and XRP, whose funds are large, must keep pushing on data from 2026-10-30.
The forward rows are the ones #29's daily step builds (postclose_days.csv).
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import pandas as pd

from . import levetf as lv
from .liq import clustered

PLACEBO = {"ADA": "2026-04-01", "XLM": "2026-04-01", "LINK": "2026-04-01", "AVAX": "2026-05-15"}
PLACEBO_LAST = "2026-10-27"
FLAT = 0.0003                 # criterion 1: the placebo's push stays under 3 bps
PUSHED = ("SOL", "XRP")
FORWARD_FROM, FORWARD_TO = "2026-10-30", "2027-03-31"
LEDGER_IN = "postclose_days.csv"


def placebo_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """The placebo coins' rows from their fund's first day to the end of the cached bars."""
    keep = [(rows["coin"] == c) & (rows["date"] >= d) & (rows["date"] <= PLACEBO_LAST) for c, d in PLACEBO.items()]
    return rows[pd.concat(keep, axis=1).any(axis=1)] if keep else rows.iloc[:0]


def forward_rows(rows: pd.DataFrame) -> pd.DataFrame:
    return rows[rows["coin"].isin(PUSHED) & (rows["date"] >= FORWARD_FROM) & (rows["date"] <= FORWARD_TO)]


def criteria(placebo: pd.DataFrame, forward: Optional[pd.DataFrame] = None) -> List[dict]:
    """Criterion 1 on the placebo rows; 2 and 3 on the forward rows (not met while there are none)."""
    p = clustered(lv.per_date(placebo[placebo["kind"] == "trading"]))
    fw = forward if forward is not None else placebo.iloc[:0]
    tr = lv.per_date(fw[fw["kind"] == "trading"])
    f = clustered(tr)
    d = lv.welch(tr, lv.per_date(fw[fw["kind"] == "closed"]))
    bps = lambda x: f"{1e4 * x:+.2f} bps"  # noqa: E731
    return [
        {"criterion": "the placebo is flat: coins with $1-3M 2x funds, mean y < 3 bps",
         "actual": f"{bps(p['mean'])}, t {p['t']:.2f}, {p['n']} days", "met": p["mean"] < FLAT},
        {"criterion": "the push continues: SOL and XRP forward, mean y > 0, t >= 2",
         "actual": f"{bps(f['mean'])}, t {f['t']:.2f}, {f['n']} days", "met": f["mean"] > 0 and f["t"] >= 2},
        {"criterion": "only when the funds trade: above the closed-day mean",
         "actual": f"{bps(d['diff'])}, t {d['t']:.2f}", "met": d["diff"] > 0},
    ]


def verdict(rows: List[dict]) -> str:
    return "PASS" if all(r["met"] for r in rows) else "FAIL"


def run(state_dir: Path) -> dict:
    """SOL and XRP's running push, from #29's ledger (it decides nothing)."""
    path = Path(state_dir) / LEDGER_IN
    rows = pd.read_csv(path) if path.exists() and path.stat().st_size > 1 else pd.DataFrame()
    if rows.empty or "y" not in rows:
        return {"note": "mark: 0 trading days", "equity": None}
    tr = lv.per_date(forward_rows(rows).query("kind == 'trading'"))
    note = f"mark: {len(tr)} trading days"
    if len(tr):
        note += f" (SOL+XRP into the close {1e4 * float(tr.mean()):+.1f} bps; decides nothing)"
    return {"note": note, "equity": None}

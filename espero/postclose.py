"""#29's forward paper test (research/FORWARD_POSTCLOSE.md): does the US session's
move reverse after the 16:00 ET close? It reads the 5-minute files #24's job records
(espero/lowsfwd.py) and rebuilds #28's rows (espero/levetf.py, unchanged) on the
window. Nothing trades, and the running numbers decide nothing.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Sequence

import pandas as pd

from . import levetf as lv
from . import liq, lows, lowsfwd
from .liq import clustered

FORWARD_FROM = "2026-10-30"
FORWARD_TO = "2027-03-31"
HALF = "2027-01-01"
COINS = ("BTC", "ETH", "SOL", "XRP")
LEDGER = "postclose_days.csv"
COLUMNS = ["date", "coin", "kind", "r", "y", "r_post15", "post15", "r_post60", "post60"]


def rows(data: Path = lowsfwd.DATA, coins: Sequence[str] = COINS) -> pd.DataFrame:
    """#28's rows for each recorded coin, on the window's dates that have bars."""
    out = []
    for c in coins:
        files = sorted((Path(data) / liq.symbol("binance-futures", c)).glob("*.zip"))
        if not files:
            continue
        b = lows.bars(pd.concat([lowsfwd.read(f.read_bytes()) for f in files], ignore_index=True))
        last = min(FORWARD_TO, pd.to_datetime(int(b.index.max()), unit="s", utc=True).strftime("%Y-%m-%d"))
        if last >= FORWARD_FROM:
            out.append(lv.rows(b, c, FORWARD_FROM, last))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=COLUMNS)


def criteria(df: pd.DataFrame) -> List[dict]:
    """The four criteria of FORWARD_POSTCLOSE.md on BTC and ETH, each date's mean one observation."""
    df = df[df["coin"].isin(lv.PRIMARY)]
    tr, cl = df[df["kind"] == "trading"], df[df["kind"] == "closed"]
    days = lv.per_date(tr, "post15")
    c1 = clustered(days)
    c2 = lv.welch(days, lv.per_date(cl, "post15"))
    h1, h2 = clustered(days[days.index < HALF]), clustered(days[days.index >= HALF])
    fade = clustered(-lv.per_date(tr[tr["r_post15"].abs() >= lv.BIG_R], "post15"))
    bps = lambda x: f"{1e4 * x:+.1f} bps"  # noqa: E731
    return [
        {"criterion": "the reversal holds: trading days, mean post15 < 0, t <= -3",
         "actual": f"{bps(c1['mean'])}, t {c1['t']:.2f}, {c1['n']} days",
         "met": c1["mean"] < 0 and c1["t"] <= -lv.T_HURDLE},
        {"criterion": "only when the US trades: below the closed-day mean",
         "actual": f"{bps(c2['diff'])}, t {c2['t']:.2f}",
         "met": c2["diff"] < 0},
        {"criterion": "not one stretch: mean post15 < 0 in each half",
         "actual": f"{bps(h1['mean'])} ({h1['n']} days), {bps(h2['mean'])} ({h2['n']} days)",
         "met": h1["mean"] < 0 and h2["mean"] < 0},
        {"criterion": "it pays: |r| >= 2% days, fading 16:00 -> 16:15 earns > 18 bps, t > 2",
         "actual": f"{bps(fade['mean'])}, t {fade['t']:.2f}, {fade['n']} days",
         "met": fade["mean"] > lv.LEG_HURDLE and fade["t"] > lv.LEG_T},
    ]


def run(state_dir: Path, data: Path = lowsfwd.DATA) -> dict:
    """Rebuild the ledger from the recorded files and say where it stands (it decides nothing)."""
    df = rows(data)
    df.to_csv(Path(state_dir) / LEDGER, index=False, float_format="%.8g")
    days = lv.per_date(df[df["coin"].isin(lv.PRIMARY) & (df["kind"] == "trading")], "post15")
    note = f"mark: {len(days)} trading days"
    if len(days):
        note += f" (BTC+ETH after the close {1e4 * float(days.mean()):+.1f} bps in 15 min; decides nothing)"
    return {"note": note, "equity": None}

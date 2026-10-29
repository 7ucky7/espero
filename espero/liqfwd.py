"""#22's forward paper test (research/FORWARD_LIQ.md): record aggr's hourly bars
day by day, and rebuild the paper ledger of long-liquidation spikes bought at the
spike hour's close and sold 4 hours later. Nothing trades.

`run` is the daily job's step: it records every complete UTC day not yet saved
(up to yesterday), then rewrites `liqfwd_trades.csv` in the state directory.
The ledger is rebuilt from the recorded bars each time, so it can always be
checked against them. Its running numbers decide nothing (the evaluation is
once, after the end date).
"""
from __future__ import annotations

import gzip
import io
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from . import aggr, liqspike

FORWARD_FROM = pd.Timestamp("2026-10-30 00:00", tz="UTC")
FORWARD_TO = pd.Timestamp("2027-03-31 23:00", tz="UTC")
HOLD_H = 4
DATA = Path(__file__).resolve().parents[1] / "data" / "aggr"
COST_HL = 0.0009


def day_path(data: Path, day: pd.Timestamp) -> Path:
    return data / "forward" / f"{day:%Y-%m-%d}.csv.gz"


def record(data: Path = DATA, now: Optional[pd.Timestamp] = None,
           fetch: Callable = aggr.fetch, first: pd.Timestamp = FORWARD_FROM) -> List[str]:
    """Save each complete UTC day from `first` to yesterday that is not on disk yet."""
    now = pd.Timestamp.now(tz="UTC") if now is None else now
    saved = []
    day = first.normalize()
    while day + pd.Timedelta(days=1) <= now.normalize() and day <= FORWARD_TO.normalize() + pd.Timedelta(days=1):
        path = day_path(data, day)
        if not path.exists():
            df = fetch(day, day + pd.Timedelta(days=1))
            path.parent.mkdir(parents=True, exist_ok=True)
            buf = io.StringIO()
            df.sort_values(["market", "time"]).to_csv(buf, index=False)
            path.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))
            saved.append(day.strftime("%Y-%m-%d"))
        day += pd.Timedelta(days=1)
    return saved


def load(data: Path = DATA) -> pd.DataFrame:
    """Warm-up (explored and sealed months) plus every recorded forward day."""
    files = sorted((data / "explore").glob("*.csv.gz")) + sorted((data / "holdout").glob("*.csv.gz")) + \
        sorted((data / "forward").glob("*.csv.gz"))
    frames = [pd.read_csv(f) for f in files]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=aggr.COLUMNS)


def ledger(p: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Every long-liquidation spike in the forward window whose 4-hour exit is recorded."""
    rows = []
    for c, df in p.items():
        close = df["close"].to_numpy()
        for t in liqspike.spikes(df, "long", FORWARD_FROM, FORWARD_TO):
            i = df.index.get_loc(t)
            if i + HOLD_H >= len(df) or not (np.isfinite(close[i]) and np.isfinite(close[i + HOLD_H])):
                continue
            rows.append({"coin": c, "spike_hour": t, "day": t.strftime("%Y-%m-%d"),
                         "usd": float(df["long"].iat[i]), "entry": float(close[i]),
                         "exit": float(close[i + HOLD_H]), "ret": float(close[i + HOLD_H] / close[i] - 1)})
    return pd.DataFrame(rows, columns=["coin", "spike_hour", "day", "usd", "entry", "exit", "ret"])


def run(state_dir: Path, data: Path = DATA, now: Optional[pd.Timestamp] = None,
        fetch: Callable = aggr.fetch) -> dict:
    saved = record(data, now, fetch)
    led = ledger(aggr.panel(load(data)))
    led.to_csv(Path(state_dir) / "liqfwd_trades.csv", index=False, float_format="%.8g")
    days = led["day"].nunique()
    mean = float(led.groupby("day")["ret"].mean().mean()) if days else float("nan")
    note = f"mark: {len(led)} paper trades on {days} days"
    if days:
        note += f", mean {1e4 * mean:+.1f} bps a day (gross; decides nothing)"
    return {"note": note, "equity": None, "saved": saved}

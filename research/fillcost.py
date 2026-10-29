"""Hypothesis #33 — what the accounts' 00:00 UTC fills cost.

    python research/fillcost.py      # cached bars and funding only; downloads nothing

The measure and criteria are frozen in research/PREREGISTRATION_FILLCOST.md; this
script prints the pre-registered tables, and the verdict is written by hand into
RESULTS_FILLCOST.md.
"""
from __future__ import annotations

import gzip
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import List, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import fillcost as fc  # noqa: E402
from espero import liq as lq  # noqa: E402
from espero import lows as lw  # noqa: E402
from espero.liq import clustered  # noqa: E402
from espero.xs import UNIVERSE  # noqa: E402

DATA = ROOT / "data"
EVENTS = ROOT / "research" / "fillcost_events.csv.gz"
MONTHS = [m.strftime("%Y-%m") for m in pd.period_range("2020-01", "2026-09", freq="M").to_timestamp()]
DAYS = [d.strftime("%Y-%m-%d") for d in pd.date_range("2026-10-01", "2026-10-27")]
KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume",
              "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]


def first_file(*paths: Path) -> Optional[bytes]:
    for p in paths:
        if p.exists():
            return p.read_bytes()
    return None


def frame(blob: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        text = z.read(z.namelist()[0]).decode()
    header = text.split(",", 1)[0].strip() == "open_time"
    df = pd.read_csv(io.StringIO(text), header=0 if header else None)
    df.columns = KLINE_COLS
    return df


def coin(c: str):
    sym = lq.symbol("binance-futures", c)
    frames = []
    for m in MONTHS:
        blob = first_file(DATA / "lows" / sym / f"{m}.zip", DATA / "levetf" / sym / f"{m}.zip",
                          DATA / "bids" / sym / f"{m}.zip")
        if blob:
            frames.append(frame(blob))
    for d in DAYS:
        blob = first_file(DATA / "levetf" / sym / "daily" / f"{d}.zip", DATA / "bids" / sym / "daily" / f"{d}.zip")
        if blob:
            frames.append(frame(blob))
    fpath = DATA / "settle" / "funding" / f"{sym}.json"
    if not frames or not fpath.exists():
        return None
    b = lw.bars(pd.concat(frames, ignore_index=True))
    fund = fc.settlements(json.loads(fpath.read_text()))
    out = {"primary": fc.events(b, fund)}
    out["every day 00:00"] = fc.events(b, fund, mondays=False)
    out["every day 08:00"] = fc.events(b, fund, hour=8, mondays=False)
    out["every day 16:00"] = fc.events(b, fund, hour=16, mondays=False)
    return {k: v.assign(coin=c) for k, v in out.items()}


def bps(x: float) -> str:
    return f"{1e4 * x:+.2f} bps"


def line(name: str, ev: pd.DataFrame, col: str = "m30") -> str:
    c = clustered(fc.by_day(ev, col))
    return f"| {name} | {bps(c['mean'])} | {c['t']:.2f} | {c['n']} | {int(ev[col].notna().sum())} |"


def main() -> int:
    runs: dict = {}
    used: List[str] = []
    for c in UNIVERSE:
        out = coin(c)
        if out is None:
            continue
        used.append(c)
        for k, v in out.items():
            runs.setdefault(k, []).append(v)
    ev = {k: pd.concat(v, ignore_index=True) for k, v in runs.items()}
    p = ev["primary"]
    buf = io.StringIO()
    p.to_csv(buf, index=False, float_format="%.6g")
    EVENTS.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))
    print(f"coins: {len(used)} of {len(UNIVERSE)}; coin-Mondays: {len(p)} ({int(p['m30'].notna().sum())} with m30) "
          f"on {p['day'].nunique()} Mondays, {p['day'].min()} -> {p['day'].max()} -> {EVENTS.relative_to(ROOT)}")
    print("bucket shares:", (p["bucket"].value_counts(normalize=True).round(3)).to_dict())

    crit = fc.criteria(p)
    print("\n## criteria (each Monday's mean within a bucket one observation)\n")
    print("| # | criterion | actual | met |")
    print("|---|---|---|---|")
    for i, r in enumerate(crit, 1):
        print(f"| {i} | {r['criterion']} | {r['actual']} | {'yes' if r['met'] else '**no**'} |")
    print(f"\nverdict: {fc.verdict(crit)}")

    print("\n## information only\n")
    print("| set | mean | t | days | events |")
    print("|---|---|---|---|---|")
    for bkt in ("longs pay", "shorts pay", "normal"):
        g = p[p["bucket"] == bkt]
        for col in fc.HORIZONS:
            print(line(f"Mondays 00:00, {bkt}, {col}", g, col))
    for name in ("every day 00:00", "every day 08:00", "every day 16:00"):
        for bkt in ("longs pay", "shorts pay", "normal"):
            print(line(f"{name}, {bkt}, m30", ev[name][ev[name]["bucket"] == bkt]))
    print("\nby year, Mondays 00:00, m30 (bps):\n")
    print("| year | longs pay | shorts pay | normal |")
    print("|---|---|---|---|")
    for y, g in p.assign(year=p["day"].str[:4]).groupby("year"):
        cells = [bps(clustered(fc.by_day(g[g["bucket"] == b]))["mean"]) for b in ("longs pay", "shorts pay", "normal")]
        print(f"| {y} | " + " | ".join(cells) + " |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

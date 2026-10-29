"""Hypothesis #25 — breakdowns made of closing positions bounce more.

    python research/oi.py      # 5-minute bars from #20's cache; open interest downloaded into data/oi/

The rules and criteria are frozen in research/PREREGISTRATION_OI.md; the verdict
is written by hand into RESULTS_OI.md.
"""
from __future__ import annotations

import gzip
import importlib.util
import io
import json
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import liq as lq  # noqa: E402
from espero import lows as lw  # noqa: E402
from espero import oi as oim  # noqa: E402
from espero.xs import UNIVERSE  # noqa: E402

CACHE = ROOT / "data" / "oi"
EVENTS = ROOT / "research" / "oi_events.csv.gz"
URL = "https://data.binance.vision/data/futures/um/daily/metrics/{sym}/{sym}-metrics-{day}.zip"
WORKERS = 6


def lows_module():
    spec = importlib.util.spec_from_file_location("research_lows", ROOT / "research" / "lows.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RL = lows_module()


def metrics(sym: str, day: str) -> Optional[pd.DataFrame]:
    path = CACHE / sym / f"{day}.csv.gz"
    none = path.with_suffix("").with_suffix(".none")
    if none.exists():
        return None
    if not path.exists():
        blob = RL.get(URL.format(sym=sym, day=day))          # #20's downloader: retries, 404 is None
        path.parent.mkdir(parents=True, exist_ok=True)
        if blob is None:
            none.write_text("")
            return None
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            path.write_bytes(gzip.compress(z.read(z.namelist()[0]), mtime=0))
    return pd.read_csv(path)


def coin(c: str) -> Tuple[pd.DataFrame, dict]:
    sym = lq.symbol("binance-futures", c)
    frames = [f for f in (RL.month_frame(sym, m) for m in RL.MONTHS if m >= "2020-12") if f is not None]
    if not frames:
        return pd.DataFrame(), {"coin": c, "status": "no bars"}
    b = lw.bars(pd.concat(frames, ignore_index=True))
    ev = lw.events(b, "down", lw.excluded_days(), first=oim.FIRST_DAY, last=oim.LAST_DAY)
    if ev.empty:
        return pd.DataFrame(), {"coin": c, "status": "no events"}
    days = sorted(set(ev["day"]) | {(pd.Timestamp(d) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                                    for d in ev["day"]})
    parts = [m for m in (metrics(sym, d) for d in days) if m is not None]
    oi = oim.series(pd.concat(parts, ignore_index=True)) if parts else pd.Series(dtype=float)
    ev = ev.assign(coin=c, oi_drop=oim.drop(ev, oi))
    return ev, {"coin": c, "status": "ok", "events": len(ev), "measured": int(np.isfinite(ev["oi_drop"]).sum()),
                "oi_days_missing": len(days) - len(parts)}


def bps(x: float) -> str:
    return f"{1e4 * x:+.1f} bps"


def main() -> int:
    pd.set_option("display.width", 200)
    print(f"{len(UNIVERSE)} coins: #20's down-breaks {oim.FIRST_DAY} -> {oim.LAST_DAY}, open interest from Binance's "
          f"metrics archive (cached in data/oi/) ...", flush=True)
    out: List[pd.DataFrame] = []
    metas = []
    with ThreadPoolExecutor(WORKERS) as ex:
        for k, (ev, meta) in enumerate(ex.map(coin, UNIVERSE), 1):
            metas.append(meta)
            if len(ev):
                out.append(ev)
            print(f"  {k}/{len(UNIVERSE)} {meta}", flush=True)
    ev = pd.concat(out, ignore_index=True)
    buf = io.StringIO()
    ev.to_csv(buf, index=False, float_format="%.6g")
    EVENTS.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))
    (ROOT / "research" / "oi_manifest.json").write_text(json.dumps(metas, indent=1))

    m = ev[np.isfinite(ev["oi_drop"])]
    print("\n## data\n")
    print(f"down-breaks: {len(ev)}; with an open-interest drop measured: {len(m)} on {m['day'].nunique()} days; "
          f"median oi_drop {100 * m['oi_drop'].median():+.2f}%, top decile from {100 * m['oi_drop'].quantile(0.9):+.2f}%")
    rows = oim.criteria(ev)
    print("\n## criteria (within-day terciles of oi_drop; r60 = 1h long return from the next open)\n")
    print("| # | criterion | actual | met |")
    print("|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        print(f"| {i} | {r['criterion']} | {r['actual']} | {'yes' if r['met'] else '**no**'} |")
    print(f"\nverdict: {oim.verdict(rows)}")

    print("\n## information only\n")
    for name, col, y, within in (("4-hour outcome", "oi_drop", "r240", True), ("global terciles", "oi_drop", "r60", False)):
        c = lq.clustered(lq.day_diff(ev, col, y, within))
        print(f"{name}: D {bps(c['mean'])}, t {c['t']:.2f}, {c['n']} days")
    use = lq.usable(ev, "oi_drop", "r60")
    t = lq.tag(use, "oi_drop")
    for g in ("forced", "middle", "organic"):
        s = use[t == g]
        c = lq.clustered(s["r60"].groupby(s["day"]).mean())
        c4 = lq.clustered(s["r240"].groupby(s["day"]).mean())
        print(f"  {g:8s}: 1h {bps(c['mean'])} (t {c['t']:.2f}), 4h {bps(c4['mean'])} (t {c4['t']:.2f}), {len(s)} events")
    per = lq.day_diff(ev, "oi_drop", "r60")
    print("\nD by year:")
    for y, g in per.groupby(per.index.str[:4]):
        c = lq.clustered(g)
        print(f"  {y}: {bps(c['mean'])} (t {c['t']:.2f}, {c['n']} days)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

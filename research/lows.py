"""Hypothesis #20 — new 4-hour lows on volume bounce.

    python research/lows.py          # downloads Binance's monthly 5-minute archive (cached in data/lows/)

The rules and criteria are frozen in research/PREREGISTRATION_LOWS.md; this
script prints the pre-registered tables, and the verdict is written by hand into
RESULTS_LOWS.md.
"""
from __future__ import annotations

import gzip
import http.client
import io
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import liq as lq  # noqa: E402
from espero import lows as lw  # noqa: E402
from espero.xs import UNIVERSE  # noqa: E402

CACHE = ROOT / "data" / "lows"
EVENTS = ROOT / "research" / "lows_events.csv.gz"
MANIFEST = ROOT / "research" / "lows_manifest.json"
MONTHS = [f"{y}-{m:02d}" for y in range(2019, 2027) for m in range(1, 13) if "2019-12" <= f"{y}-{m:02d}" <= "2026-03"]
URL = "https://data.binance.vision/data/futures/um/monthly/klines/{sym}/5m/{sym}-5m-{month}.zip"
KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume",
              "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]
WORKERS = 6
COST_BINANCE_US = 0.0004
COST_HL = 0.0009


def get(url: str, tries: int = 4) -> Optional[bytes]:
    """The body, or None for a 404 (no such month). Anything else is retried, then raised."""
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "espero"}),
                                        timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code in (401, 403) or k == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
            if k == tries - 1:
                raise
        time.sleep(1.5 * (k + 1))
    return None


def month_frame(sym: str, month: str) -> Optional[pd.DataFrame]:
    path = CACHE / sym / f"{month}.zip"
    none = path.with_suffix(".none")
    if none.exists():
        return None
    if path.exists():
        blob = path.read_bytes()
    else:
        blob = get(URL.format(sym=sym, month=month))
        path.parent.mkdir(parents=True, exist_ok=True)
        if blob is None:
            none.write_text("")
            return None
        path.write_bytes(blob)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        text = z.read(z.namelist()[0]).decode()
    header = text.split(",", 1)[0].strip() == "open_time"
    df = pd.read_csv(io.StringIO(text), header=0 if header else None)
    df.columns = KLINE_COLS
    return df


def coin(c: str) -> Tuple[pd.DataFrame, dict]:
    sym = lq.symbol("binance-futures", c)
    frames, missing = [], 0
    for m in MONTHS:
        df = month_frame(sym, m)
        if df is None:
            missing += 1
        else:
            frames.append(df)
    meta = {"coin": c, "symbol": sym, "months_missing": missing}
    if not frames:
        meta["status"] = "no bars"
        return pd.DataFrame(), meta
    b = lw.bars(pd.concat(frames, ignore_index=True))
    skip = lw.excluded_days()
    ev = pd.concat([lw.events(b, "down", skip), lw.events(b, "up", skip)], ignore_index=True)
    meta["status"] = "ok"
    return ev.assign(coin=c), meta


def bps(x: float) -> str:
    return f"{1e4 * x:+.1f} bps"


def row(name: str, s: pd.Series) -> str:
    c = lq.clustered(s)
    return f"| {name} | {bps(c['mean'])} | {c['t']:.2f} | {c['n']} |"


def report(ev: pd.DataFrame, metas: List[dict]) -> None:
    down, up = ev[ev["direction"] == "down"], ev[ev["direction"] == "up"]
    print("\n## data\n")
    print(f"coins with bars: {sum(1 for m in metas if m['status'] == 'ok')} of {len(metas)}; "
          f"months missing in all: {sum(m['months_missing'] for m in metas)}")
    print(f"breakdowns: {len(down)} on {down['day'].nunique()} days; breakouts (contrast): {len(up)}; "
          f"days {ev['day'].min()} -> {ev['day'].max()}, #18's days and their neighbours left out")

    rows = lw.criteria(ev)
    print("\n## criteria (long bought at the next 5-minute open after a new 4-hour low on volume)\n")
    print("| # | criterion | actual | met |")
    print("|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        print(f"| {i} | {r['criterion']} | {r['actual']} | {'yes' if r['met'] else '**no**'} |")
    print(f"\nverdict: {lw.verdict(rows)}")

    print("\n## information only\n")
    print("| variant | mean | t | days |")
    print("|---|---|---|---|")
    print(row("breakdowns, 4h", lw.by_day(down["r240"], down["day"])))
    print(row("breakouts (#10's trigger), 1h long", lw.by_day(up["r60"], up["day"])))
    print(row("breakouts, 15 minutes", lw.by_day(up["r15"], up["day"])))
    yr = down.assign(year=down["day"].str[:4])
    for y, g in yr.groupby("year"):
        print(row(f"breakdowns {y}, 1h", lw.by_day(g["r60"], g["day"])))
    c = lq.clustered(lw.by_day(down["r60"], down["day"]))
    print(f"\nbreakdowns, 1h: {bps(c['mean'])} gross; net Binance.US {bps(c['mean'] - COST_BINANCE_US)}, "
          f"Hyperliquid {bps(c['mean'] - COST_HL)}")
    print("\nbreakdowns' 1h mean by coin (bps):")
    print((down.assign(x=1e4 * down["r60"]).groupby("coin")["x"].agg(["size", "mean"]).round(1)
           .sort_values("mean").to_string()))


def main() -> int:
    pd.set_option("display.width", 200)
    print(f"{len(UNIVERSE)} coins x {len(MONTHS)} months of 5-minute bars, cached in {CACHE.relative_to(ROOT)}/ ...",
          flush=True)
    out, metas = [], []
    with ThreadPoolExecutor(WORKERS) as ex:
        for k, (ev, meta) in enumerate(ex.map(coin, UNIVERSE), 1):
            metas.append(meta)
            if len(ev):
                out.append(ev)
            print(f"  {k}/{len(UNIVERSE)} {meta['coin']}: {meta['status']}, {len(ev)} events", flush=True)
    ev = pd.concat(out, ignore_index=True).sort_values(["ts", "coin"]).reset_index(drop=True)
    buf = io.StringIO()
    ev.to_csv(buf, index=False, float_format="%.6g")
    EVENTS.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))
    MANIFEST.write_text(json.dumps({"months": MONTHS, "coins": metas, "events": len(ev)}, indent=1))
    print(f"-> {EVENTS.relative_to(ROOT)} ({len(ev)} events), {MANIFEST.relative_to(ROOT)}")
    report(ev, metas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

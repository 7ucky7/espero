"""Hypothesis #18 — liquidations sort breakouts into forced and organic.

    python research/liq.py              # downloads the 82 free days (cached in data/liq/), then the tables

The rules and the pass criteria are frozen in research/PREREGISTRATION_LIQ.md.
This script prints the pre-registered tables; the verdict is written by hand
into RESULTS_LIQ.md.
"""
from __future__ import annotations

import datetime as dt
import gzip
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

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import liq as lq  # noqa: E402
from espero.xs import UNIVERSE  # noqa: E402

CACHE = ROOT / "data" / "liq"
EVENTS = ROOT / "research" / "liq_events.csv"
MANIFEST = ROOT / "research" / "liq_manifest.json"
DAYS = [dt.date(y, m, 1) for y in range(2020, 2027) for m in range(1, 13)
        if dt.date(2020, 1, 1) <= dt.date(y, m, 1) <= dt.date(2026, 10, 1)]
KLINE_URL = "https://data.binance.vision/data/futures/um/daily/klines/{sym}/1m/{sym}-1m-{day}.zip"
LIQ_URL = "https://datasets.tardis.dev/v1/{venue}/liquidations/{day:%Y/%m/%d}/{sym}.csv.gz"
KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume",
              "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]
WORKERS = 6
COST_BINANCE_US = 0.0004
COST_HL = 0.0009


def get(url: str, tries: int = 4) -> Optional[bytes]:
    """The body, or None for a 404 (no such market that day). Anything else is retried,
    then raised: the run stops rather than guess."""
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "espero"}),
                                        timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code in (401, 403) or k == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if k == tries - 1:
                raise
        time.sleep(1.5 * (k + 1))
    return None


def read_klines(blob: bytes) -> pd.DataFrame:
    """One archive zip -> the 12 columns; older files have no header row."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        text = z.read(z.namelist()[0]).decode()
    header = text.split(",", 1)[0].strip() == "open_time"
    df = pd.read_csv(io.StringIO(text), header=0 if header else None)
    df.columns = KLINE_COLS
    return df


def coin_day(coin: str, day: dt.date) -> Tuple[pd.DataFrame, dict]:
    """Download (or reuse) one coin-day and return its events and what was missing."""
    sym = lq.symbol("binance-futures", coin)
    folder = CACHE / day.isoformat()
    bars_path, liq_path, meta_path = folder / f"{coin}_bars.csv.gz", folder / f"{coin}_liq.csv.gz", \
        folder / f"{coin}.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if not meta["bars"]:
            return pd.DataFrame(), meta
        bars = pd.read_csv(bars_path, index_col="ts")
        liq = pd.read_csv(liq_path)
    else:
        frames = []
        for d in (day - dt.timedelta(days=1), day, day + dt.timedelta(days=1)):
            blob = get(KLINE_URL.format(sym=sym, day=d.isoformat()))
            if blob is None and d == day:
                frames = []
                break
            if blob is not None:
                frames.append(read_klines(blob))
        meta = {"coin": coin, "day": day.isoformat(), "bars": bool(frames), "venues": {}}
        folder.mkdir(parents=True, exist_ok=True)
        if not frames:
            meta_path.write_text(json.dumps(meta))
            return pd.DataFrame(), meta
        bars = lq.bars_5m(pd.concat(frames, ignore_index=True))
        parts = []
        for venue in lq.VENUES:
            blob = get(LIQ_URL.format(venue=venue, day=day, sym=lq.symbol(venue, coin)))
            meta["venues"][venue] = "no market" if blob is None else "ok"
            if blob is not None:
                text = gzip.decompress(blob) if blob else b""
                rows = pd.read_csv(io.BytesIO(text)) if text.strip() else \
                    pd.DataFrame(columns=["timestamp", "side", "price", "amount"])
                meta["venues"][venue] = f"ok, {len(rows)} rows"
                parts.append(lq.liquidations(rows, venue))
        liq = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["ts", "side", "usd", "venue"])
        bars.to_csv(bars_path)
        liq.to_csv(liq_path, index=False)
        meta_path.write_text(json.dumps(meta))
    start = int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp())
    ev = lq.events(bars, liq, start)
    return ev.assign(coin=coin, day=day.isoformat()), meta


def build() -> Tuple[pd.DataFrame, List[dict]]:
    jobs = [(c, d) for d in DAYS for c in UNIVERSE]
    print(f"{len(DAYS)} days x {len(UNIVERSE)} coins = {len(jobs)} coin-days "
          f"({DAYS[0]} .. {DAYS[-1]}), cached in {CACHE.relative_to(ROOT)}/ ...", flush=True)
    out, metas = [], []
    with ThreadPoolExecutor(WORKERS) as ex:
        for k, (ev, meta) in enumerate(ex.map(lambda j: coin_day(*j), jobs), 1):
            metas.append(meta)
            if len(ev):
                out.append(ev)
            if k % 250 == 0:
                print(f"  {k}/{len(jobs)} coin-days", flush=True)
    return (pd.concat(out, ignore_index=True) if out else pd.DataFrame()), metas


def bps(x: float) -> str:
    return f"{1e4 * x:+.1f} bps"


def report(ev: pd.DataFrame, metas: List[dict]) -> None:
    have = [m for m in metas if m["bars"]]
    print("\n## data\n")
    print(f"coin-days with Binance bars: {len(have)} of {len(metas)}")
    for v in lq.VENUES:
        n = sum(1 for m in have if str(m["venues"].get(v, "")).startswith("ok"))
        print(f"  with a {v} liquidation file: {n}")
    use = lq.usable(ev)
    print(f"events: {len(ev)} ({int((ev['direction'] == 1).sum())} up, {int((ev['direction'] == -1).sum())} down); "
          f"usable (s and y present, day with >= {lq.MIN_DAY_EVENTS}): {len(use)} on {use['day'].nunique()} days")
    print(f"events with no liquidation at all in the hour before: {(ev['liq_total'] == 0).mean():.1%}; "
          f"with none on the break's side: {(ev['forced'] == 0).mean():.1%}")

    rows = lq.criteria(ev)
    print("\n## criteria (y = 1-hour return in the break's direction, within-day terciles of s)\n")
    print("| # | criterion | actual | met |")
    print("|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        print(f"| {i} | {r['criterion']} | {r['actual']} | {'yes' if r['met'] else '**no**'} |")
    print(f"\nverdict: {lq.verdict(rows)}")

    print("\n## information only\n")
    print("| variant | mean D | t | days |")
    print("|---|---|---|---|")
    variants = [("Binance liquidations only", "s_binance", "y60", True),
                ("Bybit liquidations only", "s_bybit", "y60", True),
                ("15-minute window", "s15", "y60", True),
                ("15-minute horizon", "s", "y15", True),
                ("4-hour horizon", "s", "y240", True),
                ("global terciles", "s", "y60", False),
                ("aggressor agreement (taker flow) instead of s", "agree", "y60", True)]
    for name, col, y, within in variants:
        c = lq.clustered(lq.day_diff(ev, col, y, within))
        print(f"| {name} | {bps(c['mean'])} | {c['t']:.2f} | {c['n']} |")

    print("\nmean y of every break (days counted once):")
    for d, name in ((1, "up-breaks"), (-1, "down-breaks")):
        sub = ev[(ev["direction"] == d) & np.isfinite(ev["y60"])]
        c = lq.clustered(sub.groupby("day")["y60"].mean())
        print(f"  {name}: {bps(c['mean'])} in the break's direction, t {c['t']:.2f}, {len(sub)} events")

    print("\nlong legs, gross and net of one taker round trip:")
    for name, d, g in (("a: buy forced down-breaks", -1, "forced"), ("b: buy organic up-breaks", 1, "organic"),
                       ("buy organic down-breaks", -1, "organic"), ("buy forced up-breaks", 1, "forced")):
        c = lq.clustered(lq.leg(ev, d, g))
        print(f"  {name}: {bps(c['mean'])} (t {c['t']:.2f}, {c['n']} days); "
              f"net Binance.US {bps(c['mean'] - COST_BINANCE_US)}, Hyperliquid {bps(c['mean'] - COST_HL)}")

    print("\nevents by year:")
    yr = ev.assign(year=ev["day"].str[:4]).groupby(["year", "direction"]).size().unstack(fill_value=0)
    yr.columns = [{1: "up", -1: "down"}[c] for c in yr.columns]
    print(yr.to_string())


def main() -> int:
    pd.set_option("display.width", 200)
    ev, metas = build()
    if ev.empty:
        print("no events")
        return 2
    ev = ev.sort_values(["day", "ts", "coin"]).reset_index(drop=True)
    ev.to_csv(EVENTS, index=False, float_format="%.10g")
    missing = {v: sorted(f"{m['day']} {m['coin']}" for m in metas
                         if m["bars"] and not str(m["venues"].get(v, "")).startswith("ok"))
               for v in lq.VENUES}
    MANIFEST.write_text(json.dumps({
        "days": [d.isoformat() for d in DAYS], "coins": UNIVERSE,
        "coin_days_with_bars": sum(1 for m in metas if m["bars"]),
        "coin_days_without_bars": sorted(f"{m['day']} {m['coin']}" for m in metas if not m["bars"]),
        "no_liquidation_file": missing, "events": len(ev)}, indent=1))
    print(f"-> {EVENTS.relative_to(ROOT)}, {MANIFEST.relative_to(ROOT)}")
    report(ev, metas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Hypothesis #30 — resting bids catch forced sellers.

    python research/bids.py          # reads #20's and #28's caches, downloads the rest into data/bids/

The rule and criteria are frozen in research/PREREGISTRATION_BIDS.md; this script
prints the pre-registered tables, and the verdict is written by hand into RESULTS_BIDS.md.
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
from typing import Dict, List, Optional, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import bids as bd  # noqa: E402
from espero import liq as lq  # noqa: E402
from espero import lows as lw  # noqa: E402
from espero.liq import clustered  # noqa: E402
from espero.xs import UNIVERSE  # noqa: E402

LOWS = ROOT / "data" / "lows"                      # #20's monthly cache, read only
LEVETF = ROOT / "data" / "levetf"                  # #28's, read only
CACHE = ROOT / "data" / "bids"
EVENTS = ROOT / "research" / "bids_events.csv.gz"
MANIFEST = ROOT / "research" / "bids_manifest.json"
MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
DAYS = [d.strftime("%Y-%m-%d") for d in pd.date_range("2026-10-01", "2026-10-27")]
URL_MONTH = "https://data.binance.vision/data/futures/um/monthly/klines/{sym}/5m/{sym}-5m-{month}.zip"
URL_DAY = "https://data.binance.vision/data/futures/um/daily/klines/{sym}/5m/{sym}-5m-{day}.zip"
KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume",
              "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]
WORKERS = 6
VARIANTS = {                                       # information only
    "bid 0.5 ATR": dict(k=0.5),
    "bid 2 ATR": dict(k=2.0),
    "fills on a touch": dict(eps=0.0),
    "4-hour exit": dict(hold=48),
    "bid 0.5 ATR, target entry + 1 ATR": dict(k=0.5, target="atr"),
    "bid 2 ATR, target entry + 1 ATR": dict(k=2.0, target="atr"),
}


def get(url: str, tries: int = 8) -> Optional[bytes]:
    """The body, or None for a 404 (no such file). Anything else is retried, then raised."""
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
        time.sleep(min(60.0, 2.0 ** k))
    return None


def blob(paths: List[Path], fallback: Path, url: str) -> Optional[bytes]:
    """The first cached file among `paths`; else `fallback`, fetched once (a 404 remembered as .none)."""
    for p in paths + [fallback]:
        if p.exists():
            return p.read_bytes()
        if p.with_suffix(".none").exists():
            return None
    data = get(url)
    fallback.parent.mkdir(parents=True, exist_ok=True)
    if data is None:
        fallback.with_suffix(".none").write_text("")
        return None
    fallback.write_bytes(data)
    time.sleep(0.2)
    return data


def frame(data: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        text = z.read(z.namelist()[0]).decode()
    header = text.split(",", 1)[0].strip() == "open_time"
    df = pd.read_csv(io.StringIO(text), header=0 if header else None)
    df.columns = KLINE_COLS
    return df


def coin(c: str) -> Tuple[Dict[str, pd.DataFrame], dict]:
    sym = lq.symbol("binance-futures", c)
    frames, missing = [], []
    for m in MONTHS:
        data = blob([LOWS / sym / f"{m}.zip", LEVETF / sym / f"{m}.zip"], CACHE / sym / f"{m}.zip",
                    URL_MONTH.format(sym=sym, month=m))
        if data:
            frames.append(frame(data))
        else:
            missing.append(m)
    for d in DAYS:
        data = blob([LEVETF / sym / "daily" / f"{d}.zip"], CACHE / sym / "daily" / f"{d}.zip",
                    URL_DAY.format(sym=sym, day=d))
        if data:
            frames.append(frame(data))
        else:
            missing.append(d)
    meta = {"coin": c, "symbol": sym, "missing": missing}
    if not frames:
        meta["status"] = "no bars"
        return {}, meta
    b = lw.bars(pd.concat(frames, ignore_index=True))
    skip = lw.excluded_days("2026-03-01", "2026-11-01")
    out = {"primary": bd.events(b, skip).assign(coin=c)}
    for name, kw in VARIANTS.items():
        out[name] = bd.events(b, skip, **kw).assign(coin=c)
    meta["status"] = "ok"
    meta["bars"] = len(b)
    return out, meta


def bps(x: float) -> str:
    return f"{1e4 * x:+.1f} bps"


def summary(name: str, ev: pd.DataFrame) -> str:
    ev = ev[ev["complete"].astype(bool)]
    fills = ev[ev["filled"].astype(bool)]
    a = clustered(lw.by_day(fills["net"], fills["day"]))
    v = clustered(lw.by_day(ev["value"], ev["day"]))
    rate = len(fills) / len(ev) if len(ev) else float("nan")
    return (f"| {name} | {len(fills)} | {100 * rate:.0f}% | {bps(a['mean'])} | {a['t']:.2f} | "
            f"{bps(v['mean'])} | {v['t']:.2f} |")


def report(runs: Dict[str, pd.DataFrame], metas: List[dict]) -> None:
    ev = runs["primary"]
    done = ev[ev["complete"].astype(bool)]
    fills = done[done["filled"].astype(bool)]
    print("\n## data\n")
    ok = [m for m in metas if m["status"] == "ok"]
    print(f"coins with bars: {len(ok)} of {len(metas)}")
    for m in metas:
        if m["missing"]:
            print(f"  {m['coin']}: missing {len(m['missing'])}: {', '.join(m['missing'][:8])}"
                  f"{' ...' if len(m['missing']) > 8 else ''}")
    print(f"events: {len(ev)} ({len(ev) - len(done)} dropped for gaps) on {done['day'].nunique()} days, "
          f"{done['day'].min()} -> {done['day'].max()}; fills: {len(fills)}")

    crit = bd.criteria(ev)
    print("\n## criteria (each UTC day's mean one observation)\n")
    print("| # | criterion | actual | met |")
    print("|---|---|---|---|")
    for i, r in enumerate(crit, 1):
        print(f"| {i} | {r['criterion']} | {r['actual']} | {'yes' if r['met'] else '**no**'} |")
    print(f"\nverdict: {bd.verdict(crit)}")

    print("\n## information only\n")
    print(f"fill rate {100 * len(fills) / len(done):.1f}%; exits: "
          f"{(fills['exit'] == 'target').mean():.0%} at the target, {(fills['exit'] == 'timeout').mean():.0%} timed out; "
          f"median depth {1e4 * done['depth'].median():.0f} bps below the trigger close")
    g = clustered(lw.by_day(fills["gross"], fills["day"]))
    fee = float((fills["gross"] - fills["net"]).mean()) if len(fills) else float("nan")
    print(f"filled trades' gross {bps(g['mean'])} (t {g['t']:.2f}); fees {1e4 * fee:.1f} bps a trade on average")
    unf = done[~done["filled"].astype(bool)]
    a, u = clustered(lw.by_day(fills["r60"], fills["day"])), clustered(lw.by_day(unf["r60"], unf["day"]))
    print(f"adverse selection, #20's gross 1-hour return from the next open: filled events {bps(a['mean'])} "
          f"(t {a['t']:.2f}), unfilled {bps(u['mean'])} (t {u['t']:.2f})")
    tk = clustered(lw.by_day(done["taker_net"], done["day"]))
    vb = clustered(lw.by_day(done["value"], done["day"]))
    print(f"per event: the bid {bps(vb['mean'])} (t {vb['t']:.2f}); taking (#20's trade, taker costs) "
          f"{bps(tk['mean'])} (t {tk['t']:.2f})")

    print("\n| variant | fills | fill rate | net per fill | t | per event | t |")
    print("|---|---|---|---|---|---|---|")
    print(summary("**the rule: bid 1 ATR, target the trigger close, 1 hour**", ev))
    for name in VARIANTS:
        print(summary(name, runs[name]))

    print("\nby month (filled trades):\n")
    print("| month | fills | net | t |")
    print("|---|---|---|---|")
    for m, grp in fills.assign(month=fills["day"].str[:7]).groupby("month"):
        c = clustered(lw.by_day(grp["net"], grp["day"]))
        print(f"| {m} | {len(grp)} | {bps(c['mean'])} | {c['t']:.2f} |")

    print("\nby coin (filled trades, mean net in bps):")
    per = fills.assign(x=1e4 * fills["net"]).groupby("coin")["x"].agg(["size", "mean"]).round(1)
    print(per.sort_values("mean").to_string())
    for c in ("BTC", "ETH"):
        grp = fills[fills["coin"] == c]
        print(f"{c}: {len(grp)} fills, mean net {bps(grp['net'].mean()) if len(grp) else '-'}")


def main() -> int:
    pd.set_option("display.width", 200)
    print(f"{len(UNIVERSE)} coins x {len(MONTHS)} months + {len(DAYS)} days of 5-minute bars ...", flush=True)
    runs: Dict[str, List[pd.DataFrame]] = {}
    metas = []
    with ThreadPoolExecutor(WORKERS) as ex:
        for k, (out, meta) in enumerate(ex.map(coin, UNIVERSE), 1):
            metas.append(meta)
            for name, df in out.items():
                runs.setdefault(name, []).append(df)
            n = len(out.get("primary", []))
            print(f"  {k}/{len(UNIVERSE)} {meta['coin']}: {meta['status']}, {n} events", flush=True)
    joined = {name: pd.concat(dfs, ignore_index=True) for name, dfs in runs.items()}
    ev = joined["primary"].sort_values(["ts", "coin"]).reset_index(drop=True)
    joined["primary"] = ev
    buf = io.StringIO()
    ev.to_csv(buf, index=False, float_format="%.6g")
    EVENTS.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))
    MANIFEST.write_text(json.dumps({"months": MONTHS, "days": DAYS, "coins": metas}, indent=1))
    print(f"-> {EVENTS.relative_to(ROOT)} ({len(ev)} events), {MANIFEST.relative_to(ROOT)}")
    report(joined, metas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

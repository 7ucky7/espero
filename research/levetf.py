"""Hypothesis #28 — leveraged ETFs push crypto into the US close.

    python research/levetf.py        # reads #20's 5-minute cache, downloads what is missing into data/levetf/

The rule and criteria are frozen in research/PREREGISTRATION_LEVETF.md; this script
checks the NYSE calendar against SPY's bars, then prints the pre-registered tables,
and the verdict is written by hand into RESULTS_LEVETF.md.
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
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import levetf as lv  # noqa: E402
from espero import lows as lw  # noqa: E402
from espero.liq import clustered  # noqa: E402

LOWS = ROOT / "data" / "lows"                     # #20's monthly cache, read only
CACHE = ROOT / "data" / "levetf"
SPY = ROOT / "data" / "trend" / "SPY.csv"
ROWS = ROOT / "research" / "levetf_days.csv.gz"
MANIFEST = ROOT / "research" / "levetf_manifest.json"
COINS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "XRP": "XRPUSDT"}
INFO_FROM = "2025-04-08"                          # SOL and XRP: 2x funds from spring 2025
MONTHS = [f"{y}-{m:02d}" for y in range(2019, 2027) for m in range(1, 13) if "2019-12" <= f"{y}-{m:02d}" <= "2026-09"]
DAYS = [d.strftime("%Y-%m-%d") for d in pd.date_range("2026-10-01", "2026-10-29")]
URL_MONTH = "https://data.binance.vision/data/futures/um/monthly/klines/{sym}/5m/{sym}-5m-{month}.zip"
URL_DAY = "https://data.binance.vision/data/futures/um/daily/klines/{sym}/5m/{sym}-5m-{day}.zip"
KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume",
              "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]
COST_HL = 0.0009


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


def cached(path: Path, url: str) -> Optional[bytes]:
    """A cached zip, fetched once; a 404 is remembered as `<name>.none`."""
    none = path.with_suffix(".none")
    if none.exists():
        return None
    if path.exists():
        return path.read_bytes()
    blob = get(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    if blob is None:
        none.write_text("")
        return None
    path.write_bytes(blob)
    time.sleep(0.2)
    return blob


def frame(blob: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        text = z.read(z.namelist()[0]).decode()
    header = text.split(",", 1)[0].strip() == "open_time"
    df = pd.read_csv(io.StringIO(text), header=0 if header else None)
    df.columns = KLINE_COLS
    return df


def coin_bars(sym: str) -> Tuple[pd.DataFrame, dict]:
    frames, missing = [], []
    for m in MONTHS:
        old = LOWS / sym / f"{m}.zip"
        if old.exists():
            blob = old.read_bytes()
        elif old.with_suffix(".none").exists():
            blob = None
        else:
            blob = cached(CACHE / sym / f"{m}.zip", URL_MONTH.format(sym=sym, month=m))
        if blob is None:
            missing.append(m)
        else:
            frames.append(frame(blob))
    for d in DAYS:
        blob = cached(CACHE / sym / "daily" / f"{d}.zip", URL_DAY.format(sym=sym, day=d))
        if blob is None:
            missing.append(d)
        else:
            frames.append(frame(blob))
    b = lw.bars(pd.concat(frames, ignore_index=True))
    return b, {"symbol": sym, "bars": len(b), "missing": missing,
               "first": pd.to_datetime(b.index.min(), unit="s", utc=True).isoformat(),
               "last": pd.to_datetime(b.index.max(), unit="s", utc=True).isoformat()}


def bps(x: float) -> str:
    return f"{1e4 * x:+.2f} bps"


def line(name: str, s: pd.Series) -> str:
    c = clustered(s)
    return f"| {name} | {bps(c['mean'])} | {c['t']:.2f} | {c['n']} |"


def report(df: pd.DataFrame, metas: dict) -> None:
    prim = df[df["coin"].isin(lv.PRIMARY)]
    print("\n## data\n")
    for c, m in metas.items():
        print(f"{c}: {m['bars']} bars {m['first'][:16]} -> {m['last'][:16]}; missing {len(m['missing'])}: "
              f"{', '.join(m['missing']) or '-'}")
    n = prim.dropna(subset=["y"]).groupby(["era", "kind"])["date"].nunique()
    print("\ndates with a primary y (BTC/ETH), by era and kind:")
    print(n.to_string())

    crit = lv.criteria(df)
    print("\n## criteria (BTC and ETH, each date's mean one observation)\n")
    print("| # | criterion | actual | met |")
    print("|---|---|---|---|")
    for i, r in enumerate(crit, 1):
        print(f"| {i} | {r['criterion']} | {r['actual']} | {'yes' if r['met'] else '**no**'} |")
    print(f"\nverdict: {lv.verdict(crit)}")

    print("\n## information only\n")
    print("| variant | mean | t | dates |")
    print("|---|---|---|---|")
    for era in ("with", "ramp", "before"):
        for kind in ("trading", "closed"):
            print(line(f"BTC+ETH, {era}, {kind}, 15:45 -> 16:00", lv.per_date(lv.sample(prim, era, kind))))
    for coin in lv.PRIMARY:
        g = df[df["coin"] == coin]
        for era in ("with", "before"):
            for kind in ("trading", "closed"):
                print(line(f"{coin}, {era}, {kind}", lv.per_date(lv.sample(g, era, kind))))
    for col, label in (("y30", "15:30 -> 16:00"), ("y5", "15:55 -> 16:00"), ("post15", "after: 16:00 -> 16:15"),
                       ("post60", "after: 16:00 -> 17:00")):
        for era in ("with", "before"):
            for kind in ("trading", "closed"):
                print(line(f"{label}, {era}, {kind}", lv.per_date(lv.sample(prim, era, kind), col)))
    for era in ("with", "before"):
        print(line(f"placebo 11:45 -> 12:00 ET, {era}, trading", lv.per_date(lv.sample(prim, era, "trading"), "midday")))
        g = prim[prim["era"] == era]
        print(line(f"placebo 23:45 -> 00:00 UTC, {era}, every date", lv.per_date(g, "utc")))

    yr = prim.assign(year=prim["date"].str[:4])
    print("\nby year, 15:45 -> 16:00 (BTC+ETH):\n")
    print("| year | trading | t | closed | t |")
    print("|---|---|---|---|---|")
    for y, g in yr.groupby("year"):
        a = clustered(lv.per_date(g[g["kind"] == "trading"]))
        b = clustered(lv.per_date(g[g["kind"] == "closed"]))
        print(f"| {y} | {bps(a['mean'])} | {a['t']:.2f} | {bps(b['mean'])} | {b['t']:.2f} |")

    w = lv.sample(prim, "with", "trading").dropna(subset=["y", "r"])
    w = w.assign(q=pd.qcut(w["r"].abs(), 5, labels=False) + 1)
    print("\nwith-era trading days by quintile of |r| (coin-days, each date's mean one observation):\n")
    print("| quintile | |r| range | mean y | t | dates |")
    print("|---|---|---|---|---|")
    for q, g in w.groupby("q"):
        c = clustered(lv.per_date(g))
        print(f"| {q} | {100 * g['r'].abs().min():.2f}% - {100 * g['r'].abs().max():.2f}% | {bps(c['mean'])} | "
              f"{c['t']:.2f} | {c['n']} |")

    print(f"\nSOL and XRP from {INFO_FROM}:\n")
    print("| coin | trading | t | closed | t |")
    print("|---|---|---|---|---|")
    for coin in ("SOL", "XRP"):
        g = df[(df["coin"] == coin) & (df["date"] >= INFO_FROM)]
        a = clustered(lv.per_date(g[g["kind"] == "trading"]))
        b = clustered(lv.per_date(g[g["kind"] == "closed"]))
        print(f"| {coin} | {bps(a['mean'])} | {a['t']:.2f} | {bps(b['mean'])} | {b['t']:.2f} |")

    c1 = clustered(lv.per_date(lv.sample(prim, "with", "trading")))
    big = lv.sample(prim, "with", "trading")
    c4 = clustered(lv.per_date(big[big["r"].abs() >= lv.BIG_R]))
    print(f"\nnet of one Hyperliquid round trip (9 bps): every with-era trading day {bps(c1['mean'] - COST_HL)}; "
          f"|r| >= 2% days {bps(c4['mean'] - COST_HL)}")


def main() -> int:
    pd.set_option("display.width", 200)
    spy = pd.read_csv(SPY, usecols=["dt"])["dt"].str[:10]
    bad = lv.calendar_mismatches(spy[(spy >= lv.FIRST) & (spy <= lv.LAST)].tolist())
    if bad:
        print(f"calendar disagrees with SPY's sessions on {len(bad)} dates: {', '.join(bad)}")
        return 1
    print(f"calendar matches SPY's sessions on every date {lv.FIRST} -> {lv.LAST}", flush=True)
    out: List[pd.DataFrame] = []
    metas = {}
    for coin, sym in COINS.items():
        print(f"  {coin}: loading {len(MONTHS)} months + {len(DAYS)} days of 5-minute bars ...", flush=True)
        b, meta = coin_bars(sym)
        metas[coin] = meta
        out.append(lv.rows(b, coin))
    df = pd.concat(out, ignore_index=True)
    buf = io.StringIO()
    df.to_csv(buf, index=False, float_format="%.6g")
    ROWS.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))
    MANIFEST.write_text(json.dumps({"months": MONTHS, "days": DAYS, "coins": metas}, indent=1))
    print(f"-> {ROWS.relative_to(ROOT)} ({len(df)} rows), {MANIFEST.relative_to(ROOT)}")
    report(df, metas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

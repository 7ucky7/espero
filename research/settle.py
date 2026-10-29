"""Hypothesis #19 — the funding settlement moves prices.

    python research/settle.py           # downloads funding and hourly bars (cached in data/settle/), then the tables

The rules and the pass criteria are frozen in research/PREREGISTRATION_SETTLE.md.
This script prints the pre-registered tables; the verdict is written by hand
into RESULTS_SETTLE.md.
"""
from __future__ import annotations

import datetime as dt
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

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import liq as lq  # noqa: E402
from espero import settle as st  # noqa: E402
from espero.xs import UNIVERSE  # noqa: E402

CACHE = ROOT / "data" / "settle"
EVENTS = ROOT / "research" / "settle_events.csv"
MANIFEST = ROOT / "research" / "settle_manifest.json"
START = int(dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc).timestamp())
END = int(dt.datetime(2026, 9, 30, 16, tzinfo=dt.timezone.utc).timestamp())
MONTHS = [f"{y}-{m:02d}" for y in range(2019, 2027) for m in range(1, 13) if "2019-12" <= f"{y}-{m:02d}" <= "2026-09"]
FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&startTime={start}&limit=1000"
KLINE_URL = {"perp": "https://data.binance.vision/data/futures/um/monthly/klines/{sym}/1h/{sym}-1h-{month}.zip",
             "spot": "https://data.binance.vision/data/spot/monthly/klines/{sym}/1h/{sym}-1h-{month}.zip"}
KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume",
              "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]
WORKERS = 6
COST_BINANCE_US = 0.0004
COST_HL = 0.0009


def get(url: str, tries: int = 4) -> Optional[bytes]:
    """The body, or None when there is no such file or symbol (a 404, or Binance's 400
    with code -1121, "Invalid symbol"). Anything else is retried, then raised."""
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "espero"}),
                                        timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404 or (exc.code == 400 and invalid_symbol(exc)):
                return None
            if exc.code in (401, 403) or k == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
            if k == tries - 1:
                raise
        time.sleep(1.5 * (k + 1))
    return None


def invalid_symbol(exc: urllib.error.HTTPError) -> bool:
    try:
        return json.loads(exc.read() or b"{}").get("code") == -1121
    except (ValueError, AttributeError, OSError):
        return False


def funding(sym: str) -> Optional[List[dict]]:
    """Every funding row from the day before the window to just past it, cached."""
    path = CACHE / "funding" / f"{sym}.json"
    if path.exists():
        return json.loads(path.read_text())
    rows: List[dict] = []
    cursor = (START - 86400) * 1000
    while cursor <= (END + 86400) * 1000:
        blob = get(FUNDING_URL.format(sym=sym, start=cursor))
        if blob is None:
            return None
        page = json.loads(blob)
        if not page:
            break
        rows += page
        cursor = int(page[-1]["fundingTime"]) + 1
        if len(page) < 1000:
            break
        time.sleep(0.25)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))
    return rows


def klines(market: str, sym: str) -> Tuple[Optional[pd.DataFrame], int]:
    """Hourly bars for every month in the window, cached per month; (bars, months missing)."""
    frames, missing = [], 0
    for month in MONTHS:
        path = CACHE / "klines" / market / sym / f"{month}.zip"
        none = path.with_suffix(".none")
        if none.exists():
            missing += 1
            continue
        if path.exists():
            blob = path.read_bytes()
        else:
            blob = get(KLINE_URL[market].format(sym=sym, month=month))
            path.parent.mkdir(parents=True, exist_ok=True)
            if blob is None:
                none.write_text("")
                missing += 1
                continue
            path.write_bytes(blob)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            text = z.read(z.namelist()[0]).decode()
        header = text.split(",", 1)[0].strip() == "open_time"
        df = pd.read_csv(io.StringIO(text), header=0 if header else None)
        df.columns = KLINE_COLS
        frames.append(df)
    if not frames:
        return None, missing
    return st.hourly(pd.concat(frames, ignore_index=True)), missing


def coin(c: str) -> Tuple[pd.DataFrame, dict]:
    perp_sym, spot_sym = lq.symbol("binance-futures", c), st.spot_symbol(c)
    meta = {"coin": c, "perp": perp_sym, "spot": spot_sym}
    rows = funding(perp_sym)
    if rows is None:
        meta["status"] = "no perpetual"
        return pd.DataFrame(), meta
    perp, meta["perp_months_missing"] = klines("perp", perp_sym)
    spot, meta["spot_months_missing"] = klines("spot", spot_sym)
    setl = st.settlements(rows)
    meta["settlements_8h"] = int(((setl["ts"] >= START) & (setl["ts"] <= END)).sum())
    if perp is None:
        meta["status"] = "no perpetual bars"
        return pd.DataFrame(), meta
    meta["status"] = "ok" if spot is not None else "ok, no spot bars"
    return st.events(setl, perp, spot, START, END).assign(coin=c), meta


def build() -> Tuple[pd.DataFrame, List[dict]]:
    print(f"{len(UNIVERSE)} coins, settlements {dt.datetime.fromtimestamp(START, dt.timezone.utc):%Y-%m-%d} -> "
          f"{dt.datetime.fromtimestamp(END, dt.timezone.utc):%Y-%m-%d %H:%M} UTC; "
          f"{len(MONTHS)} months of hourly bars each, cached in {CACHE.relative_to(ROOT)}/ ...", flush=True)
    out, metas = [], []
    with ThreadPoolExecutor(WORKERS) as ex:
        for k, (ev, meta) in enumerate(ex.map(coin, UNIVERSE), 1):
            metas.append(meta)
            if len(ev):
                out.append(ev)
            print(f"  {k}/{len(UNIVERSE)} {meta['coin']}: {meta['status']}", flush=True)
    return (pd.concat(out, ignore_index=True) if out else pd.DataFrame()), metas


def bps(x: float) -> str:
    return f"{1e4 * x:+.1f} bps"


def line(name: str, s: pd.Series) -> str:
    c = lq.clustered(s)
    return f"| {name} | {bps(c['mean'])} | {c['t']:.2f} | {c['n']} |"


def report(ev: pd.DataFrame, metas: List[dict]) -> None:
    x = st.excess(ev)
    print("\n## data\n")
    print(f"coins with a perpetual and bars: {sum(1 for m in metas if m['status'].startswith('ok'))} of {len(metas)}; "
          f"without spot bars: {[m['coin'] for m in metas if m['status'] == 'ok, no spot bars']}; "
          f"left out: {[(m['coin'], m['status']) for m in metas if not m['status'].startswith('ok')]}")
    grp = st.group(ev["f_prev"])
    print(f"8-hour settlements: {len(ev)}; high (|previous rate| >= 0.05%): {int((grp == 'high').sum())} "
          f"({int((ev['f_prev'] >= st.HIGH).sum())} longs paying, {int((ev['f_prev'] <= -st.HIGH).sum())} shorts paying); "
          f"baseline: {int((grp == 'base').sum())}")
    print(f"high events with g: {int(np.isfinite(x['g']).sum())} on {x.loc[np.isfinite(x['g']), 'day'].nunique()} days")

    rows = st.criteria(ev)
    print("\n## criteria (perpetual hourly bars; g = settlement minus placebo, against the hour's baseline coins)\n")
    print("| # | criterion | actual | met |")
    print("|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        print(f"| {i} | {r['criterion']} | {r['actual']} | {'yes' if r['met'] else '**no**'} |")
    print(f"\nverdict: {st.verdict(rows)}")

    print("\n## information only\n")
    print("| variant | mean | t | days |")
    print("|---|---|---|---|")
    a = x["f_prev"].abs()
    for name, lo, hi in (("g, |previous rate| 0.05-0.1%", 0.0005, 0.001), ("g, 0.1-0.2%", 0.001, 0.002),
                         ("g, 0.2% and above", 0.002, np.inf)):
        sel = x[(a >= lo) & (a < hi)]
        print(line(name, st.by_day(sel["g"], sel["day"])))
    now = st.excess(ev, rate="f_now")
    print(line("g, grouped on the settling rate", st.by_day(now["g"], now["day"])))
    print(line("placebo alone (e at +4h)", st.by_day(x["ep"], x["day"])))
    print(line("settlement alone (e at T)", st.by_day(x["e"], x["day"])))
    sp = st.excess(ev, pre="spot_pre", post="spot_post", pre_p="spot_pre_p", post_p="spot_post_p")
    print(line("g on spot bars", st.by_day(sp["g"], sp["day"])))
    two = st.excess(ev, pre="pre2", post="post2", pre_p="pre2_p", post_p="post2_p")
    print(line("g, 2-hour windows", st.by_day(two["g"], two["day"])))

    print("\nlong-only spot legs, gross and net of one taker round trip:")
    for name, sign, col in (("a: buy after the longs paid (T -> T+1h)", 1, "spot_post"),
                            ("b: buy into the short cover (T-1h -> T)", -1, "spot_pre")):
        c = lq.clustered(st.leg(ev, sign, col))
        print(f"  {name}: {bps(c['mean'])} (t {c['t']:.2f}, {c['n']} days); "
              f"net Binance.US {bps(c['mean'] - COST_BINANCE_US)}, Hyperliquid {bps(c['mean'] - COST_HL)}")

    print("\nhigh events by year and by who pays:")
    hi = ev[grp == "high"]
    tab = hi.assign(year=hi["day"].str[:4], pays=np.where(hi["f_prev"] > 0, "longs pay", "shorts pay"))
    print(tab.groupby(["year", "pays"]).size().unstack(fill_value=0).to_string())


def main() -> int:
    pd.set_option("display.width", 200)
    ev, metas = build()
    if ev.empty:
        print("no settlements")
        return 2
    ev = ev.sort_values(["ts", "coin"]).reset_index(drop=True)
    x = st.excess(ev)
    keep = ["ts", "day", "coin", "f_prev", "f_now", "d", "pre", "post", "pre_p", "post_p", "spot_pre", "spot_post",
            "n_b", "b_pre", "b_post", "n_bp", "bp_pre", "bp_post", "e_pre", "e_post", "e", "ep", "g"]
    x[keep].to_csv(EVENTS, index=False, float_format="%.8g")
    MANIFEST.write_text(json.dumps({"start": START, "end": END, "months": MONTHS, "coins": metas,
                                    "settlements": len(ev), "high_events": len(x)}, indent=1))
    print(f"-> {EVENTS.relative_to(ROOT)} ({len(x)} high events), {MANIFEST.relative_to(ROOT)}")
    report(ev, metas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

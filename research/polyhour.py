"""Hypothesis #37 — Polymarket's hourly bitcoin crowd against a random walk.

    python research/polyhour.py      # fetches every hourly market once (cached in data/polymarket/)

Frozen in research/PREREGISTRATION_POLYHOUR.md; the verdict is written by hand into RESULTS_POLYHOUR.md.
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
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))
from levpush import bars  # noqa: E402  (the cached-bar reader)

from espero import polyhour as ph  # noqa: E402
from espero.liq import clustered  # noqa: E402

CACHE = ROOT / "data" / "polymarket"
ROWS = ROOT / "research" / "polyhour_markets.csv.gz"
GAMMA = "https://gamma-api.polymarket.com/events?slug={slug}"
HISTORY = "https://clob.polymarket.com/prices-history?market={token}&startTs={start}&endTs={end}&fidelity=1"


def get(url: str, tries: int = 6):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "espero"}), timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code != 429 and exc.code < 500:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(min(30.0, 2.0 ** k))
    raise RuntimeError(f"{url}: gave up")


def market(d: dt.date, hour: int) -> dict:
    s = ph.slug(d, hour)
    path = CACHE / f"{s}.json"
    if path.exists():
        return json.loads(path.read_text())
    out = {"slug": s, "hour": hour, "start": ph.hour_start(d, hour), "outcome": None}
    ev = get(GAMMA.format(slug=s))
    if ev:
        m = ev[0]["markets"][0]
        prices = json.loads(m.get("outcomePrices") or "[]")
        if m.get("closed") and prices in (["1", "0"], ["0", "1"]):
            out["outcome"] = 1.0 if prices[0] == "1" else 0.0
        out["volume"] = m.get("volumeNum")
        token = json.loads(m["clobTokenIds"])[0]          # the "Up" outcome (outcomes are ["Up", "Down"])
        if json.loads(m.get("outcomes") or "[]")[:1] != ["Up"]:
            raise RuntimeError(f"{s}: outcomes {m.get('outcomes')}")
        h = get(HISTORY.format(token=token, start=out["start"] - 120, end=out["start"] + 3600))
        out["history"] = (h or {}).get("history", [])
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    time.sleep(0.1)
    return out


def cents(x: float) -> str:
    return f"{100 * x:+.2f}"


def main() -> int:
    days = [x.date() for x in pd.date_range(ph.FIRST, ph.LAST)]
    print(f"{len(days) * 24} hourly markets, {ph.FIRST} -> {ph.LAST} ...", flush=True)
    ms = []
    for i, d in enumerate(days):
        ms.extend(market(d, h) for h in range(24))
        if i % 15 == 0:
            print(f"  {d}: {len(ms)} fetched", flush=True)
    b = bars("BTC")
    rows = [r for r in (ph.market_row(m, b) for m in ms) if r is not None]
    df = pd.DataFrame(rows)
    buf = io.StringIO()
    df.to_csv(buf, index=False, float_format="%.6g")
    ROWS.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))
    missing = sum(1 for m in ms if "history" not in m)
    unresolved = sum(1 for m in ms if "history" in m and m["outcome"] is None)
    print(f"\nmarkets: {len(ms)}; not found {missing}; unresolved {unresolved}; with p and q "
          f"{int(df[['p', 'q']].notna().all(axis=1).sum())} -> {ROWS.relative_to(ROOT)}")
    crit = ph.criteria(df)
    print("\n## criteria\n")
    print("| # | criterion | actual | met |")
    print("|---|---|---|---|")
    for i, r in enumerate(crit, 1):
        print(f"| {i} | {r['criterion']} | {r['actual']} | {'yes' if r['met'] else '**no**'} |")
    print(f"\nverdict: {ph.verdict(crit)}")

    print("\n## information only (cents per $1 share)\n")
    by = {m["slug"]: m for m in ms}
    for name, kw in (("threshold 0.03", dict(threshold=0.03)), ("threshold 0.10", dict(threshold=0.10)),
                     ("minute 15", dict(minute=15)), ("minute 45", dict(minute=45)), ("cost 0.02", dict(cost=0.02))):
        alt = pd.DataFrame([r for r in (ph.market_row(by[s], b, **kw) for s in df["slug"]) if r is not None])
        bt = alt.dropna(subset=["profit"])
        c = clustered(bt.groupby("day")["profit"].mean())
        print(f"{name:15s} {cents(c['mean'])} (t {c['t']:.2f}), {len(bt)} bets")
    lean = df.dropna(subset=["p0", "prev_ret"])
    print(f"\nthe crowd at the hour's start: mean p0 {lean['p0'].mean():.3f}; corr(p0 - 0.5, previous hour's BTC move) "
          f"{np.corrcoef(lean['p0'] - 0.5, lean['prev_ret'])[0, 1]:+.3f}; corr(p0 - 0.5, outcome) "
          f"{np.corrcoef(lean['p0'] - 0.5, lean['outcome'])[0, 1]:+.3f}; Up won {lean['outcome'].mean():.3f}")
    bt = df.dropna(subset=["profit"])
    print(f"median volume of markets bet on: ${bt['volume'].median():,.0f}")
    print("\nby hour of day (ET), mean profit per bet, cents:")
    print((100 * bt.groupby("hour_et")["profit"].mean()).round(2).to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

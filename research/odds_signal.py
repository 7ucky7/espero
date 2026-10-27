"""Crypto-policy odds as a signal, implemented as research/PREREGISTRATION_ODDS.md says.

    python research/odds_signal.py

Enumerates the basket by the frozen search rule, fetches each market's odds
history, builds the matched 7-day change, and tests it against BTC's forward
20-day return.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import data  # noqa: E402

UA = {"User-Agent": "espero/0.1"}
CACHE = ROOT / "research" / "data" / "odds"
SEARCHES = ["bitcoin etf", "crypto regulation", "crypto bill", "sec crypto",
            "bitcoin reserve", "stablecoin bill", "crypto tax"]
CRYPTO = re.compile(r"\b(bitcoin|btc|crypto|ethereum|stablecoin)\b", re.I)
POLICY = re.compile(r"\b(etf|regulation|bill|law|sec|approval|ban|reserve|tax|legislation|congress)\b", re.I)
PRICEY = re.compile(r"(above \$|hit \$|between \$|close at|price|market cap|airdrop|ipo)", re.I)
LOOKBACK = 7
HOLD = 20
COST = 0.0010
DESIGN = ("2022-01-01", "2024-12-31")
HOLDOUT = ("2025-01-01", "2026-10-27")


def get(url: str) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def collect() -> list[dict]:
    """Enumerate candidates by the frozen search terms. No hand picking."""
    seen, out = set(), []
    for term in SEARCHES:
        d = get("https://gamma-api.polymarket.com/public-search?" +
                urllib.parse.urlencode({"q": term, "limit_per_type": "40"}))
        for e in d.get("events", []):
            for m in e.get("markets", []):
                q = m.get("question") or ""
                cid = m.get("conditionId") or m.get("id")
                if not cid or cid in seen:
                    continue
                if not (CRYPTO.search(q) and POLICY.search(q)):
                    continue
                if PRICEY.search(q):
                    continue
                seen.add(cid)
                out.append({"id": cid, "question": q, "closed": m.get("closed"),
                            "end": m.get("endDate"), "tokens": json.loads(m.get("clobTokenIds") or "[]")})
        time.sleep(0.2)
    return out


def history(token: str, mkt: str) -> pd.Series:
    path = CACHE / f"{mkt.replace('/', '_')[:60]}.json"
    if not path.exists():
        url = "https://clob.polymarket.com/prices-history?" + urllib.parse.urlencode(
            {"market": token, "interval": "max", "fidelity": 1440})
        path.write_text(json.dumps(get(url)))
        time.sleep(0.15)
    h = json.loads(path.read_text()).get("history", [])
    if not h:
        return pd.Series(dtype=float)
    s = pd.Series([p["p"] for p in h],
                  index=pd.to_datetime([p["t"] for p in h], unit="s", utc=True).tz_convert(None).normalize())
    return s.groupby(level=0).last()


def build_panel(markets: list[dict]) -> pd.DataFrame:
    cols = {}
    for m in markets:
        if not m["tokens"]:
            continue
        s = history(m["tokens"][0], m["id"])
        if len(s) >= 30:                      # frozen minimum
            cols[m["question"][:48]] = s
    return pd.DataFrame(cols).sort_index()


def deltas(panel: pd.DataFrame) -> pd.Series:
    """Matched-sample 7-day change, requiring at least 3 markets present on both days."""
    out = {}
    idx = panel.index
    for i in range(len(idx)):
        t = idx[i]
        back = t - pd.Timedelta(days=LOOKBACK)
        if back not in panel.index:
            continue
        a, b = panel.loc[t], panel.loc[back]
        both = a.notna() & b.notna()
        if both.sum() < 3:
            continue
        out[t] = float((a[both] - b[both]).mean())
    return pd.Series(out).sort_index()


def main() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    print("enumerating basket ...")
    mkts = collect()
    print(f"qualifying markets per the frozen rule: {len(mkts)}")
    (ROOT / "research" / "odds_basket.json").write_text(json.dumps(mkts, indent=2))

    panel = build_panel(mkts)
    print(f"panel: {panel.shape[1]} markets x {panel.shape[0]} days "
          f"({panel.index.min().date()} .. {panel.index.max().date()})")
    d = deltas(panel)
    print(f"signal days: {len(d)}\n")

    btc = data.yahoo_daily("BTC-USD", "5y").set_index("dt")["close"]
    btc.index = btc.index.tz_convert(None).normalize()

    rows = []
    for t, dv in d.items():
        fut = btc.index[btc.index.get_indexer([t], method="bfill")[0]:]
        if len(fut) <= HOLD:
            continue
        entry = btc.loc[fut[0]]
        exit_ = btc.loc[fut[min(HOLD, len(fut) - 1)]]
        rows.append({"date": t, "delta": dv, "fwd20": exit_ / entry - 1})
    sig = pd.DataFrame(rows).set_index("date")
    print(f"observations with a forward return: {len(sig)}")

    for label, (s, e) in (("design", DESIGN), ("holdout", HOLDOUT)):
        sub = sig.loc[s:e]
        if len(sub) < 20:
            print(f"{label}: only {len(sub)} observations")
            continue
        # spearman without scipy: pearson of ranks
        rho = sub["delta"].rank().corr(sub["fwd20"].rank())
        q = pd.qcut(sub["delta"], 5, labels=False, duplicates="drop")
        spread = sub.groupby(q)["fwd20"].mean()
        print(f"{label:8s} n={len(sub):3d}  spearman={rho:+.3f}  "
              f"Q1={100*spread.iloc[0]:+.2f}%  Q5={100*spread.iloc[-1]:+.2f}%  "
              f"Q5-Q1={100*(spread.iloc[-1]-spread.iloc[0]):+.2f}%")

    # simple rule: long BTC for 20 days whenever delta > 0
    btc_all = btc.loc[pd.Timestamp(DESIGN[0]):pd.Timestamp(HOLDOUT[1])]
    pos, rets = [], []
    i = 0
    dates = list(d.index)
    while i < len(dates):
        t = dates[i]
        if d.iloc[i] > 0:
            fut = btc_all.index[btc_all.index.get_indexer([t], method="bfill")[0]:]
            if len(fut) > HOLD:
                r = btc_all.loc[fut[HOLD]] / btc_all.loc[fut[0]] - 1 - 2 * COST
                rets.append((t, r))
                i += HOLD
                continue
        i += 1
    tr = pd.Series(dict(rets)).sort_index()
    if len(tr):
        eq = (1 + tr).cumprod()
        print(f"\nrule: {len(tr)} trades, total {100*(eq.iloc[-1]-1):+.1f}%, "
              f"win {100*(tr>0).mean():.0f}%")
        for label, (s, e) in (("design", DESIGN), ("holdout", HOLDOUT)):
            seg = tr.loc[s:e]
            if len(seg):
                bh = btc_all.loc[pd.Timestamp(s):pd.Timestamp(e)]
                print(f"  {label:8s} n={len(seg):3d}  return {100*((1+seg).prod()-1):+7.2f}%  "
                      f"vs BTC {100*(bh.iloc[-1]/bh.iloc[0]-1):+7.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

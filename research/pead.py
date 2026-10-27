"""PEAD test, implemented exactly as research/PREREGISTRATION_PEAD.md says.

    python research/pead.py            # fetches (cached), runs, prints design + holdout
    python research/pead.py --refetch  # ignore the cache

Event = SEC 8-K item 2.02, timestamped by acceptanceDateTime.
Frozen rule: reaction day from that timestamp, long if reaction >= +3%,
entry next open, 40-trading-day hold, max 5 x 20%, 10 bps a side.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CACHE = ROOT / "research" / "data" / "pead"
UA = "espero-research admin@example.com"

UNIVERSE = [
    # tech / comm (13)
    "AAPL", "MSFT", "INTC", "CSCO", "ORCL", "IBM", "TXN", "QCOM", "AMAT", "T", "VZ", "CMCSA", "ADI",
    # financials (11)
    "JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC", "SCHW", "AXP", "V", "MA",
    # energy (6)
    "XOM", "CVX", "COP", "SLB", "HAL", "OXY",
    # health (9)
    "JNJ", "PFE", "MRK", "ABT", "BMY", "LLY", "AMGN", "GILD", "UNH",
    # consumer (12)
    "WMT", "TGT", "HD", "LOW", "COST", "KO", "PEP", "PG", "CL", "KMB", "MCD", "SBUX", "NKE", "DIS",
    # industrial (9)
    "CAT", "DE", "BA", "LMT", "NOC", "GE", "HON", "UPS", "MMM",
    "SPY",
]

THRESHOLD = 0.03
HOLD_DAYS = 40
MAX_POSITIONS = 5
COST = 0.0010
DESIGN = ("2010-01-01", "2020-12-31")
HOLDOUT = ("2021-01-01", "2026-10-27")


def _curl(url: str) -> bytes:
    out = subprocess.run(["curl", "-s", "--compressed", "--max-time", "40", "-H", f"User-Agent: {UA}", url],
                         capture_output=True)
    if out.returncode != 0 or not out.stdout:
        raise RuntimeError(f"fetch failed: {url}")
    return out.stdout


def fetch_json(url: str, path: Path, refetch: bool = False) -> dict:
    if path.exists() and not refetch:
        return json.loads(path.read_text())
    data = _curl(url)
    path.write_text(data.decode("utf-8", "replace"))
    time.sleep(0.12)  # SEC allows 10 req/s; stay well under
    return json.loads(path.read_text())


def cik_map(refetch: bool = False) -> dict[str, str]:
    raw = fetch_json("https://www.sec.gov/files/company_tickers.json", CACHE / "tickers.json", refetch)
    return {v["ticker"]: str(v["cik_str"]).zfill(10) for v in raw.values()}


def filings(ticker: str, cik: str, refetch: bool = False) -> list[dict]:
    """All 8-K item 2.02 filings from the recent block and every archived chunk."""
    out = []
    recent = fetch_json(f"https://data.sec.gov/submissions/CIK{cik}.json",
                        CACHE / f"sub_{ticker}.json", refetch)
    blocks = [recent["filings"]["recent"]]
    for chunk in recent["filings"].get("files", []):
        arch = fetch_json(f"https://data.sec.gov/submissions/{chunk['name']}",
                          CACHE / f"sub_{ticker}_{chunk['name'][-8:-5]}.json", refetch)
        # archived chunks are a flat columnar block; the recent block is wrapped
        blocks.append(arch["filings"]["recent"] if "filings" in arch else arch)
    for b in blocks:
        for form, items, acc in zip(b["form"], b["items"], b["acceptanceDateTime"]):
            if form == "8-K" and "2.02" in (items or ""):
                out.append({"acceptance": acc})
    return out


def prices(ticker: str, refetch: bool = False) -> pd.DataFrame:
    path = CACHE / f"px_{ticker}.csv"
    if not path.exists() or refetch:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=20y&interval=1d"
        raw = json.loads(_curl(url))
        res = raw["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        rows = []
        for i, ts in enumerate(res["timestamp"]):
            o, h, l, c = (q[k][i] for k in ("open", "high", "low", "close"))
            if None in (o, h, l, c):
                continue
            rows.append({"dt": pd.to_datetime(ts, unit="s", utc=True).tz_convert("America/New_York").normalize().tz_localize(None),
                         "open": o, "close": c})
        pd.DataFrame(rows).to_csv(path, index=False)
        time.sleep(0.1)
    df = pd.read_csv(path, parse_dates=["dt"]).set_index("dt").sort_index()
    return df[~df.index.duplicated(keep="last")]


def reaction_day(acceptance: str, index: pd.DatetimeIndex) -> pd.Timestamp | None:
    ts = pd.Timestamp(acceptance).tz_convert("America/New_York")
    day = ts.normalize().tz_localize(None)
    if ts.hour >= 16:
        day = day + pd.Timedelta(days=1)
    pos = index.searchsorted(day)
    return index[pos] if pos < len(index) else None


def build_events(tickers: list[str], ci, px, refetch=False) -> pd.DataFrame:
    rows = []
    for t in tickers:
        df = px[t]
        for f in filings(t, ci[t], refetch):
            rd = reaction_day(f["acceptance"], df.index)
            if rd is None:
                continue
            loc = df.index.get_loc(rd)
            if loc < 1 or loc + 1 + HOLD_DAYS >= len(df):
                continue
            reaction = df["close"].iloc[loc] / df["close"].iloc[loc - 1] - 1
            entry_i = loc + 1
            exit_i = entry_i + HOLD_DAYS
            if exit_i >= len(df):
                continue
            rows.append({
                "ticker": t, "reaction_day": rd, "reaction": reaction,
                "entry_day": df.index[entry_i], "entry_px": float(df["open"].iloc[entry_i]),
                "exit_day": df.index[exit_i], "exit_px": float(df["close"].iloc[exit_i]),
            })
    ev = pd.DataFrame(rows).sort_values("entry_day").reset_index(drop=True)
    return ev


def simulate(ev: pd.DataFrame, px: dict[str, pd.DataFrame], start: str, end: str):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    ev = ev[(ev.entry_day >= start) & (ev.entry_day <= end) & (ev.reaction >= THRESHOLD)]
    if ev.empty:
        return pd.Series(dtype=float), 0

    cal = pd.DatetimeIndex(sorted(set().union(*[set(p.loc[start:end].index) for p in px.values()])))
    cash, positions, equity, trades = 1.0, [], [], 0
    by_entry = {d: g for d, g in ev.groupby("entry_day")}

    for day in cal:
        # exits at the close
        still = []
        for p in positions:
            if p["exit_day"] <= day:
                px_exit = float(px[p["ticker"]]["close"].asof(day))
                cash += p["size"] * px_exit * (1 - COST)
                trades += 1
            else:
                still.append(p)
        positions = still

        # entries at the open
        if day in by_entry:
            todays = by_entry[day].sort_values("reaction", ascending=False)
            for _, row in todays.iterrows():
                if len(positions) >= MAX_POSITIONS:
                    break
                eq = cash + sum(p["size"] * float(px[p["ticker"]]["close"].asof(day)) for p in positions)
                notional = 0.20 * eq
                if notional > cash or notional < 1e-9:
                    continue
                entry = float(px[row["ticker"]]["open"].asof(day)) * (1 + COST)
                positions.append({"ticker": row["ticker"], "size": notional / entry,
                                  "exit_day": row["exit_day"]})
                cash -= notional

        eq = cash + sum(p["size"] * float(px[p["ticker"]]["close"].asof(day)) for p in positions)
        equity.append((day, eq))

    return pd.Series(dict(equity)), trades


def metrics(eq: pd.Series) -> dict:
    if len(eq) < 2:
        return {}
    r = eq.pct_change().dropna()
    years = len(eq) / 252
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    dd = (eq / eq.cummax() - 1).min()
    return {"cagr": 100 * cagr, "sharpe": float(np.sqrt(252) * r.mean() / r.std()) if r.std() else 0,
            "maxdd": 100 * dd, "total": 100 * (eq.iloc[-1] / eq.iloc[0] - 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refetch", action="store_true")
    args = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)

    print(f"{len(UNIVERSE)} tickers; fetching CIKs ...")
    ci = cik_map(args.refetch)
    missing = [t for t in UNIVERSE if t not in ci]
    tickers = [t for t in UNIVERSE if t in ci]
    if missing:
        print("no CIK for:", missing)
    print("fetching prices ...")
    px = {t: prices(t, args.refetch) for t in tickers}
    print("fetching filings ...")
    ev = build_events(tickers, ci, px, args.refetch)
    print(f"events parsed: {len(ev)}  (8-K 2.02, 1994-2026)\n")

    for label, (s, e) in (("design", DESIGN), ("holdout", HOLDOUT)):
        eq, trades = simulate(ev, px, s, e)
        m = metrics(eq)
        spy = px["SPY"] if "SPY" in px else None
        bench = {}
        if spy is not None:
            b = spy.loc[pd.Timestamp(s):pd.Timestamp(e), "close"]
            bench = metrics(b / b.iloc[0])
        if m:
            print(f"{label:8s} trades={trades:3d}  cagr={m['cagr']:+7.2f}%  sharpe={m['sharpe']:5.2f}  "
                  f"maxdd={m['maxdd']:7.2f}%  total={m['total']:+8.2f}%")
            if bench:
                print(f"{'':8s} SPY      cagr={bench['cagr']:+7.2f}%  sharpe={bench['sharpe']:5.2f}  "
                      f"maxdd={bench['maxdd']:7.2f}%  total={bench['total']:+8.2f}%")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

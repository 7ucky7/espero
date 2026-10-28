"""Hypothesis #14 — #12's carry rule, unchanged, on Kraken Futures funding.

    python research/carry_kraken.py fetch   # universe, funding, perp and spot candles -> research/data/carry_kraken
    python research/carry_kraken.py run     # one replay: primary window (criteria) and the later months (info)

Rule, window, costs and criteria: research/PREREGISTRATION_CARRY3.md. Engine: espero/carry.py,
the same `simulate` #12 ran on; the report is research/carry.py's.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from espero import carry, data  # noqa: E402
from espero import kraken_futures as kf  # noqa: E402

sys.path.insert(0, str(ROOT / "research"))
from carry import report  # noqa: E402

DATA = ROOT / "research" / "data" / "carry_kraken"
TOP = 20
PRIMARY_END = int(dt.datetime(2026, 4, 2, tzinfo=dt.timezone.utc).timestamp())   # #12's window starts here
PERP_FEE = {"maker": 0.0002, "taker": 0.0005}                                       # Kraken Futures base tier


def fetch() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    perps = kf.perpetuals()
    spot_products = set(data.list_products(exclude=()))
    universe = []
    for r in kf.top_by_open_interest(TOP, perps):
        if f"{r['coin']}-USD" in spot_products:
            universe.append(r)
        else:
            print(f"{r['symbol']}: no Coinbase spot pair, dropped")
    (DATA / "universe.json").write_text(json.dumps(
        {"fetched": dt.datetime.now(dt.timezone.utc).isoformat(), "coins": universe}, indent=2))
    print(f"universe: {len(universe)} perps: {' '.join(r['coin'] for r in universe)}")

    now = dt.datetime.now(dt.timezone.utc)
    for r in universe:
        sym, coin = r["symbol"], r["coin"]
        if all((DATA / f"{k}_{coin}.csv").exists() for k in ("funding", "perp", "spot")):
            print(f"{coin}: on disk")
            continue
        t0 = time.time()
        raw = kf.funding_history(sym)
        raw.to_csv(DATA / f"funding_raw_{coin}.csv", index=False)
        f = kf.hourly_funding(raw)
        f.to_csv(DATA / f"funding_{coin}.csv", index=False)
        if f.empty:
            print(f"{coin}: no funding history")
            continue
        start = int(f["ts"].iloc[0])
        p = kf.candles(sym, start)
        p.to_csv(DATA / f"perp_{coin}.csv", index=False)
        days = (now - dt.datetime.fromtimestamp(start, dt.timezone.utc)).days + 1
        s = data.fetch(f"{coin}-USD", days, 3600)
        s.to_csv(DATA / f"spot_{coin}.csv", index=False)
        print(f"{coin}: funding {len(raw)} rates -> {len(f)}h  perp {len(p)}h  spot {len(s)}h  "
              f"({time.time() - t0:.0f}s)")


def load(window: str) -> dict:
    """`primary`: hours before 2026-04-02 (the criteria). `later`: from then on (info).
    The cut is applied before `from_frames`, so the 90-day minimum is per window."""
    uni = json.loads((DATA / "universe.json").read_text())["coins"]
    coins = {}
    for r in uni:
        coin = r["coin"]
        try:
            f = pd.read_csv(DATA / f"funding_{coin}.csv")
            p = pd.read_csv(DATA / f"perp_{coin}.csv")
            s = pd.read_csv(DATA / f"spot_{coin}.csv")
        except (FileNotFoundError, pd.errors.EmptyDataError):
            print(f"{coin}: excluded (no data)")
            continue
        pts, sts = data.unix_seconds(p["time"]), data.unix_seconds(s["time"])
        if window == "primary":
            f, p, s = f[f["ts"] < PRIMARY_END], p[(pts < PRIMARY_END).to_numpy()], s[(sts < PRIMARY_END).to_numpy()]
        else:
            f, p, s = f[f["ts"] >= PRIMARY_END], p[(pts >= PRIMARY_END).to_numpy()], s[(sts >= PRIMARY_END).to_numpy()]
        cd = carry.from_frames(f, p, s) if len(p) and len(s) else None
        if cd is None or len(cd.funding) < carry.MIN_HISTORY_H:
            print(f"{coin}: excluded (under 90 days with funding, perp and spot)")
            continue
        coins[coin] = cd
    return coins


def run() -> None:
    rule = dict(swap_gap=carry.SWAP_GAP, min_hold=carry.MIN_HOLD_H)
    primary = load("primary")
    print("== #14 primary: before 2026-04-02, #12's rule, maker costs, Kraken perp 2 bps (criteria judged here)")
    report(primary, maker=True, perp_fee=PERP_FEE["maker"], **rule)
    print("\n\n== reported: same window, taker costs (Kraken perp 5 bps + 5 bps slippage)")
    report(primary, brief=True, maker=False, perp_fee=PERP_FEE["taker"], **rule)
    later = load("later")
    print("\n\n== reported, not a criterion: 2026-04-02 -> fetch, the months #12 ran on, maker costs")
    if later:
        report(later, brief=True, maker=True, perp_fee=PERP_FEE["maker"], **rule)
    else:
        print("no coin has 90 days in this window")


if __name__ == "__main__":
    {"fetch": fetch, "run": run}[sys.argv[1] if len(sys.argv) > 1 else "run"]()

"""Hypothesis #26 — #18's rule on every day of Binance's COIN-M liquidations.

    python research/liq2.py     # 5-minute bars from #20's cache; liquidation files into data/liq2/

Rules and criteria frozen in research/PREREGISTRATION_LIQ2.md (with its amendment);
the verdict is written by hand into RESULTS_LIQ2.md.
"""
from __future__ import annotations

import datetime as dt
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
from espero import coinm as cm  # noqa: E402
from espero import liq as lq  # noqa: E402
from espero import lows as lw  # noqa: E402

CACHE = ROOT / "data" / "liq2"
EVENTS = ROOT / "research" / "liq2_events.csv.gz"
FIRST, LAST = dt.date(2023, 6, 26), dt.date(2024, 10, 14)
SPLIT = "2024-02-16"
WORKERS = 6
UNMEASURED = ["forced", "forced_binance", "forced_bybit", "forced15", "liq_total", "s", "s_binance",
              "s_bybit", "s15"]


def lows_module():
    spec = importlib.util.spec_from_file_location("research_lows", ROOT / "research" / "lows.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RL = lows_module()


def days() -> List[dt.date]:
    skip = lw.excluded_days()
    return [d for d in (FIRST + dt.timedelta(n) for n in range((LAST - FIRST).days + 1))
            if d.isoformat() not in skip]


def liq_file(coin: str, day: dt.date) -> Optional[str]:
    """The day's snapshot CSV text, or None when Binance has no file for it (cached either way)."""
    sym = cm.symbol(coin)
    path = CACHE / sym / f"{day}.csv.gz"
    none = CACHE / sym / f"{day}.none"
    if none.exists():
        return None
    if not path.exists():
        blob = RL.get(cm.URL.format(sym=sym, day=day.isoformat()))
        path.parent.mkdir(parents=True, exist_ok=True)
        if blob is None:
            none.write_text("")
            return None
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            path.write_bytes(gzip.compress(z.read(z.namelist()[0]), mtime=0))
    return gzip.decompress(path.read_bytes()).decode()


def bars_5m(coin: str) -> Optional[pd.DataFrame]:
    """#18's bar frame (quote and taker-buy volume kept) from #20's monthly 5-minute files."""
    sym = lq.symbol("binance-futures", coin)
    months = [m for m in RL.MONTHS if "2023-06" <= m <= "2024-10"]
    frames = [f for f in (RL.month_frame(sym, m) for m in months) if f is not None]
    return lq.bars_5m(pd.concat(frames, ignore_index=True)) if frames else None


def coin(c: str) -> Tuple[pd.DataFrame, dict]:
    bars = bars_5m(c)
    if bars is None:
        return pd.DataFrame(), {"coin": c, "status": "no bars"}
    texts = {d: liq_file(c, d) for d in days()}
    have = [d for d, t in texts.items() if t is not None]
    if not have:
        return pd.DataFrame(), {"coin": c, "status": "no liquidation files"}
    span = (min(have), max(have))
    out = []
    for d, text in texts.items():
        start = int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp())
        window = bars[(bars.index >= start - 86400) & (bars.index < start + 2 * 86400)]
        if window.empty:
            continue
        liq = cm.liquidations(text, c) if text is not None else pd.DataFrame(columns=["ts", "side", "usd", "venue"])
        ev = lq.events(window, liq, start)
        if not (span[0] <= d <= span[1]):
            ev[UNMEASURED] = np.nan                       # outside the coin's span: no forced share (amendment)
        out.append(ev.assign(coin=c, day=d.isoformat()))
    ev = pd.concat(out, ignore_index=True) if out else pd.DataFrame()
    return ev, {"coin": c, "status": "ok", "files": len(have), "first_file": str(span[0]), "last_file": str(span[1]),
                "events": len(ev)}


def bps(x: float) -> str:
    return f"{1e4 * x:+.1f} bps"


def main() -> int:
    pd.set_option("display.width", 200)
    print(f"{len(cm.COINS)} coins, {len(days())} days {FIRST} -> {LAST} (#18's days left out); "
          f"COIN-M liquidations cached in data/liq2/ ...", flush=True)
    out, metas = [], []
    with ThreadPoolExecutor(WORKERS) as ex:
        for k, (ev, meta) in enumerate(ex.map(coin, cm.COINS), 1):
            metas.append(meta)
            if len(ev):
                out.append(ev)
            print(f"  {k}/{len(cm.COINS)} {meta}", flush=True)
    ev = pd.concat(out, ignore_index=True)
    # empty per-day tables carry object columns into the concat; the measures are numbers
    num = [c for c in ev.columns if c not in ("coin", "day")]
    ev[num] = ev[num].apply(pd.to_numeric, errors="coerce")
    buf = io.StringIO()
    ev.to_csv(buf, index=False, float_format="%.6g")
    EVENTS.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))
    (ROOT / "research" / "liq2_manifest.json").write_text(json.dumps(metas, indent=1))

    use = lq.usable(ev)
    print("\n## data\n")
    print(f"events: {len(ev)} ({int((ev['direction'] == 1).sum())} up, {int((ev['direction'] == -1).sum())} down); "
          f"usable: {len(use)} on {use['day'].nunique()} days; with no liquidation on the break's side: "
          f"{(ev['forced'] == 0).mean():.1%}")
    rows = lq.criteria(ev, split=SPLIT)
    print("\n## criteria (#18's, halves split at 2024-02-16)\n")
    print("| # | criterion | actual | met |")
    print("|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        print(f"| {i} | {r['criterion']} | {r['actual']} | {'yes' if r['met'] else '**no**'} |")
    print(f"\nverdict: {lq.verdict(rows)}")
    print("\n## information only\n")
    for name, col, y, within in (("15-minute window", "s15", "y60", True), ("15-minute horizon", "s", "y15", True),
                                 ("4-hour horizon", "s", "y240", True), ("global terciles", "s", "y60", False),
                                 ("taker-flow agreement instead of s", "agree", "y60", True)):
        c = lq.clustered(lq.day_diff(ev, col, y, within))
        print(f"{name}: D {bps(c['mean'])}, t {c['t']:.2f}, {c['n']} days")
    for name, d, g in (("a: buy forced down-breaks", -1, "forced"), ("b: buy organic up-breaks", 1, "organic")):
        c = lq.clustered(lq.leg(ev, d, g))
        print(f"  {name}: {bps(c['mean'])} (t {c['t']:.2f}); net Hyperliquid {bps(c['mean'] - 0.0009)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Hypothesis #21 — liquidation spikes reverse, on aggr's sealed months.

    python research/liqspike.py

Checks the four sealed files against research/aggr_holdout_manifest.json, builds
the exploration's hourly panel (explored months as warm-up for the trailing
thresholds only), and prints the pre-registered tables. The rules and criteria
are frozen in research/PREREGISTRATION_LIQSPIKE.md; the verdict is written by hand
into RESULTS_LIQSPIKE.md.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import liq as lq  # noqa: E402
from espero import liqspike as ls  # noqa: E402

EVENTS = ROOT / "research" / "liqspike_events.csv"
COST_BINANCE_US = 0.0004
COST_HL = 0.0009


def explore_module():
    spec = importlib.util.spec_from_file_location("aggr_explore", ROOT / "research" / "aggr_explore.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def verify(data: Path, manifest: Path) -> None:
    """Every sealed file present and byte-for-byte what was sealed, or the run stops."""
    sealed = json.loads(manifest.read_text())["files"]
    for name, digest in sealed.items():
        got = hashlib.sha256((data / "holdout" / name).read_bytes()).hexdigest()
        if got != digest:
            raise RuntimeError(f"sealed file {name} changed: {got} != {digest}")


def load_holdout(ax) -> pd.DataFrame:
    verify(ax.DATA, ax.MANIFEST)
    frame = pd.concat([pd.read_csv(ax.DATA / "holdout" / f"{m}.csv.gz") for m in ax.HOLDOUT], ignore_index=True)
    frame["t"] = pd.to_datetime(frame["time"], unit="s", utc=True)
    return frame


def bps(x: float) -> str:
    return f"{1e4 * x:+.1f} bps"


def row(name: str, s: pd.Series) -> str:
    c = lq.clustered(s)
    return f"| {name} | {bps(c['mean'])} | {c['t']:.2f} | {c['n']} |"


def report(p, ev: pd.DataFrame, base) -> None:
    print("## data\n")
    span = f"{ls.TEST_FROM:%Y-%m-%d %H:%M} -> {ls.TEST_TO:%Y-%m-%d %H:%M} UTC"
    print(f"{len(p)} coins; spike hours from {span}; thresholds from each coin's previous 720 hours")
    print(f"events: {int((ev['side'] == 'long').sum())} long-liquidation spikes, "
          f"{int((ev['side'] == 'short').sum())} short-liquidation spikes, on {ev['day'].nunique()} days")
    print(f"baseline (mean over every coin-hour): {', '.join(f'{k}h {bps(v)}' for k, v in base.items())}")

    rows = ls.criteria(ev, base)
    print("\n## criteria (excess = return minus the baseline; R signs it so a reversal is positive)\n")
    print("| # | criterion | actual | met |")
    print("|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        print(f"| {i} | {r['criterion']} | {r['actual']} | {'yes' if r['met'] else '**no**'} |")
    print(f"\nverdict: {ls.verdict(rows)}")

    print("\n## information only\n")
    print("| variant | mean | t | days |")
    print("|---|---|---|---|")
    longs, shorts = ev[ev["side"] == "long"], ev[ev["side"] == "short"]
    for k in (1, 4):
        print(row(f"R at {k}h", ls.by_day(ls.reversal(ev, base, k), ev["day"])))
        print(row(f"longs, excess {k}h", ls.by_day(longs[f"r{k}"] - base[k], longs["day"])))
        print(row(f"shorts, excess {k}h", ls.by_day(shorts[f"r{k}"] - base[k], shorts["day"])))
    print(row("long leg raw 24h, entry at the next hour's open", ls.by_day(np.expm1(longs["r24_open"]), longs["day"])))
    print(row("short leg (a paper short) raw 24h", ls.by_day(-np.expm1(shorts["r24"]), shorts["day"])))
    crowd = ev.groupby(["t", "side"])["coin"].transform("size")
    for name, sel in (("spikes shared by 5+ coins in the hour", crowd >= 5), ("spikes on 1-4 coins", crowd < 5)):
        e = ev[sel]
        print(row(f"R, {name} ({int(sel.sum())} events)", ls.by_day(ls.reversal(e, base), e["day"])))
    size = longs["usd"].rank(pct=True)
    for name, sel in (("long spikes, top third by dollars", size > 2 / 3), ("long spikes, bottom third", size <= 1 / 3)):
        e = longs[sel]
        print(row(name, ls.by_day(e["r24"] - base[24], e["day"])))

    leg = lq.clustered(ls.by_day(np.expm1(longs["r24"]), longs["day"]))
    print(f"\nlong leg, raw 24h: {bps(leg['mean'])} gross; net Binance.US {bps(leg['mean'] - COST_BINANCE_US)}, "
          f"Hyperliquid {bps(leg['mean'] - COST_HL)}")
    print("\nlong-liquidation spikes' excess 24h by coin:")
    print((longs.assign(x=1e4 * (longs["r24"] - base[24])).groupby("coin")["x"].agg(["size", "mean"])
           .round(1).to_string()))


def main() -> int:
    pd.set_option("display.width", 200)
    ax = explore_module()
    holdout = load_holdout(ax)
    print("sealed files verified against research/aggr_holdout_manifest.json\n")
    raw = pd.concat([ax.load_explore(), holdout], ignore_index=True)
    p = ax.panel(raw)
    ev = ls.events(p)
    base = ls.baseline(p)
    ev.to_csv(EVENTS, index=False, float_format="%.8g")
    report(p, ev, base)
    print(f"\n-> {EVENTS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

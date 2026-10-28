"""Hypotheses #9 and #9b — BTC lead-lag into altcoins, hourly.

#9 (unscaled gap) fails by construction: within an hour BTC's return is one
number, so the gap's cross-sectional ranks equal plain reversal's. #9b scales
BTC's move by each coin's trailing beta, which varies across coins. Both are
reported; the criteria are applied to #9b. See the two pre-registrations.

    python research/leadlag.py            # fetches a year of hourly candles (or reuses data/panel_hourly)
    python research/leadlag.py --refresh

The rule and the pass criteria are frozen in research/PREREGISTRATION_LEADLAG.md.
This script prints the pre-registered table; the verdict is written by hand into
RESULTS_LEADLAG.md.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import factor_eval as fe  # noqa: E402
from espero import factors, ops, panel  # noqa: E402

PANEL_DIR = ROOT / "data" / "panel_hourly"
DAYS = 365
LEADER = "BTC"
PRIMARY_H = 3
HORIZONS = (1, 3, 6, 12)
MIN_HISTORY = 720          # 30 days of hours
MIN_DOLLAR_VOLUME = 50_000  # per hour, trailing 7-day mean
VOLUME_WINDOW = 168
EMBARGO = 24
N_SPLITS = 4
# Kept as run (research/ERRATA.md, 2026-10-28): defined but never passed to fe.evaluate,
# so the published run used its default min_train=180 hours, not the pre-registered 30 days.
MIN_TRAIN = 720
SPREAD_HURDLE = 0.0010     # 10 bps per 3h
HIT_HURDLE = 0.52
COST_CHEAP = 0.0004        # Binance.US round trip
COST_COINBASE = 0.0240     # Coinbase taker round trip
PRIMARY = "leadlag_beta_1h"
TABLE = ["leadlag_beta_1h", "leadlag_beta_3h", "leadlag_1h", "leadlag_3h", "rev_1", "rev_3", "mom_7", "mom_30", "lowvol_30", "maxret_30",
         "amihud_30", "volume_z_20", "alpha101_6", "alpha101_12", "alpha101_101"]


def load_panel(refresh: bool) -> panel.MarketPanel:
    if PANEL_DIR.exists() and not refresh:
        p = panel.MarketPanel.load(PANEL_DIR)
        print(f"panel from {PANEL_DIR}: {len(p.coins)} coins, {len(p.index)} hours")
        return p
    print(f"fetching {DAYS} days of hourly candles from Coinbase ...")
    p = panel.build_coinbase(days=DAYS, granularity=3600)
    p.save(PANEL_DIR)
    print(f"{len(p.coins)} coins, {len(p.index)} hours; not on Coinbase: {sorted(p.errors) or 'none'}")
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    p = load_panel(args.refresh)

    mask = panel.eligible(p, min_history=MIN_HISTORY, min_dollar_volume=MIN_DOLLAR_VOLUME,
                          volume_window=VOLUME_WINDOW)
    mask[LEADER] = False      # the leader is not in the cross-section it leads
    print(f"eligible in the last hour: {int(mask.iloc[-1].sum())} / {len(p.coins) - 1}")
    print(f"window {p.index[0]} → {p.index[-1]}")

    tables = {}
    for h in HORIZONS:
        tables[h] = fe.evaluate(p, names=TABLE, horizon=h, mask=mask, n_splits=N_SPLITS,
                                embargo=EMBARGO)
    print(f"\n## factor table, primary horizon {PRIMARY_H}h (purged {N_SPLITS}-block walk-forward, "
          f"{EMBARGO}h embargo)\n")
    print("```")
    print(fe.format_table(tables[PRIMARY_H]))
    print("```")

    print(f"\n## {PRIMARY} across horizons (information)\n")
    print("| horizon | IC oos | ICIR | t oos | hit | Q5-Q1 | churn |")
    print("|---|---|---|---|---|---|---|")
    for h in HORIZONS:
        r = tables[h].loc[PRIMARY]
        print(f"| {h}h | {r['ic_oos']:+.4f} | {r['icir_oos']:.2f} | {r['t_oos']:.2f} | {r['hit_oos']:.2f} | "
              f"{1e4 * r['spread_oos']:+.1f} bps | {r['turnover']:.2f} |")

    t = tables[PRIMARY_H]
    ll, rv = t.loc[PRIMARY], t.loc["rev_1"]
    same = t.loc["leadlag_1h"]
    print(f"\n#9 check: leadlag_1h t={same['t_oos']:.2f} vs rev_1 t={rv['t_oos']:.2f} "
          f"(identical by construction: {abs(same['t_oos'] - rv['t_oos']) < 1e-9})")
    spread_bps = 1e4 * ll["spread_oos"]
    print(f"\n## criteria at {PRIMARY_H}h\n")
    print("| criterion | required | actual | met |")
    print("|---|---|---|---|")
    print(f"| OOS IC t > 3 | > 3 | {ll['t_oos']:.2f} | {'yes' if ll['t_oos'] > 3 else '**no**'} |")
    print(f"| beats rev_1 (t) | > {rv['t_oos']:.2f} | {ll['t_oos']:.2f} | "
          f"{'yes' if ll['t_oos'] > rv['t_oos'] else '**no**'} |")
    print(f"| Q5-Q1 spread > 10 bps | > 10.0 | {spread_bps:+.1f} bps | "
          f"{'yes' if ll['spread_oos'] > SPREAD_HURDLE else '**no**'} |")
    print(f"| hit rate > 0.52 | > 0.52 | {ll['hit_oos']:.3f} | {'yes' if ll['hit_oos'] > HIT_HURDLE else '**no**'} |")
    print(f"\nspread net of costs per {PRIMARY_H}h: Binance.US {spread_bps - 1e4 * COST_CHEAP:+.1f} bps · "
          f"Coinbase {spread_bps - 1e4 * COST_COINBASE:+.1f} bps  (one round trip per rebalance)")

    print(f"\nIC decay of {PRIMARY} (mean IC by horizon, full window):")
    f = ops.where_valid(factors.ZOO[PRIMARY](p), mask)
    print(fe.ic_decay(f, p.close, horizons=(1, 2, 3, 6, 12, 24)).round(4).to_string())
    pd.set_option("display.width", 200)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

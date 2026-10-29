"""Hypotheses #16 and #17 — altcoins led by their peer basket, and
ETH-ecosystem coins led by ETH, hourly.

    python research/peers.py            # fetches the frozen year (or reuses data/panel_peers)
    python research/peers.py --no-hl    # skip the Hyperliquid information table

The rules and the pass criteria are frozen in research/PREREGISTRATION_PEERS.md.
This script prints the pre-registered tables; the verdicts are written by hand
into RESULTS_PEERS.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import data, ops, panel  # noqa: E402
from espero import factor_eval as fe  # noqa: E402
from espero import factors as fz  # noqa: E402
from espero.xs import UNIVERSE  # noqa: E402

PANEL_DIR = ROOT / "data" / "panel_peers"
HL_DIR = ROOT / "data" / "panel_peers_hl"
START = dt.datetime(2024, 10, 27, tzinfo=dt.timezone.utc)
END = dt.datetime(2025, 10, 27, tzinfo=dt.timezone.utc)      # exclusive
DAYS = (END - START).days
HL_DAYS = 208                       # the ~5,000 hourly bars Hyperliquid serves
PRIMARY_H = 3
HORIZONS = (1, 3, 6, 12)
MIN_HISTORY = 720
MIN_DOLLAR_VOLUME = 50_000
VOLUME_WINDOW = 168
BETA_WINDOW = 168
EMBARGO = 24
N_SPLITS = 4
MIN_TRAIN = 720
T_HURDLE = 3.0
SPREAD_HURDLE = 0.0010              # 10 bps per 3h
HIT_HURDLE = 0.52
COST_TAKER = 0.0009                 # Hyperliquid round trip, 4.5 bps a side
COST_MAKER = 0.0003
ETH_GROUP = ["ARB", "OP", "LINK", "AAVE", "MKR", "CRV", "SNX", "SUSHI", "YFI", "SHIB", "WLD"]
ETH_MIN_COINS = 6


def load_panel(fetch_hl: bool = False) -> panel.MarketPanel:
    directory = HL_DIR if fetch_hl else PANEL_DIR
    if directory.exists():
        p = panel.MarketPanel.load(directory)
        print(f"panel from {directory.relative_to(ROOT)}: {len(p.coins)} coins, {len(p.index)} hours")
        return p
    if fetch_hl:
        print(f"fetching {HL_DAYS} days of hourly Hyperliquid perp bars ...", flush=True)
        p = panel.build_hyperliquid(UNIVERSE, days=HL_DAYS, granularity=3600)
    else:
        print(f"fetching Coinbase hourly candles {START:%Y-%m-%d} -> {END:%Y-%m-%d} ...", flush=True)
        p = panel.build_coinbase(UNIVERSE, days=DAYS, granularity=3600,
                                 fetch=lambda prod, days, gran: data.fetch(prod, days, gran, end=END))
        p = p.slice(None, END.replace(tzinfo=None) - pd.Timedelta(hours=1))
    p.save(directory)
    print(f"{len(p.coins)} coins, {len(p.index)} hours; not loaded: {sorted(p.errors) or 'none'}")
    return p


def masks(p: panel.MarketPanel):
    base = panel.eligible(p, min_history=MIN_HISTORY, min_dollar_volume=MIN_DOLLAR_VOLUME,
                          volume_window=VOLUME_WINDOW)
    base["BTC"] = False
    peers = base.copy()
    eth = base.copy()
    for c in eth.columns:
        if c not in ETH_GROUP:
            eth[c] = False
    eth.loc[eth.sum(axis=1) < ETH_MIN_COINS] = False      # too few to rank: not evaluated
    return peers, eth


def factor_sets(peers_mask: pd.DataFrame):
    peers = {
        "push_peers": lambda p: fz.push_peers(p, peers_mask, 1, BETA_WINDOW),
        "push_peers_3h": lambda p: fz.push_peers(p, peers_mask, 3, BETA_WINDOW),
        "gap_peers": lambda p: fz.gap_peers(p, peers_mask, 1, BETA_WINDOW),
        "gap_peers_raw": lambda p: fz.gap_peers(p, peers_mask, 1, scaled=False),
        "push_btc": lambda p: fz.push(p, 1, BETA_WINDOW, "BTC"),
        "rev_1": fz.rev_1,
        "rev_3": fz.rev_3,
    }
    eth = {
        "push_eth": lambda p: fz.push(p, 1, BETA_WINDOW, "ETH"),
        "push_eth_3h": lambda p: fz.push(p, 3, BETA_WINDOW, "ETH"),
        "gap_eth": lambda p: fz.leadlag_beta(p, 1, BETA_WINDOW, "ETH"),
        "gap_eth_raw": lambda p: fz.leadlag(p, 1, "ETH"),
        "push_btc": lambda p: fz.push(p, 1, BETA_WINDOW, "BTC"),
        "rev_1": fz.rev_1,
        "rev_3": fz.rev_3,
    }
    return peers, eth


def judge(p, label, primary, raw, facs, mask, q) -> dict:
    tables = {h: fe.evaluate(p, names=list(facs), horizon=h, q=q, mask=mask, n_splits=N_SPLITS,
                             embargo=EMBARGO, factors=facs, min_train=MIN_TRAIN)
              for h in HORIZONS}
    t = tables[PRIMARY_H]
    print(f"\n### {label}: factor table at {PRIMARY_H}h (purged {N_SPLITS}-block walk-forward, "
          f"{EMBARGO}h embargo, {MIN_TRAIN}h minimum training, {q} quantiles)\n")
    print("```")
    print(fe.format_table(t))
    print("```")
    print(f"splits: {t.attrs['splits']}")
    same = abs(t.loc[raw, "t_oos"] - t.loc["rev_1", "t_oos"]) < 1e-9
    print(f"check: {raw} t={t.loc[raw, 't_oos']:.4f} vs rev_1 t={t.loc['rev_1', 't_oos']:.4f} "
          f"(identical by construction: {same})")

    fwd = fe.forward_returns(p.close, PRIMARY_H)
    regs = {primary: ops.where_valid(facs[primary](p), mask), "rev_1": ops.where_valid(fz.rev_1(p), mask)}
    coef = fe.fama_macbeth(fwd, regs).reindex(t.attrs["test_dates"]).dropna()
    fm = fe.summarize(coef[primary], 2 * (PRIMARY_H - 1))
    fm_rev = fe.summarize(coef["rev_1"], 2 * (PRIMARY_H - 1))
    print(f"\nFama-MacBeth at {PRIMARY_H}h, {fm.n} test hours: {primary} coef {fm.mean:+.4f} "
          f"t {fm.t:.2f} (NW {fm.t_nw:.2f}); rev_1 coef {fm_rev.mean:+.4f} t {fm_rev.t:.2f} (NW {fm_rev.t_nw:.2f})")

    r = t.loc[primary]
    bps = 1e4 * r["spread_oos"]
    crit = [
        ("OOS rank IC t > 3", f"{r['t_oos']:.2f} (NW {r['t_oos_nw']:.2f})", r["t_oos"] > T_HURDLE),
        ("Fama-MacBeth t > 3 with rev_1", f"{fm.t:.2f} (NW {fm.t_nw:.2f})", fm.t > T_HURDLE),
        ("top-bottom spread > 10 bps", f"{bps:+.1f} bps", r["spread_oos"] > SPREAD_HURDLE),
        ("hit rate > 0.52", f"{r['hit_oos']:.3f}", r["hit_oos"] > HIT_HURDLE),
    ]
    print(f"\n#### criteria for {primary} at {PRIMARY_H}h\n")
    print("| criterion | actual | met |")
    print("|---|---|---|")
    for name, actual, met in crit:
        print(f"| {name} | {actual} | {'yes' if met else '**no**'} |")
    passed = all(m for _, _, m in crit)
    print(f"\nverdict for {label}: {'PASS' if passed else 'FAIL'}")
    print(f"spread net of one round trip per {PRIMARY_H}h: Hyperliquid taker {bps - 1e4 * COST_TAKER:+.1f} bps · "
          f"maker {bps - 1e4 * COST_MAKER:+.1f} bps")

    print(f"\n{primary} across horizons (information):\n")
    print("| horizon | IC oos | t oos | t NW | hit | top-bottom |")
    print("|---|---|---|---|---|---|")
    for h in HORIZONS:
        x = tables[h].loc[primary]
        print(f"| {h}h | {x['ic_oos']:+.4f} | {x['t_oos']:.2f} | {x['t_oos_nw']:.2f} | {x['hit_oos']:.2f} | "
              f"{1e4 * x['spread_oos']:+.1f} bps |")
    f = ops.where_valid(facs[primary](p), mask)
    print(f"\nIC decay of {primary} (mean IC, full window):")
    print(fe.ic_decay(f, p.close, horizons=(1, 2, 3, 6, 12, 24)).round(4).to_string())
    return {"passed": passed, "n_compared": len(facs) * len(HORIZONS)}


def run(p: panel.MarketPanel, title: str) -> list:
    peers_mask, eth_mask = masks(p)
    print(f"\n## {title}")
    print(f"window {p.index[0]} -> {p.index[-1]}, {len(p.index)} hours")
    print(f"eligible in the last hour: {int(peers_mask.iloc[-1].sum())} peers; "
          f"{int(eth_mask.iloc[-1].sum())} of the ETH group "
          f"(listed: {sorted(c for c in ETH_GROUP if c in p.coins)}; "
          f"hours with >= {ETH_MIN_COINS} eligible: {int(eth_mask.any(axis=1).sum())})")
    peers, eth = factor_sets(peers_mask)
    return [judge(p, "#16 peer basket", "push_peers", "gap_peers_raw", peers, peers_mask, 5),
            judge(p, "#17 ETH ecosystem", "push_eth", "gap_eth_raw", eth, eth_mask, 3)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-hl", action="store_true", help="skip the Hyperliquid information table")
    args = ap.parse_args()
    pd.set_option("display.width", 200)

    out = run(load_panel(), f"Coinbase spot, {START:%Y-%m-%d} -> {END:%Y-%m-%d} (the test)")
    n = sum(o["n_compared"] for o in out)
    print(f"\nexpected best |t| among {n} null comparisons: {fe.expected_max_sharpe(n, 1.0):.2f}")
    print(f"\nverdicts: #16 {'PASS' if out[0]['passed'] else 'FAIL'}, #17 {'PASS' if out[1]['passed'] else 'FAIL'}")
    if not args.no_hl:
        run(load_panel(fetch_hl=True), "Hyperliquid perps, last ~208 days (information only, overlaps #9b)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

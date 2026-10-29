"""Hypothesis #15 — multi-asset trend, sized by volatility.

    python research/trend.py --fetch     # the one fetch: writes data/trend/, then runs
    python research/trend.py             # reruns offline from the committed snapshot

The rule is frozen in research/PREREGISTRATION_TREND.md and lives in
espero/trend.py; this script owns only the loop, the benchmarks and the
report. It prints the pre-registered criteria; it does not decide. The verdict
is written by hand into RESULTS_TREND.md.
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import data, trend  # noqa: E402
from espero import factor_eval as fe  # noqa: E402

SNAPSHOT = ROOT / "data" / "trend"
SPAN = "10y"
NW_LAGS = 13
T_HURDLE = 1.28
SPLIT = pd.Timestamp("2022-01-01")
NO_ALTS = {**trend.CLASSES, "crypto": trend.MAJORS}
NO_CRYPTO = {k: v for k, v in trend.CLASSES.items() if k != "crypto"}
ALTS_FIFTH = {**trend.CLASSES, "crypto": trend.MAJORS, "alts": (trend.ALTS,)}


@dataclass
class Run:
    name: str
    equity: pd.Series          # at every daily cutoff
    gross: pd.Series           # invested share of equity at every cutoff
    book: trend.Book
    alts: pd.DataFrame         # per decision: eligible alts and why the others were not


# ----------------------------------------------------------------------- data
def fetch(directory: Path = SNAPSHOT) -> List[str]:
    """The one fetch. Every symbol the rule can hold, plus BIL for the cash variant."""
    directory.mkdir(parents=True, exist_ok=True)
    failed = []
    for sym in trend.symbols() + [trend.CASH_PROXY]:
        try:
            df = data.yahoo_daily(sym, SPAN, adjusted=True)
        except data.FetchError as exc:
            failed.append(f"{sym}: {exc}")
            continue
        df.to_csv(directory / f"{sym}.csv", index=False)
    return failed


def load(directory: Path = SNAPSHOT) -> Dict[str, pd.DataFrame]:
    return {p.stem: trend.to_frame(pd.read_csv(p)) for p in sorted(Path(directory).glob("*.csv"))}


# ------------------------------------------------------------------ simulator
def simulate(frames: Dict[str, pd.DataFrame], start=trend.START, end=trend.END, mode: str = "trend",
             cost_mult: float = 1.0, horizons: Sequence[int] = trend.HORIZONS,
             classes=trend.CLASSES, band: float = trend.BAND, cash_yield: bool = False,
             name: Optional[str] = None) -> Run:
    """Every day: book the fills whose bars have closed, mark, and on Mondays decide.
    The run is assumed on time (07:30 New York), as the pre-registration says."""
    book = trend.Book(cash=1.0)
    cash_frame = frames.get(trend.CASH_PROXY) if cash_yield else None
    days = pd.date_range(trend.cutoff(start), trend.cutoff(end), freq="D")
    eq, gross, alts = [], [], []
    for d in days:
        book.fill(frames, d, cost_mult)
        e = book.mark(frames, d, cash_frame)
        eq.append(e)
        gross.append(sum(book.values.values()) / e if e else 0.0)
        if d.weekday() == 0:
            dec = trend.decide(frames, d, mode, horizons, classes)
            book.rebalance(dec, frames, trend.run_moment(d), band)
            why = [v.why for s, v in dec.views.items() if v.member == trend.ALTS]
            alts.append({"date": d, "eligible": why.count(""), "liquidity": why.count("liquidity"),
                         "history": why.count("history"), "stale": why.count("stale"),
                         "no data": why.count("no data")})
    return Run(name or mode, pd.Series(eq, index=days), pd.Series(gross, index=days), book,
               pd.DataFrame(alts).set_index("date") if alts else pd.DataFrame())


def buy_and_hold(frames: Dict[str, pd.DataFrame], sym: str, start=trend.START, end=trend.END) -> pd.Series:
    days = pd.date_range(trend.cutoff(start), trend.cutoff(end), freq="D")
    px = pd.Series([trend.last_adj(frames[sym], d) for d in days], index=days, dtype=float)
    return px / px.iloc[0]


# -------------------------------------------------------------------- metrics
def weekly(eq: pd.Series) -> pd.Series:
    return eq[eq.index.day_of_week == 0].pct_change().dropna()


def sharpe(r: pd.Series) -> float:
    s = r.std()
    return float(r.mean() / s * math.sqrt(52)) if s > 0 else 0.0


def cagr(eq: pd.Series) -> float:
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    return float((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1)


def maxdd(eq: pd.Series) -> float:
    return float((eq / eq.cummax() - 1).min())


def stats(run: Run) -> dict:
    eq = run.equity
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    r = weekly(eq)
    return {"cagr": cagr(eq), "sharpe": sharpe(r), "maxdd": maxdd(eq), "vol": float(r.std() * math.sqrt(52)),
            "turnover": run.book.traded / float(eq.mean()) / years, "trades": run.book.trades,
            "costs": run.book.costs, "gross": float(run.gross.mean()), "late": run.book.late}


def criteria(tr: Run, vol: Run, sixty: Run, tr2x: Run) -> List[tuple]:
    rt, rv = weekly(tr.equity), weekly(vol.equity)
    k = min(1.0, float(rt.std() / rv.std()))
    e = rt - k * rv
    t = fe.newey_west_t(e, NW_LAGS)
    blend = (1 + k * vol.equity.pct_change().fillna(0.0)).cumprod()
    s_tr, s_6040 = sharpe(rt), sharpe(weekly(sixty.equity))
    dd_tr, dd_blend = maxdd(tr.equity), maxdd(blend)
    c2x = cagr(tr2x.equity)
    return [
        ("1", "trend adds return beyond vol sizing",
         f"mean(e) > 0 and NW t >= {T_HURDLE}",
         f"k {k:.3f}; mean(e) {1e4 * e.mean():+.2f} bps/wk; NW t {t:.2f}", e.mean() > 0 and t >= T_HURDLE),
        ("2", "trend protects beyond vol sizing", f"max DD > {100 * dd_blend:.2f}%",
         f"{100 * dd_tr:.2f}%", dd_tr > dd_blend),
        ("3", "beats 60/40", f"Sharpe > {s_6040:.2f}", f"{s_tr:.2f}", s_tr > s_6040),
        ("4", "survives doubled costs", "CAGR > 0", f"{100 * c2x:+.2f}%", c2x > 0),
    ]


# --------------------------------------------------------------------- report
def row(name: str, s: dict) -> str:
    return (f"| {name} | {100 * s['cagr']:+.2f}% | {s['sharpe']:.2f} | {100 * s['maxdd']:.2f}% | "
            f"{100 * s['vol']:.1f}% | {s['turnover']:.2f}x | {s['trades']} | {100 * s['costs']:.2f}% | "
            f"{100 * s['gross']:.0f}% |")


def eq_row(name: str, eq: pd.Series) -> str:
    r = weekly(eq)
    return (f"| {name} | {100 * cagr(eq):+.2f}% | {sharpe(r):.2f} | {100 * maxdd(eq):.2f}% | "
            f"{100 * r.std() * math.sqrt(52):.1f}% | | | | |")


HEADER = ("| book | CAGR | Sharpe | max DD | vol | turnover/yr | trades | costs | avg gross |\n"
          "|---|---|---|---|---|---|---|---|---|")


def class_of(sym: str) -> str:
    for cls, members in trend.CLASSES.items():
        if sym in members or (trend.ALTS in members and sym in trend.ALT_COINS):
            return "alts" if sym in trend.ALT_COINS else cls
    return "other"


def report(frames: Dict[str, pd.DataFrame]) -> None:
    print(f"snapshot: {len(frames)} series in {SNAPSHOT.relative_to(ROOT)}")
    print("| symbol | first | last | rows |\n|---|---|---|---|")
    for sym in trend.symbols() + [trend.CASH_PROXY]:
        f = frames.get(sym)
        print(f"| {sym} | {f.index[0].date()} | {f.index[-1].date()} | {len(f)} |" if f is not None
              else f"| {sym} | missing | | |")

    runs = {
        "trend": simulate(frames),
        "volonly": simulate(frames, mode="volonly"),
        "static": simulate(frames, mode="static"),
        "6040": simulate(frames, mode="6040"),
        "trend 2x costs": simulate(frames, cost_mult=2.0, name="trend 2x costs"),
    }
    print(f"\n## Books, decisions {trend.START.date()} → {trend.END.date()}\n")
    print(HEADER)
    for name in ("trend", "volonly", "static", "6040"):
        print(row(f"**{name}**" if name == "trend" else name, stats(runs[name])))

    print("\n## Pre-registered criteria\n")
    print("| # | criterion | required | actual | met |\n|---|---|---|---|---|")
    crit = criteria(runs["trend"], runs["volonly"], runs["6040"], runs["trend 2x costs"])
    for num, what, req, act, met in crit:
        print(f"| {num} | {what} | {req} | {act} | {'yes' if met else '**no**'} |")
    print(f"\nall four met: {'yes' if all(c[4] for c in crit) else 'no'}")

    print("\n## Information only\n")
    print(HEADER)
    info = [
        ("trend 2x costs", runs["trend 2x costs"]),
        ("trend 3x costs", simulate(frames, cost_mult=3.0)),
        ("28-day lookback alone", simulate(frames, horizons=(28,))),
        ("91-day lookback alone", simulate(frames, horizons=(91,))),
        ("364-day sign alone (≈ #4)", simulate(frames, horizons=(364,))),
        ("no crypto (budgets 1/3)", simulate(frames, classes=NO_CRYPTO)),
        ("no alts", simulate(frames, classes=NO_ALTS)),
        ("alts as a fifth class", simulate(frames, classes=ALTS_FIFTH)),
        ("no band", simulate(frames, band=0.0)),
        ("idle cash earns BIL", simulate(frames, cash_yield=True)),
    ]
    for name, run in info:
        print(row(name, stats(run)))
    for sym in ("SPY", "BTC-USD"):
        print(eq_row(f"{sym} buy-and-hold", buy_and_hold(frames, sym)))

    tr = runs["trend"]
    print("\n## Trend book: P&L by class (share of starting equity, after costs)\n")
    print("| class | P&L |\n|---|---|")
    by = {}
    for sym, p in tr.book.pnl.items():
        by[class_of(sym)] = by.get(class_of(sym), 0.0) + p
    for cls in ("equity", "bonds", "commodities", "crypto", "alts", "other"):
        if cls in by:
            print(f"| {cls} | {100 * by[cls]:+.2f}% |")

    print("\n## Trend book by period\n")
    print(HEADER)
    for label, part in (("2018–2021", tr.equity[tr.equity.index < SPLIT]),
                        ("2022–2026", tr.equity[tr.equity.index >= SPLIT])):
        print(eq_row(label, part))

    a = tr.alts
    first = a.index[a["eligible"] > 0][0].date() if (a["eligible"] > 0).any() else None
    print("\n## Altcoin sleeve eligibility (per decision)\n")
    print(f"first decision with an eligible alt: {first}; eligible alts: mean {a['eligible'].mean():.1f}, "
          f"last {int(a['eligible'].iloc[-1])} of {len(trend.ALT_COINS)}")
    print(f"the $1M liquidity filter excluded a coin on {int((a['liquidity'] > 0).sum())} of {len(a)} decisions "
          f"(max {int(a['liquidity'].max())} coins at once)")
    print(f"late fills: {tr.book.late}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="the one fetch: write data/trend/ first")
    args = ap.parse_args()
    if args.fetch:
        failed = fetch()
        print(f"fetched into {SNAPSHOT.relative_to(ROOT)}; failed: {failed or 'none'}")
    if not SNAPSHOT.exists():
        print("no snapshot: run with --fetch once", file=sys.stderr)
        return 2
    report(load())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

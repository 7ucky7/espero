"""Command line entry point: `python -m espero ...` or the `espero` script."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import data
from .backtest import Config, run
from .journal import Journal
from .paper import PaperConfig, PaperTrader
from .report import buy_and_hold, equity_png, format_matrix, matrix


def _cmd_fetch(args: argparse.Namespace) -> int:
    print(f"fetching {args.product} {args.granularity}s x {args.days}d ...")
    df = data.fetch(args.product, args.days, args.granularity)
    out = Path(args.out) if args.out else data.candle_path(args.product, args.granularity)
    data.save(df, out)
    print(f"{len(df)} candles -> {out}")
    print(f"{df['time'].iloc[0]} .. {df['time'].iloc[-1]}")
    return 0


def _load(path: str):
    p = Path(path)
    if not p.exists():
        print(f"no data at {p}. run: espero fetch BTC-USD --days 1460", file=sys.stderr)
        return None
    return data.load(p)


def _cmd_backtest(args: argparse.Namespace) -> int:
    df = _load(args.data)
    if df is None:
        return 2
    cfg = Config(fee=args.fee_bps / 1e4, timing=args.timing, sizing=args.sizing)
    m = run(df, cfg).metrics()
    width = max(len(k) for k in m)
    for k, v in m.items():
        print(f"{k:<{width}}  {v:.4f}" if isinstance(v, float) else f"{k:<{width}}  {v}")
    return 0


def _cmd_matrix(args: argparse.Namespace) -> int:
    df = _load(args.data)
    if df is None:
        return 2
    print(f"{len(df)} bars  {df['dt'].iloc[0].date()} .. {df['dt'].iloc[-1].date()}\n")
    print(format_matrix(matrix(df), buy_and_hold(df)))
    return 0


def _cmd_chart(args: argparse.Namespace) -> int:
    df = _load(args.data)
    if df is None:
        return 2
    out = equity_png(df, Path(args.out))
    print(f"wrote {out}")
    return 0


def _cmd_paper(args: argparse.Namespace) -> int:
    from .data import recent_closed_bars

    journal = Journal(args.state)
    cfg = PaperConfig(product=args.product, granularity=args.granularity,
                      initial=args.cash, fee=args.fee_bps / 1e4)
    trader = PaperTrader(journal, cfg)

    def step() -> None:
        df = recent_closed_bars(args.product, args.granularity, args.seed)
        if df.empty:
            print("no candles returned")
            return
        known = journal.last_bar_ts(args.product) or 0
        fresh = [r for r in df.to_dict("records") if int(r["ts"]) > known]
        if not fresh:
            print("no new closed bar")
            return
        # seed history silently, trade only the most recent closed bar
        for bar in fresh[:-1]:
            journal.add_bar(args.product, bar)
        print(f"bar {fresh[-1]['dt']} close={fresh[-1]['close']:.2f}")
        for event in trader.on_bar(fresh[-1]):
            print("  ", event)
        print(f"   cash={trader.cash:.2f}  equity={trader._equity(float(fresh[-1]['close'])):.2f}")

    if args.loop:
        print(f"paper trading {args.product} {args.granularity}s -> {args.state} "
              f"(ctrl-c to stop)")
        try:
            while True:
                step()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("stopped")
        finally:
            journal.close()
        return 0

    step()
    journal.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="espero", description="small honest crypto research harness")
    p.add_argument("--version", action="version", version="espero 0.1.0")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="download public Coinbase candles to CSV")
    f.add_argument("product", nargs="?", default="BTC-USD")
    f.add_argument("--days", type=int, default=1460)
    f.add_argument("--granularity", type=int, default=86400)
    f.add_argument("-o", "--out", default=None)
    f.set_defaults(func=_cmd_fetch)

    b = sub.add_parser("backtest", help="run one configuration")
    b.add_argument("data", nargs="?", default="data/BTCUSD_86400s.csv")
    b.add_argument("--fee-bps", type=float, default=10.0)
    b.add_argument("--timing", choices=["next_bar", "same_bar"], default="next_bar")
    b.add_argument("--sizing", choices=["risk2pct", "full"], default="full")
    b.set_defaults(func=_cmd_backtest)

    m = sub.add_parser("matrix", help="the audit table: timing x fees x sizing")
    m.add_argument("data", nargs="?", default="data/BTCUSD_86400s.csv")
    m.set_defaults(func=_cmd_matrix)

    pp = sub.add_parser("paper", help="run the paper trader against live candles")
    pp.add_argument("--product", default="BTC-USD")
    pp.add_argument("--granularity", type=int, default=3600)
    pp.add_argument("--state", default="paper.db")
    pp.add_argument("--cash", type=float, default=500.0)
    pp.add_argument("--fee-bps", type=float, default=0.0)
    pp.add_argument("--seed", type=int, default=300, help="bars of history to keep")
    pp.add_argument("--loop", action="store_true")
    pp.add_argument("--interval", type=float, default=60.0)
    pp.set_defaults(func=_cmd_paper)

    c = sub.add_parser("chart", help="write the equity curve PNG")
    c.add_argument("data", nargs="?", default="data/BTCUSD_86400s.csv")
    c.add_argument("-o", "--out", default="docs/equity.png")
    c.set_defaults(func=_cmd_chart)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

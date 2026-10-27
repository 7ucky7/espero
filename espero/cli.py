"""Command line entry point: `python -m espero ...` or the `espero` script."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import data
from .backtest import Config, run
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

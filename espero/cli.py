"""Command line entry point: `python -m espero ...` or the `espero` script."""
from __future__ import annotations

import argparse
import pathlib
import sys
import time
from pathlib import Path

from . import dashboard as dash
from . import data
from . import features as fx
from . import tsmom as tsm
from . import xs as xsm
from .backtest import Config, run
from .broker import BrokerError, broker_from_env
from .journal import Journal
from .live import LiveConfig, LiveTrader
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


def _cmd_live(args: argparse.Namespace) -> int:
    from .data import recent_closed_bars

    try:
        broker = broker_from_env(dry_run=not args.confirm_live)
    except BrokerError as exc:
        print(f"cannot start: {exc}", file=sys.stderr)
        return 2

    journal = Journal(args.state)
    cfg = LiveConfig(product=args.product, granularity=args.granularity,
                     max_notional=args.max_notional, max_daily_loss=args.max_daily_loss)
    trader = LiveTrader(journal, broker, cfg, kill_file=args.kill_file)

    print(f"broker   {broker.name}   live={broker.live}")
    print(f"product  {args.product} {args.granularity}s")
    try:
        print(f"price    {broker.price(args.product):.2f}")
        print(f"balance  {broker.balance(cfg.quote_currency):.2f} {cfg.quote_currency}")
    except Exception as exc:  # noqa: BLE001 - surface credential problems plainly
        print(f"credential check failed: {exc}", file=sys.stderr)
        journal.close()
        return 2
    if not broker.live:
        print("mode     DRY RUN - orders are logged, never sent")

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
        for bar in fresh[:-1]:
            journal.add_bar(args.product, bar)
        print(f"bar {fresh[-1]['dt']} close={fresh[-1]['close']:.2f}")
        for event in trader.on_bar(fresh[-1]):
            print("  ", event)

    if args.loop:
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


def _cmd_features(args: argparse.Namespace) -> int:
    if args.source == "hl":
        df, col, name = fx.hyperliquid_funding(pages=args.pages), "funding", "hl_funding_btc"
    elif args.source == "okx":
        df, col, name = fx.okx_funding(pages=args.pages), "funding", "okx_funding_btc"
    else:
        if not args.token:
            print("--token is required for --source poly", file=sys.stderr)
            return 2
        df, col, name = fx.polymarket_history(args.token), "prob", f"poly_{args.token[:10]}"

    if df.empty:
        print("no data returned", file=sys.stderr)
        return 2
    n = fx.save(args.out, name, df, col)
    print(f"{n} rows -> {args.out} [{name}]")
    print(f"range {int(df['ts'].min())} .. {int(df['ts'].max())}")
    return 0


def _cmd_tsmom(args: argparse.Namespace) -> int:
    res = tsm.run(args.state, args.cash, force=args.force, span=args.span,
                  deposit=args.deposit)
    if args.report:
        for row in reversed(res["account"].history(args.limit)):
            print(f"{row['ts']:>12d}  equity {row['equity']:8.2f}  {row['note']}")
        return 0
    print(tsm.format_report(res))
    return 0


def _cmd_dashboard(args: argparse.Namespace) -> int:
    out = dash.write(args.out, tsmom_db=pathlib.Path(args.tsmom_db),
                     paper_db=pathlib.Path(args.paper_db),
                     live_db=pathlib.Path(args.live_db),
                     xs_db=pathlib.Path(args.xs_db))
    print(f"wrote {out}")
    if args.open:
        import subprocess
        subprocess.run(["open", str(out)], check=False)
    return 0


def _cmd_daily(args: argparse.Namespace) -> int:
    from .runner import run_daily

    try:
        res = run_daily(state_dir=Path(args.state_dir), cash_tsmom=args.cash_tsmom,
                        cash_xs=args.cash_xs, force=args.force, dry_run=args.dry_run,
                        notify=not args.no_notify)
    except RuntimeError as exc:   # the lock is held by a live run
        print(f"cannot start: {exc}", file=sys.stderr)
        return 3
    for name, step in res.steps.items():
        status = "skip" if step.skipped else ("ok" if step.ok else "FAIL")
        extra = step.error or step.note
        print(f"{name:<10s} {status:<5s} {step.seconds:5.1f}s  {extra}")
    if res.paused:
        print("paused: KILL file present")
    return res.exit_code


def _cmd_factors(args: argparse.Namespace) -> int:
    from . import factor_eval as fe
    from . import panel as pnl

    if args.panel and Path(args.panel).exists() and not args.refresh:
        p = pnl.MarketPanel.load(args.panel)
        print(f"panel from {args.panel}: {len(p.coins)} coins, {len(p.index)} days")
    else:
        print(f"building panel ({len(xsm.UNIVERSE)} coins, {args.span}) ...")
        p = pnl.build(span=args.span)
        if args.panel:
            p.save(args.panel)
            print(f"saved to {args.panel}")
        if p.errors:
            print(f"{len(p.errors)} coins failed: {', '.join(sorted(p.errors))}")
    mask = pnl.eligible(p, min_history=args.min_history, min_dollar_volume=args.min_dollar_volume)
    names = args.names.split(",") if args.names else None
    t = fe.evaluate(p, names=names, horizon=args.horizon, mask=mask, n_splits=args.splits)
    print(f"\n{len(p.index)} days · horizon {args.horizon}d · eligible today: {int(mask.iloc[-1].sum())}\n")
    print(fe.format_table(t))
    if args.out:
        t.to_csv(args.out)
        print(f"\nwrote {args.out}")
    return 0


def _cmd_xs(args: argparse.Namespace) -> int:
    res = xsm.run(args.state, args.cash, force=args.force, deposit=args.deposit)
    print(xsm.format_report(res))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="espero", description="small honest crypto research harness")
    p.add_argument("--version", action="version", version="espero 0.2.0")
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

    ft = sub.add_parser("features", help="fetch point-in-time features into SQLite")
    ft.add_argument("--source", choices=["hl", "okx", "poly"], default="hl")
    ft.add_argument("--out", default="features.db")
    ft.add_argument("--pages", type=int, default=70)
    ft.add_argument("--token", default="", help="Polymarket CLOB token id")
    ft.set_defaults(func=_cmd_features)

    lv = sub.add_parser("live", help="trade a real account (dry-run unless confirmed)")
    lv.add_argument("--product", default="BTC-USD")
    lv.add_argument("--granularity", type=int, default=3600)
    lv.add_argument("--state", default="live.db")
    lv.add_argument("--seed", type=int, default=300)
    lv.add_argument("--max-notional", type=float, default=25.0)
    lv.add_argument("--max-daily-loss", type=float, default=15.0)
    lv.add_argument("--kill-file", default="KILL")
    lv.add_argument("--loop", action="store_true")
    lv.add_argument("--interval", type=float, default=60.0)
    lv.add_argument("--confirm-live", action="store_true",
                    help="actually send orders (also needs ESPERO_ALLOW_LIVE=1)")
    lv.set_defaults(func=_cmd_live)

    tm = sub.add_parser("tsmom", help="cross-asset trend paper account")
    tm.add_argument("--state", default="tsmom.db")
    tm.add_argument("--cash", type=float, default=100.0)
    tm.add_argument("--span", default="2y", help="yahoo history window")
    tm.add_argument("--force", action="store_true", help="rebalance now regardless of the calendar")
    tm.add_argument("--deposit", type=float, default=0.0, help="add cash, then deploy it")
    tm.add_argument("--report", action="store_true", help="print account history")
    tm.add_argument("--limit", type=int, default=30)
    tm.set_defaults(func=_cmd_tsmom)

    xs_p = sub.add_parser("xs", help="weekly cross-sectional top-N crypto paper account")
    xs_p.add_argument("--state", default="xs.db")
    xs_p.add_argument("--cash", type=float, default=100.0)
    xs_p.add_argument("--deposit", type=float, default=0.0)
    xs_p.add_argument("--force", action="store_true")
    xs_p.set_defaults(func=_cmd_xs)

    fc = sub.add_parser("factors", help="rank-IC evaluation of the factor zoo on the crypto panel")
    fc.add_argument("--panel", default="data/panel", help="CSV panel directory (built if missing)")
    fc.add_argument("--refresh", action="store_true", help="re-download even if the panel exists")
    fc.add_argument("--span", default="5y")
    fc.add_argument("--horizon", type=int, default=5, help="forward-return horizon in days")
    fc.add_argument("--splits", type=int, default=4, help="purged walk-forward test blocks")
    fc.add_argument("--min-history", type=int, default=365)
    fc.add_argument("--min-dollar-volume", type=float, default=1e6)
    fc.add_argument("--names", default="", help="comma-separated subset of the zoo")
    fc.add_argument("-o", "--out", default="", help="write the table as CSV")
    fc.set_defaults(func=_cmd_factors)

    dy = sub.add_parser("daily", help="the scheduled run: tsmom -> xs -> dashboard -> health.json")
    dy.add_argument("--state-dir", default=".", help="where the .db files, dashboard and health live")
    dy.add_argument("--cash-tsmom", type=float, default=100.0)
    dy.add_argument("--cash-xs", type=float, default=100.0)
    dy.add_argument("--force", action="store_true", help="rebalance both accounts now")
    dy.add_argument("--dry-run", action="store_true", help="preflight: no network, no account changes")
    dy.add_argument("--no-notify", action="store_true")
    dy.set_defaults(func=_cmd_daily)

    d = sub.add_parser("dashboard", help="static HTML dashboard for the paper accounts")
    d.add_argument("-o", "--out", default="dashboard.html")
    d.add_argument("--tsmom-db", default="tsmom.db")
    d.add_argument("--paper-db", default="paper.db")
    d.add_argument("--live-db", default="live.db")
    d.add_argument("--xs-db", default="xs.db")
    d.add_argument("--open", action="store_true")
    d.set_defaults(func=_cmd_dashboard)

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

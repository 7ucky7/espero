"""Exploration, not a test: liquidations against price, April-June 2026.

aggr's public server (api.aggr.trade, github.com/Tucsky/aggr-server) keeps hourly
bars from 2026-04-01 with the dollars of shorts (`lbuy`) and longs (`lsell`)
liquidated in each, for the markets it records: 14 of our coins on Binance
futures, Bybit and OKX. It is one person's free server, so the download is a few
dozen requests, paced, and saved.

The months are split before anything is looked at:

* **April-June** is explored here: charts of price with the liquidations under it,
  and which way price went after the biggest liquidation hours
* **July-October** is downloaded now (aggr may drop old bars) and sealed: its files
  and their SHA-256 go into research/aggr_holdout_manifest.json, and nothing here
  reads them. They are the test for whatever this suggests, once it is written down.

    python research/aggr_explore.py           # download (cached in data/aggr/), explore, draw
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import io
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "aggr"
OUT = ROOT / "research" / "aggr_explore"
MANIFEST = ROOT / "research" / "aggr_holdout_manifest.json"
API = "https://api.aggr.trade/historical/{start}/{end}/3600000/{markets}"
EXPLORE = ["2026-04", "2026-05", "2026-06"]
HOLDOUT = ["2026-07", "2026-08", "2026-09", "2026-10"]
HOLDOUT_FROM = pd.Timestamp("2026-07-01", tz="UTC")
HOLDOUT_TO = pd.Timestamp("2026-10-29", tz="UTC")       # the last full day before the download
PACE_S = 3.0
SPIKE_Q = 0.98            # a spike: an hour in the top 2% of the coin's own liquidation share
GAP_H = 6                 # one cascade, one event: spikes within 6 hours of the last are the same one
HORIZONS = (1, 4, 24)
COLUMNS = ["time", "market", "open", "high", "low", "close", "vbuy", "vsell", "cbuy", "csell", "lbuy", "lsell"]

# the markets aggr records for our universe (its /products list, 2026-10-29): price and
# volume from Binance futures (SHIB from OKX), liquidations summed over every venue
COINS: Dict[str, Dict[str, List[str]]] = {}
for c, venues in {"BTC": "BYO", "ETH": "BYO", "SOL": "BYO", "BNB": "BYO", "XRP": "BO", "ADA": "BYO",
                  "DOGE": "BYO", "AVAX": "BYO", "LINK": "BYO", "TRX": "BO", "LTC": "BYO", "XLM": "BO",
                  "HBAR": "BYO", "SHIB": "O"}.items():
    m = {"B": f"BINANCE_FUTURES:{c.lower()}usdt", "Y": f"BYBIT:{c}USDT", "O": f"OKEX:{c}-USDT-SWAP"}
    COINS[c] = {"price": [m["B"] if "B" in venues else m["O"]], "all": [m[v] for v in venues]}


# ----------------------------------------------------------------- download
def parse(payload: dict) -> pd.DataFrame:
    """aggr's `point` format -> one row per market and hour."""
    cols = payload.get("columns") or {}
    rows = payload.get("results") or []
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    return pd.DataFrame({k: [r[cols[k]] for r in rows] if k in cols else np.nan for k in COLUMNS})


def fetch(month: str, markets: List[str], sleep=time.sleep) -> pd.DataFrame:
    start = pd.Timestamp(f"{month}-01", tz="UTC")
    end = min(start + pd.offsets.MonthBegin(1), HOLDOUT_TO) if month in HOLDOUT else start + pd.offsets.MonthBegin(1)
    url = API.format(start=int(start.timestamp() * 1000), end=int(end.timestamp() * 1000),
                     markets=urllib.parse.quote("+".join(markets), safe=""))
    req = urllib.request.Request(url, headers={"User-Agent": "espero-research (hourly bars, cached once)"})
    with urllib.request.urlopen(req, timeout=120) as r:
        payload = json.load(r)
    if payload.get("error"):
        raise RuntimeError(f"aggr: {payload['error']} ({month}, {len(markets)} markets)")
    sleep(PACE_S)
    df = parse(payload)
    t = pd.to_datetime(df["time"], unit="s", utc=True)
    return df[(t >= start) & (t < end)]


def download() -> None:
    markets = sorted({m for v in COINS.values() for m in v["all"]})
    groups = [markets[i:i + 10] for i in range(0, len(markets), 10)]
    for month in EXPLORE + HOLDOUT:
        part = "explore" if month in EXPLORE else "holdout"
        path = DATA / part / f"{month}.csv.gz"
        if path.exists():
            continue
        frame = pd.concat([fetch(month, g) for g in groups], ignore_index=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        buf = io.StringIO()
        frame.sort_values(["market", "time"]).to_csv(buf, index=False)
        path.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))
        print(f"  {part} {month}: {len(frame)} market-hours", flush=True)
    seal()


def seal() -> None:
    """Checksums of the held-out months, written once: the test reads exactly these."""
    if MANIFEST.exists():
        return
    files = sorted((DATA / "holdout").glob("*.csv.gz"))
    MANIFEST.write_text(json.dumps({
        "sealed": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "why": "held out from research/aggr_explore.py; read only by a pre-registered test",
        "files": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}}, indent=1))


def load_explore() -> pd.DataFrame:
    """The explored months only. A held-out bar here is a bug, not a bonus."""
    frame = pd.concat([pd.read_csv(DATA / "explore" / f"{m}.csv.gz") for m in EXPLORE], ignore_index=True)
    frame["t"] = pd.to_datetime(frame["time"], unit="s", utc=True)
    if (frame["t"] >= HOLDOUT_FROM).any():
        raise RuntimeError("a held-out hour reached the exploration")
    return frame


# ----------------------------------------------------------------- the panel
def panel(raw: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Per coin, hourly: open/close and volume from its price market, liquidations
    summed over all its venues (long = longs liquidated, short = shorts liquidated)."""
    out = {}
    for c, m in COINS.items():
        px = raw[raw["market"] == m["price"][0]].set_index("t").sort_index()
        if px.empty:
            continue
        liq = raw[raw["market"].isin(m["all"])].groupby("t")[["lsell", "lbuy"]].sum()
        df = pd.DataFrame({"open": px["open"], "close": px["close"], "volume": px["vbuy"] + px["vsell"]})
        df = df.join(liq.rename(columns={"lsell": "long", "lbuy": "short"})).fillna({"long": 0.0, "short": 0.0})
        idx = pd.date_range(df.index.min(), df.index.max(), freq="h")
        out[c] = df.reindex(idx)
    return out


def spikes(df: pd.DataFrame, side: str) -> pd.DatetimeIndex:
    """Hours in the coin's top 2% by liquidation share on `side`, the first of each cascade."""
    share = (df[side] / df["volume"]).dropna()
    top = share.nlargest(int(np.ceil(len(share) * (1 - SPIKE_Q))))
    hot = top[top > 0].sort_index().index          # an hour with no liquidation is never a spike
    keep, last = [], None
    for t in hot:
        if last is None or (t - last) > pd.Timedelta(hours=GAP_H):
            keep.append(t)
        last = t
    return pd.DatetimeIndex(keep)


def event_table(p: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for c, df in p.items():
        lc = np.log(df["close"])
        for side in ("long", "short"):
            for t in spikes(df, side):
                i = df.index.get_loc(t)
                r = {"coin": c, "side": side, "t": t, "day": t.strftime("%Y-%m-%d"),
                     "usd": df[side].iat[i], "share": df[side].iat[i] / df["volume"].iat[i],
                     "r0": float(np.log(df["close"].iat[i] / df["open"].iat[i]))}
                for k in HORIZONS:
                    r[f"r{k}"] = float(lc.iat[i + k] - lc.iat[i]) if i + k < len(df) else np.nan
                rows.append(r)
    return pd.DataFrame(rows)


def baseline(p: Dict[str, pd.DataFrame]) -> Dict[int, float]:
    """Mean forward return over every coin-hour: what 'after a spike' is compared with."""
    out = {}
    for k in HORIZONS:
        out[k] = float(np.nanmean(np.concatenate([(np.log(df["close"]).shift(-k) - np.log(df["close"])).to_numpy()
                                                  for df in p.values()])))
    return out


def by_day(x: pd.Series, day: pd.Series) -> dict:
    d = x.groupby(day).mean().dropna()
    n = len(d)
    t = d.mean() / (d.std(ddof=1) / np.sqrt(n)) if n > 1 and d.std(ddof=1) > 0 else np.nan
    return {"mean": float(d.mean()) if n else np.nan, "t": float(t), "days": n}


def paths(p: Dict[str, pd.DataFrame], ev: pd.DataFrame, hourly: float, before: int = 6,
          after: int = 24) -> Dict[str, np.ndarray]:
    """Cumulative log return around the spikes, 0 at the close before the spike hour, net of
    the average hour's drift (`hourly`), and weighted like the table: each day's events
    averaged first, then the days."""
    out = {}
    drift = (np.arange(before + after + 2) - before) * hourly
    for side in ("long", "short"):
        days: Dict[str, list] = {}
        for r in ev[ev["side"] == side].itertuples():
            df = p[r.coin]
            i = df.index.get_loc(r.t)
            if i - before - 1 < 0 or i + after >= len(df):
                continue
            lc = np.log(df["close"].to_numpy()[i - before - 1:i + after + 1])
            days.setdefault(r.day, []).append(lc - lc[before] - drift)
        per_day = [np.nanmean(np.array(v), axis=0) for v in days.values()]
        out[side] = np.nanmean(np.array(per_day), axis=0) if per_day else np.array([])
    return out


# ------------------------------------------------------------------- charts
def _px(v: float) -> str:
    return f"{v:,.0f}" if v >= 1000 else f"{v:,.2f}" if v >= 1 else f"{v:.4g}"


def svg_coin(coin: str, df: pd.DataFrame, ev: pd.DataFrame, w: int = 1100, h: int = 420) -> str:
    """Price on top; liquidations below it: longs liquidated red (down), shorts green (up)."""
    pad, mid = 50, int(h * 0.58)
    x = np.linspace(pad, w - 15, len(df))
    close = df["close"].ffill().to_numpy()
    lo, hi = np.nanmin(close), np.nanmax(close)
    ytop = lambda v: 25 + (hi - v) / (hi - lo) * (mid - 45)                     # noqa: E731
    pts = " ".join(f"{a:.1f},{ytop(b):.1f}" for a, b in zip(x, close) if np.isfinite(b))
    big = max(df["long"].max(), df["short"].max(), 1.0)
    base, half = mid + (h - mid) / 2, (h - mid) / 2 - 12
    bars = []
    for a, lg, sh in zip(x, df["long"].to_numpy(), df["short"].to_numpy()):
        if lg > 0:
            bars.append(f'<line x1="{a:.1f}" y1="{base:.1f}" x2="{a:.1f}" y2="{base + lg / big * half:.1f}" '
                        f'stroke="#d64545" stroke-width="1"/>')
        if sh > 0:
            bars.append(f'<line x1="{a:.1f}" y1="{base:.1f}" x2="{a:.1f}" y2="{base - sh / big * half:.1f}" '
                        f'stroke="#2f9e62" stroke-width="1"/>')
    marks = []
    for r in ev[ev["coin"] == coin].itertuples():
        i = df.index.get_loc(r.t)
        color = "#d64545" if r.side == "long" else "#2f9e62"
        marks.append(f'<circle cx="{x[i]:.1f}" cy="{ytop(close[i]):.1f}" r="3.5" fill="none" stroke="{color}" '
                     f'stroke-width="1.5"/>')
    months = []
    for m in pd.date_range(df.index.min().normalize(), df.index.max(), freq="MS"):
        if m < df.index.min():
            continue
        a = x[df.index.get_indexer([m], method="nearest")[0]]
        months.append(f'<line x1="{a:.1f}" y1="20" x2="{a:.1f}" y2="{h - 8}" stroke="#ccc" stroke-dasharray="3,3"/>'
                      f'<text x="{a + 4:.1f}" y="{h - 10}" font-size="11" fill="#666">{m:%b %d}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" font-family="sans-serif">'
            f'<rect width="{w}" height="{h}" fill="white"/>'
            f'<text x="{pad}" y="16" font-size="13" font-weight="bold">{coin}: hourly close, Apr-Jun 2026 '
            f'(circles: the top-2% liquidation hours)</text>'
            f'<text x="{w - 15}" y="16" font-size="11" text-anchor="end" fill="#666">'
            f'{_px(lo)} - {_px(hi)}</text>{"".join(months)}'
            f'<polyline points="{pts}" fill="none" stroke="#333" stroke-width="1"/>{"".join(marks)}'
            f'<line x1="{pad}" y1="{base:.1f}" x2="{w - 15}" y2="{base:.1f}" stroke="#999"/>{"".join(bars)}'
            f'<text x="6" y="{base - half + 8:.1f}" font-size="10" fill="#2f9e62">shorts liq.</text>'
            f'<text x="6" y="{base + half:.1f}" font-size="10" fill="#d64545">longs liq.</text>'
            f'<text x="6" y="{base - 3:.1f}" font-size="10" fill="#666">max ${big / 1e6:,.1f}M</text></svg>')


def svg_paths(pth: Dict[str, np.ndarray], before: int = 6, w: int = 820, h: int = 380) -> str:
    """The average price path around the spikes, in basis points."""
    pad = 55
    allv = np.concatenate([v for v in pth.values() if len(v)]) * 1e4
    lo, hi = min(allv.min(), -5), max(allv.max(), 5)
    n = max(len(v) for v in pth.values())
    xs = lambda i: pad + i / (n - 1) * (w - pad - 20)                        # noqa: E731
    ys = lambda v: 30 + (hi - v) / (hi - lo) * (h - 70)                       # noqa: E731
    lines = []
    for side, color, name in (("long", "#d64545", "longs liquidated"), ("short", "#2f9e62", "shorts liquidated")):
        v = pth[side] * 1e4
        if not len(v):
            continue
        pts = " ".join(f"{xs(i):.1f},{ys(b):.1f}" for i, b in enumerate(v))
        lines.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/>'
                     f'<text x="{xs(n - 1) - 4:.1f}" y="{ys(v[-1]) - 6:.1f}" font-size="11" fill="{color}" '
                     f'text-anchor="end">{name}: {v[-1]:+.0f} bps</text>')
    ticks = "".join(f'<line x1="{xs(i):.1f}" y1="{h - 40}" x2="{xs(i):.1f}" y2="{h - 35}" stroke="#666"/>'
                    f'<text x="{xs(i):.1f}" y="{h - 22}" font-size="10" text-anchor="middle">{i - before - 1:+d}h</text>'
                    for i in range(0, n, 6))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" font-family="sans-serif">'
            f'<rect width="{w}" height="{h}" fill="white"/>'
            f'<text x="{pad}" y="18" font-size="12" font-weight="bold">Price path around the top-2% liquidation '
            f'hours, Apr-Jun 2026 (bps, net of the average hour, each day counted once)</text>'
            f'<line x1="{pad}" y1="{ys(0):.1f}" x2="{w - 20}" y2="{ys(0):.1f}" stroke="#bbb"/>'
            f'<line x1="{xs(before + 1):.1f}" y1="30" x2="{xs(before + 1):.1f}" y2="{h - 40}" stroke="#bbb" '
            f'stroke-dasharray="3,3"/><text x="{xs(before + 1) + 4:.1f}" y="42" font-size="10" fill="#666">'
            f'the spike hour closes</text>{ticks}{"".join(lines)}'
            f'<text x="8" y="{ys(hi) + 4:.1f}" font-size="10">{hi:+.0f}</text>'
            f'<text x="8" y="{ys(lo):.1f}" font-size="10">{lo:+.0f}</text></svg>')


# -------------------------------------------------------------------- report
def main() -> int:
    print("downloading hourly bars from api.aggr.trade (cached in data/aggr/) ...", flush=True)
    download()
    raw = load_explore()
    p = panel(raw)
    ev = event_table(p)
    base = baseline(p)
    span = f"{raw['t'].min():%Y-%m-%d %H:%M} -> {raw['t'].max():%Y-%m-%d %H:%M} UTC"
    print(f"\n## exploration: {len(p)} coins, {span} (July-October sealed, unread)\n")
    print(f"liquidations, all coins and venues: longs ${sum(df['long'].sum() for df in p.values()) / 1e9:,.2f}B, "
          f"shorts ${sum(df['short'].sum() for df in p.values()) / 1e9:,.2f}B")
    print(f"spikes (top 2% of each coin's hours by liquidation share, one per cascade): "
          f"{int((ev['side'] == 'long').sum())} long, {int((ev['side'] == 'short').sum())} short")
    print("\n| after a spike in | n | the spike hour itself | +1h | +4h | +24h |")
    print("|---|---|---|---|---|---|")
    for side, name in (("long", "longs liquidated"), ("short", "shorts liquidated")):
        e = ev[ev["side"] == side]
        cells = [f"{1e4 * by_day(e['r0'], e['day'])['mean']:+.0f} bps"]
        for k in HORIZONS:
            s = by_day(e[f"r{k}"] - base[k], e["day"])
            cells.append(f"{1e4 * s['mean']:+.0f} bps (t {s['t']:.1f})")
        print(f"| {name} | {len(e)} | " + " | ".join(cells) + " |")
    print(f"\nforward returns are in excess of the average hour ({', '.join(f'{k}h {1e4 * v:+.1f} bps' for k, v in base.items())}); "
          "t counts each day once")

    print("\nthe biggest spikes:")
    for r in ev.sort_values("usd", ascending=False).head(8).itertuples():
        print(f"  {r.t:%Y-%m-%d %H:%M} {r.coin:5s} {r.side:5s} ${r.usd / 1e6:6.1f}M ({100 * r.share:.1f}% of volume)  "
              f"hour {1e4 * r.r0:+5.0f} bps  then 1h {1e4 * r.r1:+5.0f}  4h {1e4 * r.r4:+5.0f}  24h {1e4 * r.r24:+5.0f}")

    OUT.mkdir(parents=True, exist_ok=True)
    for c in ("BTC", "ETH", "SOL", "DOGE"):
        (OUT / f"{c.lower()}.svg").write_text(svg_coin(c, p[c], ev))
    (OUT / "paths.svg").write_text(svg_paths(paths(p, ev, base[1])))
    ev.to_csv(OUT / "spikes.csv", index=False, float_format="%.6g")
    print(f"\n-> {OUT.relative_to(ROOT)}/ (btc, eth, sol, doge, paths .svg; spikes.csv)")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())

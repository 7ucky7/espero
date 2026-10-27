"""Market data: Coinbase Exchange public candles, cached as CSV.

No API key is needed for the endpoints used here. They are the *Exchange*
endpoints (api.exchange.coinbase.com), not the retired Coinbase Pro ones.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List

import pandas as pd

BASE = "https://api.exchange.coinbase.com/products/{product}/candles"
DEFAULT_DIR = Path("data")


def candle_path(product: str, granularity: int, directory: Path = DEFAULT_DIR) -> Path:
    return Path(directory) / f"{product.replace('-', '')}_{granularity}s.csv"


def fetch_page(product: str, granularity: int, start: dt.datetime, end: dt.datetime) -> List[list]:
    q = urllib.parse.urlencode({
        "granularity": granularity,
        "start": start.isoformat().replace("+00:00", "Z"),
        "end": end.isoformat().replace("+00:00", "Z"),
    })
    req = urllib.request.Request(BASE.format(product=product) + "?" + q,
                                 headers={"User-Agent": "espero/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch(product: str, days: int, granularity: int = 86400) -> pd.DataFrame:
    """Download `days` of candles, paginating under the 300-candle cap."""
    end = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - dt.timedelta(days=days)
    rows: List[list] = []
    cursor = start
    step = dt.timedelta(seconds=granularity * 280)
    while cursor < end:
        chunk_end = min(cursor + step, end)
        rows.extend(fetch_page(product, granularity, cursor, chunk_end))
        cursor = chunk_end
        time.sleep(0.34)  # public limit is 10 req/s; do not hammer it
    dedup = {int(r[0]): r for r in rows}
    ordered = [dedup[k] for k in sorted(dedup)]
    return pd.DataFrame(
        [
            {
                "time": dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat(),
                "open": op,
                "high": hi,
                "low": lo,
                "close": cl,
                "volume": vol,
            }
            for t, lo, hi, op, cl, vol in ordered
        ]
    )


def save(df: pd.DataFrame, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)


def load(path: Path) -> pd.DataFrame:
    """Load a candle CSV into a sorted, UTC-indexed frame."""
    df = pd.read_csv(path)
    df["dt"] = pd.to_datetime(df["time"], utc=True)
    return df.sort_values("dt").reset_index(drop=True)


def recent_closed_bars(product: str, granularity: int = 3600,
                       limit: int = 300) -> pd.DataFrame:
    """The most recent *completed* candles, oldest first.

    Coinbase returns the in-progress candle too; it is dropped here because a
    bar that can still change must never be treated as closed.
    """
    q = urllib.parse.urlencode({"granularity": granularity})
    req = urllib.request.Request(BASE.format(product=product) + "?" + q,
                                 headers={"User-Agent": "espero/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        rows = json.load(r)
    now = int(time.time())
    done = [r for r in rows if int(r[0]) + granularity <= now]
    done.sort(key=lambda r: r[0])
    done = done[-limit:]
    return pd.DataFrame([
        {"dt": dt.datetime.fromtimestamp(t, dt.timezone.utc), "ts": t,
         "open": op, "high": hi, "low": lo, "close": cl, "volume": vol}
        for t, lo, hi, op, cl, vol in done
    ])


# ---------------------------------------------------------------- other markets
def fred_series(series_id: str) -> pd.DataFrame:
    """Daily series from FRED's public CSV endpoint. No key required.

    Example: DCOILWTICO (WTI spot, Cushing, $/bbl) goes back to 1986.
    """
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "espero/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        text = r.read().decode()
    rows = []
    for line in text.splitlines()[1:]:
        date, _, value = line.partition(",")
        if not value or value in (".", "NA"):
            continue
        try:
            rows.append({"dt": dt.datetime.fromisoformat(date).replace(tzinfo=dt.timezone.utc),
                         "close": float(value)})
        except ValueError:
            continue
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["dt", "open", "high", "low", "close", "volume"])
    df["open"] = df["high"] = df["low"] = df["close"]
    df["volume"] = 0.0
    df["ts"] = (df["dt"].astype("int64") // 1_000_000_000).astype(int)
    return df[["dt", "ts", "open", "high", "low", "close", "volume"]].sort_values("dt").reset_index(drop=True)


def yahoo_daily(symbol: str, span: str = "5y") -> pd.DataFrame:
    """Daily OHLCV from Yahoo's public chart endpoint (futures, ETFs, crypto)."""
    q = urllib.parse.urlencode({"range": span, "interval": "1d"})
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?{q}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    result = payload["chart"]["result"][0]
    ts = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        o, h, l, c = (quote[k][i] for k in ("open", "high", "low", "close"))
        if None in (o, h, l, c):
            continue
        rows.append({
            "dt": dt.datetime.fromtimestamp(t, dt.timezone.utc),
            "ts": int(t),
            "open": float(o), "high": float(h), "low": float(l), "close": float(c),
            "volume": float(quote["volume"][i] or 0),
        })
    return pd.DataFrame(rows).sort_values("dt").reset_index(drop=True)

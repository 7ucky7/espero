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

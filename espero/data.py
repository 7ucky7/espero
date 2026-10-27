"""Market data: Coinbase Exchange public candles, cached as CSV.

No API key is needed for the endpoints used here. They are the *Exchange*
endpoints (api.exchange.coinbase.com), not the retired Coinbase Pro ones.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List, Optional

import pandas as pd

log = logging.getLogger(__name__)

BASE = "https://api.exchange.coinbase.com/products/{product}/candles"
DEFAULT_DIR = Path("data")
CACHE_DIR = Path(os.environ.get("ESPERO_CACHE", "data/cache"))
MAX_CACHE_AGE_DAYS = 3     # older than this, a cached series is not a fallback, it is history
RETRIES = 4
UA = {"User-Agent": "espero/0.1"}


class FetchError(RuntimeError):
    """An HTTP source failed after every retry."""


def http_get(url: str, headers: Optional[dict] = None, timeout: int = 30,
             retries: int = RETRIES, sleep=time.sleep, data: Optional[bytes] = None) -> bytes:
    """GET with bounded exponential backoff and jitter.

    Retries on connection errors, timeouts, 429 and 5xx. A 4xx other than 429
    is not retried: the request is wrong, not the network.
    """
    req = urllib.request.Request(url, headers=headers or UA, data=data)
    last: Optional[Exception] = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code != 429 and exc.code < 500:
                raise FetchError(f"{url}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last = exc
        if attempt < retries - 1:
            delay = min(30.0, 0.5 * 2 ** attempt) * (1 + random.random() * 0.5)
            log.warning("fetch failed (%s), retry %d/%d in %.1fs", last, attempt + 1, retries, delay)
            sleep(delay)
    raise FetchError(f"{url}: {last}") from last


def http_json(url: str, headers: Optional[dict] = None, timeout: int = 30) -> dict:
    return json.loads(http_get(url, headers=headers, timeout=timeout))


def candle_path(product: str, granularity: int, directory: Path = DEFAULT_DIR) -> Path:
    return Path(directory) / f"{product.replace('-', '')}_{granularity}s.csv"


def fetch_page(product: str, granularity: int, start: dt.datetime, end: dt.datetime) -> List[list]:
    q = urllib.parse.urlencode({
        "granularity": granularity,
        "start": start.isoformat().replace("+00:00", "Z"),
        "end": end.isoformat().replace("+00:00", "Z"),
    })
    return http_json(BASE.format(product=product) + "?" + q)


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
    rows = http_json(BASE.format(product=product) + "?" + q)
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
    text = http_get(url, timeout=60).decode()
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


def cache_path(symbol: str, span: str, directory: Path = None) -> Path:
    directory = Path(directory) if directory is not None else CACHE_DIR
    return directory / f"{symbol.replace('=', '_').replace('^', '')}_{span}.csv"


def _cached(symbol: str, span: str, directory: Path, max_age_days: float) -> Optional[pd.DataFrame]:
    p = cache_path(symbol, span, directory)
    if not p.exists():
        return None
    age_days = (time.time() - p.stat().st_mtime) / 86400.0
    if age_days > max_age_days:
        log.warning("cache for %s is %.1f days old; not using it", symbol, age_days)
        return None
    df = pd.read_csv(p)
    df["dt"] = pd.to_datetime(df["dt"], utc=True)
    return df.sort_values("dt").reset_index(drop=True)


def yahoo_daily(symbol: str, span: str = "5y", cache_dir: Path = None,
                max_cache_age_days: float = MAX_CACHE_AGE_DAYS) -> pd.DataFrame:
    """Daily OHLCV from Yahoo's public chart endpoint (futures, ETFs, crypto).

    Every successful fetch is written to a CSV cache. When the fetch fails after
    its retries, a cache younger than `max_cache_age_days` is returned instead,
    with a warning, so a transient outage produces a stale-but-honest mark
    rather than no mark. Callers that rank assets must still check staleness.
    """
    q = urllib.parse.urlencode({"range": span, "interval": "1d"})
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?{q}"
    try:
        payload = http_json(url, headers={"User-Agent": "Mozilla/5.0"})
        result = payload["chart"]["result"][0]
    except (FetchError, KeyError, IndexError, TypeError, ValueError) as exc:
        cached = _cached(symbol, span, cache_dir, max_cache_age_days)
        if cached is None:
            raise FetchError(f"yahoo {symbol}: {exc}; no usable cache") from exc
        log.warning("yahoo %s failed (%s); using cache from %s", symbol, exc,
                    cached["dt"].iloc[-1])
        return cached
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
    df = pd.DataFrame(rows).sort_values("dt").reset_index(drop=True)
    if not df.empty:
        try:
            save(df, cache_path(symbol, span, cache_dir))
        except OSError as exc:  # a read-only disk must not stop a mark
            log.warning("could not write cache for %s: %s", symbol, exc)
    return df

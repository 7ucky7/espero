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
from typing import Callable, List, Optional, Sequence

import pandas as pd

log = logging.getLogger(__name__)

EXCHANGE = "https://api.exchange.coinbase.com"
BASE = EXCHANGE + "/products/{product}/candles"
PRODUCTS_URL = EXCHANGE + "/products"
STATS_URL = EXCHANGE + "/products/{product}/stats"
STABLECOINS = {"USDT", "USDC", "DAI", "PYUSD", "USDP", "GUSD", "EURC", "TUSD", "PAX", "USD1", "RLUSD"}
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


def list_products(quote: str = "USD", exclude: Sequence[str] = ("BTC", "ETH"),
                  fetch: Callable[[str], object] = None) -> List[str]:
    """Every live, tradable `<base>-<quote>` product on Coinbase Exchange, minus
    stablecoins and the majors in `exclude`. Public endpoint, no key."""
    fetch = fetch or http_json
    rows = fetch(PRODUCTS_URL)
    out = []
    for r in rows:
        if r.get("quote_currency") != quote or r.get("status") != "online":
            continue
        if r.get("trading_disabled") or r.get("fx_stablecoin"):
            continue
        base = r.get("base_currency", "")
        if base in STABLECOINS or base in exclude:
            continue
        out.append(r["id"])
    return sorted(out)


def product_stats(product: str, fetch: Callable[[str], object] = None) -> dict:
    """24h stats: `last`, `volume` (base units) and the dollar volume derived from them."""
    fetch = fetch or http_json
    r = fetch(STATS_URL.format(product=product))
    last, vol = float(r.get("last") or 0), float(r.get("volume") or 0)
    return {"product": product, "last": last, "volume": vol, "dollar_volume": last * vol}


def degen_universe(top: int = 60, min_dollar_volume: float = 0.0, products: Optional[List[str]] = None,
                   fetch: Callable[[str], object] = None, pause: float = 0.1,
                   sleep=time.sleep) -> List[dict]:
    """The altcoins people are actually trading right now: every listed USD
    product ranked by 24h dollar volume, top `top`. One stats call per product
    (a few hundred, paced); a failing product is skipped, never guessed."""
    products = products if products is not None else list_products(fetch=fetch)
    stats = []
    for p in products:
        try:
            stats.append(product_stats(p, fetch=fetch))
        except Exception as exc:  # noqa: BLE001 - one dead product must not kill the scan
            log.warning("stats %s: %s", p, exc)
        if pause:
            sleep(pause)
    stats = [s for s in stats if s["dollar_volume"] >= min_dollar_volume]
    stats.sort(key=lambda s: -s["dollar_volume"])
    return stats[:top]


def candle_path(product: str, granularity: int, directory: Path = DEFAULT_DIR) -> Path:
    return Path(directory) / f"{product.replace('-', '')}_{granularity}s.csv"


def fetch_page(product: str, granularity: int, start: dt.datetime, end: dt.datetime) -> List[list]:
    q = urllib.parse.urlencode({
        "granularity": granularity,
        "start": start.isoformat().replace("+00:00", "Z"),
        "end": end.isoformat().replace("+00:00", "Z"),
    })
    return http_json(BASE.format(product=product) + "?" + q)


def fetch(product: str, days: int, granularity: int = 86400,
          end: Optional[dt.datetime] = None) -> pd.DataFrame:
    """Download `days` of candles, paginating under the 300-candle cap. With
    `end`, the window ends there (exclusive) instead of now: a past year."""
    stop = end
    end = end or dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - dt.timedelta(days=days)
    rows: List[list] = []
    cursor = start
    step = dt.timedelta(seconds=granularity * 280)
    while cursor < end:
        chunk_end = min(cursor + step, end)
        rows.extend(fetch_page(product, granularity, cursor, chunk_end))
        cursor = chunk_end
        time.sleep(0.34)  # public limit is 10 req/s; do not hammer it
    # Coinbase's `end` is inclusive: the candle opening at `end` is still in
    # progress and would be cached as if it were closed
    now = int(time.time()) if stop is None else int(stop.timestamp())
    dedup = {int(r[0]): r for r in rows if int(r[0]) + granularity <= now}
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


def unix_seconds(stamps) -> pd.Series:
    """Unix seconds from datetimes or ISO strings, whatever resolution pandas
    parsed them at. `astype("int64") // 10**9` assumes nanoseconds; pandas 3
    parses these strings to microseconds, which made every such ts 1000x small."""
    t = pd.to_datetime(pd.Series(stamps), utc=True)
    return ((t - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)).astype("int64")


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
    df["ts"] = unix_seconds(df["dt"]).to_numpy()
    return df[["dt", "ts", "open", "high", "low", "close", "volume"]].sort_values("dt").reset_index(drop=True)


def cache_path(symbol: str, span: str, directory: Path = None, adjusted: bool = False) -> Path:
    directory = Path(directory) if directory is not None else CACHE_DIR
    suffix = "_adj" if adjusted else ""      # never mixed: an adjusted series is a different series
    return directory / f"{symbol.replace('=', '_').replace('^', '')}_{span}{suffix}.csv"


def _cached(symbol: str, span: str, directory: Path, max_age_days: float,
            adjusted: bool = False) -> Optional[pd.DataFrame]:
    p = cache_path(symbol, span, directory, adjusted)
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
                max_cache_age_days: float = MAX_CACHE_AGE_DAYS, adjusted: bool = False) -> pd.DataFrame:
    """Daily OHLCV from Yahoo's public chart endpoint (futures, ETFs, crypto).

    Every successful fetch is written to a CSV cache. When the fetch fails after
    its retries, a cache younger than `max_cache_age_days` is returned instead,
    with a warning, so a transient outage produces a stale-but-honest mark
    rather than no mark. Callers that rank assets must still check staleness.

    `adjusted=True` adds an `adj_close` column: the close adjusted for splits and
    dividends, so an ETF's return includes what it paid out (TLT over ten years:
    x0.62 on price, x0.83 with dividends). It is cached in its own file and falls
    back only to that file; a payload without it is an error, never a silent
    unadjusted series. The default leaves the request, columns and cache as they were.
    """
    params = {"range": span, "interval": "1d"}
    if adjusted:
        params["events"] = "div,split"
    q = urllib.parse.urlencode(params)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?{q}"
    try:
        payload = http_json(url, headers={"User-Agent": "Mozilla/5.0"})
        result = payload["chart"]["result"][0]
        adj = result["indicators"]["adjclose"][0]["adjclose"] if adjusted else None
    except (FetchError, KeyError, IndexError, TypeError, ValueError) as exc:
        cached = _cached(symbol, span, cache_dir, max_cache_age_days, adjusted)
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
        if None in (o, h, l, c) or (adjusted and adj[i] is None):
            continue
        row = {
            "dt": dt.datetime.fromtimestamp(t, dt.timezone.utc),
            "ts": int(t),
            "open": float(o), "high": float(h), "low": float(l), "close": float(c),
            "volume": float(quote["volume"][i] or 0),
        }
        if adjusted:
            row["adj_close"] = float(adj[i])
        rows.append(row)
    df = pd.DataFrame(rows).sort_values("dt").reset_index(drop=True)
    if not df.empty:
        try:
            save(df, cache_path(symbol, span, cache_dir, adjusted))
        except OSError as exc:  # a read-only disk must not stop a mark
            log.warning("could not write cache for %s: %s", symbol, exc)
    return df

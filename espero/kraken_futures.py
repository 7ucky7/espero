"""Kraken Futures public market data, read-only: tickers, funding history and
hourly trade candles, in the frames the carry engine already reads.

No key, no signing, nothing that can place an order. Used by hypothesis #14
(research/PREREGISTRATION_CARRY3.md): #12's carry rule on a second venue.

Funding units, from Kraken's perpetual contract specification: the rate is
"standardised to a per-hour basis" and paid as rate x position x hours, and
the API's `timestamp` is the start of the period the rate applies to. So a
rate is an hourly rate for every hour of its period, the same scale as
Hyperliquid's hourly `fundingRate`.
"""
from __future__ import annotations

import datetime as dt
import time
import urllib.parse
from typing import Callable, Dict, List, Optional

import pandas as pd

BASE = "https://futures.kraken.com"
TICKERS = BASE + "/derivatives/api/v3/tickers"
FUNDING = BASE + "/derivatives/api/v3/historical-funding-rates"
CANDLES = BASE + "/api/charts/v1/trade/{symbol}/1h"
HOUR = 3600
MAX_GAP_H = 8                  # a rate never covers more than this; a longer gap stays missing
ALIASES = {"XBT": "BTC", "XDG": "DOGE"}

Fetch = Callable[[str], object]


def _get(url: str, fetch: Optional[Fetch] = None) -> object:
    from .data import http_json
    return (fetch or http_json)(url)


def base_of(symbol: str) -> Optional[str]:
    """`PF_XBTUSD` -> `BTC`. None for anything that is not a USD linear perpetual."""
    if not (symbol.startswith("PF_") and symbol.endswith("USD")):
        return None
    b = symbol[3:-3]
    return ALIASES.get(b, b) or None


def perpetuals(fetch: Optional[Fetch] = None) -> List[Dict[str, object]]:
    """Every `PF_` perpetual with its base coin and open interest in USD
    (contracts x mark price; a linear contract is one unit of the base)."""
    out = []
    for t in _get(TICKERS, fetch).get("tickers", []):
        sym = str(t.get("symbol", "")).upper()
        b = base_of(sym)
        if b is None or t.get("suspended"):
            continue
        try:
            oi = float(t.get("openInterest") or 0) * float(t.get("markPrice") or 0)
        except (TypeError, ValueError):
            continue
        out.append({"symbol": sym, "coin": b, "open_interest_usd": oi})
    return out


def top_by_open_interest(n: int, perps: List[Dict[str, object]]) -> List[Dict[str, object]]:
    return sorted(perps, key=lambda r: r["open_interest_usd"], reverse=True)[:n]


def funding_history(symbol: str, fetch: Optional[Fetch] = None) -> pd.DataFrame:
    """Raw rates: `ts` (seconds, start of the period) and `rate` (relativeFundingRate,
    hourly). The endpoint returns the whole history in one list."""
    q = urllib.parse.urlencode({"symbol": symbol})
    rows = _get(f"{FUNDING}?{q}", fetch).get("rates", [])
    if not rows:
        return pd.DataFrame(columns=["ts", "rate"])
    df = pd.DataFrame({
        "ts": [int(pd.Timestamp(r["timestamp"]).timestamp()) for r in rows],
        "rate": [float(r["relativeFundingRate"]) for r in rows],
    })
    return df.drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True)


def hourly_funding(raw: pd.DataFrame, max_gap_h: int = MAX_GAP_H) -> pd.DataFrame:
    """One row per hour in the frame `carry.from_frames` reads (`ts`, `funding`):
    each rate applied unchanged to every hour from its timestamp to the next one.
    A gap longer than `max_gap_h` is left missing. The last rate covers the
    series' usual spacing, never more than `max_gap_h`."""
    if raw.empty:
        return pd.DataFrame(columns=["ts", "funding"])
    ts = (raw["ts"].to_numpy() // HOUR) * HOUR
    rates = raw["rate"].to_numpy()
    spacing = int(pd.Series(ts).diff().median() // HOUR) if len(ts) > 1 else 1
    out_ts, out_f = [], []
    for i, (t, r) in enumerate(zip(ts, rates)):
        hours = (ts[i + 1] - t) // HOUR if i + 1 < len(ts) else max(spacing, 1)
        if hours <= 0 or hours > max_gap_h:
            hours = 1 if hours > max_gap_h else 0           # the rate's own hour only
        for h in range(int(hours)):
            out_ts.append(int(t + h * HOUR))
            out_f.append(float(r))
    df = pd.DataFrame({"ts": out_ts, "funding": out_f})
    return df.drop_duplicates("ts", keep="last").reset_index(drop=True)


def candles(symbol: str, start_s: int, end_s: Optional[int] = None, fetch: Optional[Fetch] = None,
            sleep=time.sleep, pages: int = 500) -> pd.DataFrame:
    """Hourly trade candles, `time` (ISO, UTC) and open/high/low/close/volume,
    walking forward from `start_s`. Only closed hours are kept."""
    now = int(time.time())
    end_s = min(end_s or now, now)
    rows: Dict[int, dict] = {}
    cursor = start_s
    for _ in range(pages):
        if cursor >= end_s:
            break
        q = urllib.parse.urlencode({"from": cursor, "to": end_s})
        page = _get(CANDLES.format(symbol=symbol) + "?" + q, fetch)
        got = page.get("candles", []) if isinstance(page, dict) else []
        if not got:
            break
        for c in got:
            t = int(c["time"]) // 1000
            if t + HOUR <= now:
                rows[t] = c
        last = int(got[-1]["time"]) // 1000
        if last + HOUR <= cursor:
            break
        cursor = last + HOUR
        if not page.get("more_candles", True):
            break
        sleep(0.25)
    if not rows:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    return pd.DataFrame([{
        "time": dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat(),
        "open": float(c["open"]), "high": float(c["high"]), "low": float(c["low"]),
        "close": float(c["close"]), "volume": float(c.get("volume") or 0),
    } for t, c in sorted(rows.items())])

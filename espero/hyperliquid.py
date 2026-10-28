"""Hyperliquid public `info` endpoint: perp universe, hourly funding, candles.

Everything here is a POST of a small JSON body to one URL and needs no key.
Every function takes an injectable `fetch(body: dict) -> object` so tests
never touch the network; the default posts through `data.http_get`, which
carries the retry and backoff policy.

Funding on Hyperliquid settles **hourly**, not every 8 hours as on most
venues, and the rate it quotes is the hourly rate. A positive rate is paid by
longs to shorts.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from typing import Callable, Dict, List, Optional

import pandas as pd

INFO_URL = "https://api.hyperliquid.xyz/info"
FUNDING_PERIOD_S = 3600
CANDLE_LIMIT = 5000          # the endpoint returns at most this many candles per call
INTERVAL_S = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}

Fetch = Callable[[dict], object]


def post(body: dict) -> object:
    from .data import UA, http_get
    raw = http_get(INFO_URL, headers={**UA, "Content-Type": "application/json"},
                   data=json.dumps(body).encode())
    return json.loads(raw)


def asset_contexts(fetch: Optional[Fetch] = None) -> List[Dict[str, float]]:
    """One row per listed perp: coin, mark, hourly funding, open interest and
    24h volume in dollars. `metaAndAssetCtxs` returns `[meta, ctxs]` with the
    two lists aligned by position."""
    meta, ctxs = (fetch or post)({"type": "metaAndAssetCtxs"})
    out = []
    for m, c in zip(meta["universe"], ctxs):
        if m.get("isDelisted"):
            continue
        mark = float(c["markPx"])
        out.append({
            "coin": m["name"],
            "mark": mark,
            "funding": float(c["funding"]),
            "open_interest": float(c["openInterest"]) * mark,
            "day_volume": float(c["dayNtlVlm"]),
            "max_leverage": int(m.get("maxLeverage", 0)),
        })
    return out


def top_by_open_interest(n: int, ctxs: List[Dict[str, float]]) -> List[str]:
    ranked = sorted(ctxs, key=lambda r: r["open_interest"], reverse=True)
    return [r["coin"] for r in ranked[:n]]


def funding_history(coin: str, start_ms: int, end_ms: Optional[int] = None,
                    fetch: Optional[Fetch] = None, pages: int = 200,
                    sleep=time.sleep) -> pd.DataFrame:
    """Hourly funding, walking forward 500 rows per call. Columns `ts`
    (seconds, the settlement hour) and `funding` (hourly rate)."""
    rows, cursor = [], start_ms
    for _ in range(pages):
        body = {"type": "fundingHistory", "coin": coin, "startTime": cursor}
        if end_ms is not None:
            body["endTime"] = end_ms
        page = (fetch or post)(body)
        if not page:
            break
        rows.extend(page)
        cursor = int(page[-1]["time"]) + 1
        if len(page) < 500:
            break
        sleep(0.15)
    if not rows:
        return pd.DataFrame(columns=["ts", "funding"])
    df = pd.DataFrame([{"ts": int(r["time"]) // 1000, "funding": float(r["fundingRate"])}
                       for r in rows])
    return df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


def candles(coin: str, interval: str, start_ms: int, end_ms: Optional[int] = None,
            fetch: Optional[Fetch] = None, sleep=time.sleep) -> pd.DataFrame:
    """Perp candles in the same frame as `data.fetch`: `time` (ISO, UTC),
    open/high/low/close/volume. Paginates forward under the 5000-candle cap."""
    step_ms = INTERVAL_S[interval] * 1000
    if end_ms is None:
        end_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    rows: Dict[int, dict] = {}
    cursor = start_ms
    while cursor < end_ms:
        chunk_end = min(cursor + step_ms * CANDLE_LIMIT, end_ms)
        page = (fetch or post)({"type": "candleSnapshot",
                                "req": {"coin": coin, "interval": interval,
                                        "startTime": cursor, "endTime": chunk_end}})
        if not page:
            break
        for r in page:
            rows[int(r["t"])] = r
        last = int(page[-1]["t"])
        if last + step_ms <= cursor:
            break
        cursor = last + step_ms
        if cursor < end_ms:
            sleep(0.15)
    return pd.DataFrame([{
        "time": dt.datetime.fromtimestamp(t // 1000, dt.timezone.utc).isoformat(),
        "open": float(r["o"]), "high": float(r["h"]), "low": float(r["l"]),
        "close": float(r["c"]), "volume": float(r["v"]),
    } for t, r in sorted(rows.items())])

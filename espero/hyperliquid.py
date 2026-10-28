"""Hyperliquid public `info` endpoint: perp universe, hourly funding, candles.

Everything here is a POST of a small JSON body to one URL and needs no key.
Two networks: mainnet (market data, the default) and the testnet at
api.hyperliquid-testnet.xyz (HL_NETWORK=testnet, or `testnet_post`), whose web
UI and faucet are at app.hyperliquid-testnet.xyz. Reading an account needs only
its public address; nothing here signs anything.
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
import os
import time
from typing import Callable, Dict, List, Optional

import pandas as pd

MAINNET_URL = "https://api.hyperliquid.xyz"
TESTNET_URL = "https://api.hyperliquid-testnet.xyz"
INFO_URL = MAINNET_URL + "/info"      # default; see info_url()
FUNDING_PERIOD_S = 3600
CANDLE_LIMIT = 5000          # the endpoint returns at most this many candles per call
INTERVAL_S = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}

Fetch = Callable[[dict], object]


def network(env: Optional[dict] = None) -> str:
    """"mainnet" or "testnet", from HL_NETWORK in the environment (or .env).
    Market data (universe, funding, candles) comes from mainnet unless asked
    otherwise; the testnet is thin and its funding is not the market's."""
    env = os.environ if env is None else env
    value = (env.get("HL_NETWORK") or "mainnet").strip().lower()
    if value not in ("mainnet", "testnet"):
        raise ValueError(f"HL_NETWORK must be mainnet or testnet, not {value!r}")
    return value


def info_url(env: Optional[dict] = None, testnet: Optional[bool] = None) -> str:
    """HL_API_URL wins; else the network's base. `testnet=True/False` overrides both."""
    env = os.environ if env is None else env
    if testnet is None:
        override = (env.get("HL_API_URL") or "").strip().rstrip("/")
        if override:
            return override + "/info"
        testnet = network(env) == "testnet"
    return (TESTNET_URL if testnet else MAINNET_URL) + "/info"


def post(body: dict, url: Optional[str] = None) -> object:
    from .data import UA, http_get
    raw = http_get(url or INFO_URL, headers={**UA, "Content-Type": "application/json"},
                   data=json.dumps(body).encode())
    return json.loads(raw)


def testnet_post(body: dict) -> object:
    return post(body, info_url(testnet=True))


def user_state(address: str, fetch: Optional[Fetch] = None) -> Dict[str, object]:
    """Read-only account snapshot (`clearinghouseState`): equity, margin in use,
    withdrawable, and open perp positions with entry, size, unrealised P&L and
    the funding they have paid or received. Needs only the public address."""
    st = (fetch or testnet_post)({"type": "clearinghouseState", "user": address})
    summary = st.get("marginSummary", {})
    positions = []
    for ap in st.get("assetPositions", []):
        p = ap.get("position", {})
        szi = float(p.get("szi", 0) or 0)
        if szi == 0:
            continue
        positions.append({
            "coin": p["coin"], "size": szi, "side": "long" if szi > 0 else "short",
            "entry": float(p.get("entryPx") or 0), "notional": float(p.get("positionValue") or 0),
            "unrealized": float(p.get("unrealizedPnl") or 0),
            "funding_paid": float((p.get("cumFunding") or {}).get("sinceOpen", 0) or 0),
            "liquidation": float(p["liquidationPx"]) if p.get("liquidationPx") else None,
            "leverage": float((p.get("leverage") or {}).get("value", 0) or 0),
        })
    return {
        "equity": float(summary.get("accountValue", 0) or 0),
        "margin_used": float(summary.get("totalMarginUsed", 0) or 0),
        "notional": float(summary.get("totalNtlPos", 0) or 0),
        "withdrawable": float(st.get("withdrawable", 0) or 0),
        "positions": positions,
    }


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
        sleep(0.5)      # the info endpoint rate-limits bursts of history pages
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

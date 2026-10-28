"""Point-in-time features. The rule that matters: a feature may only be used
after the moment it existed.

Every row carries two timestamps -- when the data is *about* (`ts`) and when we
could first have read it (`fetched_at`). The merge drops any feature that is
not strictly older than the bar it is attached to, which is the same
look-ahead rule the fills obey.
"""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

OKX_FUNDING = "https://www.okx.com/api/v5/public/funding-rate-history"
POLY_HISTORY = "https://clob.polymarket.com/prices-history"
UA = {"User-Agent": "espero/0.1"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS features (
    name TEXT NOT NULL, ts INTEGER NOT NULL, value REAL, fetched_at INTEGER,
    PRIMARY KEY (name, ts)
);
"""


def _get(url: str, params: dict) -> dict:
    from .data import http_json
    return http_json(url + "?" + urllib.parse.urlencode(params), headers=UA)


# ------------------------------------------------------------------ sources
def okx_funding(pages: int = 4, inst_id: str = "BTC-USDT-SWAP") -> pd.DataFrame:
    """Hourly-equivalent perpetual funding, 8h settlements, paginated backwards."""
    rows, cursor = [], None
    for _ in range(pages):
        params = {"instId": inst_id, "limit": 100}
        if cursor:
            # OKX's "after" walks backwards from the cursor; counter-intuitive but
            # "before" is ignored and returns the newest page again.
            params["after"] = cursor
        data = _get(OKX_FUNDING, params).get("data", [])
        if not data:
            break
        rows.extend(data)
        cursor = min(int(r["fundingTime"]) for r in data)
        time.sleep(0.2)
    if not rows:
        return pd.DataFrame(columns=["ts", "funding"])
    df = pd.DataFrame(
        [{"ts": int(r["fundingTime"]) // 1000, "funding": float(r["realizedRate"])}
         for r in rows]
    ).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    return df


def hyperliquid_funding(pages: int = 70, coin: str = "BTC",
                        start_ms: int = 1_683_000_000_000) -> pd.DataFrame:
    """Hourly funding from Hyperliquid, walking forward 500 rows at a time."""
    rows, cursor = [], start_ms
    for _ in range(pages):
        body = json.dumps({"type": "fundingHistory", "coin": coin,
                           "startTime": cursor}).encode()
        from .data import http_get
        page = json.loads(http_get("https://api.hyperliquid.xyz/info", data=body,
                                   headers={**UA, "Content-Type": "application/json"}))
        if not page:
            break
        rows.extend(page)
        cursor = int(page[-1]["time"]) + 1
        if len(page) < 500:
            break
        time.sleep(0.15)
    if not rows:
        return pd.DataFrame(columns=["ts", "funding"])
    df = pd.DataFrame([{"ts": int(r["time"]) // 1000, "funding": float(r["fundingRate"])}
                       for r in rows])
    return df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


def deribit_funding(start_ms: int = 1_546_300_800_000,
                    end_ms: int = 1_793_059_200_000) -> pd.DataFrame:   # pinned: 2026-10-27, reproducible
    """Hourly funding history, long enough to cover several market regimes.

    Deribit is used here because it is the only free source reachable from this
    machine that goes back before 2023.
    """

    rows = []
    cursor = start_ms
    while cursor < end_ms:
        nxt = min(cursor + 30 * 24 * 3600 * 1000, end_ms)
        params = {
            "instrument_name": "BTC-PERPETUAL",
            "start_timestamp": cursor,
            "end_timestamp": nxt,
            "count": 1000,
        }
        data = _get("https://www.deribit.com/api/v2/public/get_funding_rate_history",
                    params).get("result", [])
        rows.extend(data)
        cursor = nxt
        time.sleep(0.15)
    if not rows:
        return pd.DataFrame(columns=["ts", "funding"])
    df = pd.DataFrame([{"ts": int(r["timestamp"]) // 1000,
                        "funding": float(r["interest_8h"] if "interest_8h" in r else r["interest"])}
                       for r in rows])
    return df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


def polymarket_history(token_id: str, fidelity: int = 60) -> pd.DataFrame:
    """Implied probability of one outcome, from the CLOB price history."""
    data = _get(POLY_HISTORY, {"market": token_id, "interval": "max", "fidelity": fidelity})
    hist = data.get("history", [])
    if not hist:
        return pd.DataFrame(columns=["ts", "prob"])
    df = pd.DataFrame([{"ts": int(p["t"]), "prob": float(p["p"])} for p in hist])
    return df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


# ------------------------------------------------------------------ storage
def save(db_path: str | Path, name: str, df: pd.DataFrame, value_col: str) -> int:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    now = int(time.time())
    rows = [(name, int(r["ts"]), float(r[value_col]), now) for _, r in df.iterrows()]
    db.executemany(
        "INSERT OR REPLACE INTO features(name, ts, value, fetched_at) VALUES (?,?,?,?)", rows
    )
    db.commit()
    db.close()
    return len(rows)


def load(db_path: str | Path, name: str) -> pd.DataFrame:
    db = sqlite3.connect(Path(db_path))
    db.executescript(SCHEMA)
    df = pd.read_sql_query(
        "SELECT ts, value, fetched_at FROM features WHERE name=? ORDER BY ts", db, params=(name,)
    )
    db.close()
    if df.empty:
        return pd.DataFrame(columns=["ts", "value", "fetched_at"])
    return df


# -------------------------------------------------------------- transforms
def zscore(feats: pd.DataFrame, column: str, window: int = 90) -> pd.DataFrame:
    """Causal z-score over the feature's own timeline."""
    out = feats.copy()
    mean = out[column].rolling(window, min_periods=max(10, window // 3)).mean()
    std = out[column].rolling(window, min_periods=max(10, window // 3)).std()
    out[f"{column}_z"] = (out[column] - mean) / std.replace(0, np.nan)
    return out


def attach(bars: pd.DataFrame, feats: pd.DataFrame, value_col: str,
           out_col: str, lag_seconds: int = 3600) -> pd.DataFrame:
    """As-of merge that refuses to let a feature be younger than `lag_seconds`.

    The bar's lookup key is moved back by the lag, so a feature stamped at the
    bar's own close time cannot be used on that bar.
    """
    b = bars.copy()
    f = feats.copy()
    unit = "datetime64[us, UTC]"
    b["dt"] = pd.to_datetime(b["dt"], utc=True).astype(unit)
    f["dt"] = pd.to_datetime(f["ts"], unit="s", utc=True).astype(unit)
    b["_key"] = (b["dt"] - pd.Timedelta(seconds=lag_seconds)).astype(unit)
    merged = pd.merge_asof(
        b.sort_values("_key"), f[["dt", value_col]].sort_values("dt"),
        left_on="_key", right_on="dt", direction="backward",
        suffixes=("", "_feat"), allow_exact_matches=True,
    ).rename(columns={value_col: out_col})

    # a feature stamped exactly at the bar's own close was not knowable yet
    if "dt_feat" in merged.columns:
        same_instant = merged["dt_feat"] == merged["dt"]
        merged.loc[same_instant, out_col] = np.nan
        merged = merged.drop(columns=["dt_feat"])
    merged = merged.drop(columns=["_key"])
    return merged.sort_values("dt").reset_index(drop=True)

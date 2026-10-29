"""aggr's public hourly bars (api.aggr.trade, github.com/Tucsky/aggr-server).

Each bar carries the dollars of shorts (`lbuy`) and longs (`lsell`) liquidated in
it. The coins, markets and panel are the exploration's (research/aggr_explore.py),
copied here unchanged so the daily job does not import research code. It is one
person's free server: a few requests a day, paced.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Dict, List

import numpy as np
import pandas as pd

API = "https://api.aggr.trade/historical/{start}/{end}/3600000/{markets}"
PACE_S = 3.0
COLUMNS = ["time", "market", "open", "high", "low", "close", "vbuy", "vsell", "cbuy", "csell", "lbuy", "lsell"]

COINS: Dict[str, Dict[str, List[str]]] = {}
for _c, _venues in {"BTC": "BYO", "ETH": "BYO", "SOL": "BYO", "BNB": "BYO", "XRP": "BO", "ADA": "BYO",
                    "DOGE": "BYO", "AVAX": "BYO", "LINK": "BYO", "TRX": "BO", "LTC": "BYO", "XLM": "BO",
                    "HBAR": "BYO", "SHIB": "O"}.items():
    _m = {"B": f"BINANCE_FUTURES:{_c.lower()}usdt", "Y": f"BYBIT:{_c}USDT", "O": f"OKEX:{_c}-USDT-SWAP"}
    COINS[_c] = {"price": [_m["B"] if "B" in _venues else _m["O"]], "all": [_m[v] for v in _venues]}


def markets() -> List[str]:
    return sorted({m for v in COINS.values() for m in v["all"]})


def parse(payload: dict) -> pd.DataFrame:
    """aggr's `point` format -> one row per market and hour."""
    cols = payload.get("columns") or {}
    rows = payload.get("results") or []
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    return pd.DataFrame({k: [r[cols[k]] for r in rows] if k in cols else np.nan for k in COLUMNS})


def fetch(start: pd.Timestamp, end: pd.Timestamp, sleep=time.sleep, opener=urllib.request.urlopen) -> pd.DataFrame:
    """Hourly bars for every market from `start` (inclusive) to `end` (exclusive)."""
    out = []
    ms = markets()
    for i in range(0, len(ms), 10):
        url = API.format(start=int(start.timestamp() * 1000), end=int(end.timestamp() * 1000),
                         markets=urllib.parse.quote("+".join(ms[i:i + 10]), safe=""))
        req = urllib.request.Request(url, headers={"User-Agent": "espero (daily hourly bars)"})
        with opener(req, timeout=120) as r:
            payload = json.load(r)
        if payload.get("error"):
            raise RuntimeError(f"aggr: {payload['error']}")
        out.append(parse(payload))
        sleep(PACE_S)
    df = pd.concat(out, ignore_index=True)
    t = pd.to_datetime(df["time"], unit="s", utc=True)
    return df[(t >= start) & (t < end)]


def panel(raw: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Per coin, hourly: open/close and volume from its price market, liquidations summed
    over all its venues (long = longs liquidated, short = shorts liquidated)."""
    raw = raw.assign(t=pd.to_datetime(raw["time"], unit="s", utc=True)) if "t" not in raw else raw
    out = {}
    for c, m in COINS.items():
        px = raw[raw["market"] == m["price"][0]].set_index("t").sort_index()
        px = px[~px.index.duplicated(keep="last")]
        if px.empty:
            continue
        liq = raw[raw["market"].isin(m["all"])].drop_duplicates(["market", "t"], keep="last") \
            .groupby("t")[["lsell", "lbuy"]].sum()
        df = pd.DataFrame({"open": px["open"], "close": px["close"], "volume": px["vbuy"] + px["vsell"]})
        df = df.join(liq.rename(columns={"lsell": "long", "lbuy": "short"})).fillna({"long": 0.0, "short": 0.0})
        out[c] = df.reindex(pd.date_range(df.index.min(), df.index.max(), freq="h"))
    return out

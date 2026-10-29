"""Cryptometer (cryptometer.io): 24-hour liquidations by exchange. Read-only.

The key comes from CRYPTOMETER_API_KEY in .env (you set it; nothing here prints
it, and errors are reported with it removed). The liquidation endpoint is a paid
add-on and returns only the last 24 hours, one total per exchange: a daily
snapshot beside aggr's hourly bars, not a history.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Dict, Optional

BASE = "https://api.cryptometer.io"


class CryptometerError(RuntimeError):
    pass


def _key(env: Optional[dict] = None) -> str:
    key = (env if env is not None else os.environ).get("CRYPTOMETER_API_KEY", "").strip()
    if not key:
        raise CryptometerError("CRYPTOMETER_API_KEY is not set (add it to .env)")
    return key


def get(path: str, params: Dict[str, str], env: Optional[dict] = None,
        opener: Callable = urllib.request.urlopen) -> dict:
    key = _key(env)
    url = f"{BASE}/{path.strip('/')}/?" + urllib.parse.urlencode({**params, "api_key": key})
    try:
        with opener(urllib.request.Request(url, headers={"User-Agent": "espero"}), timeout=30) as r:
            payload = json.load(r)
    except urllib.error.HTTPError as exc:
        raise CryptometerError(f"{path}: HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise CryptometerError(f"{path}: {str(exc).replace(key, '<key>')}") from None
    if str(payload.get("success", "true")).lower() == "false" or payload.get("error"):
        msg = str(payload.get("error") or payload.get("message") or "refused").replace(key, "<key>")
        raise CryptometerError(f"{path}: {msg}")
    return payload


def liquidations(symbol: str, env: Optional[dict] = None, opener: Callable = urllib.request.urlopen) -> dict:
    """{exchange: {"longs": usd, "shorts": usd}} over the last 24 hours."""
    payload = get("liquidation-data-v2", {"symbol": symbol.lower()}, env, opener)
    data = payload.get("data") or []
    rows = data[0] if isinstance(data, list) and data else data
    out = {}
    for ex, v in (rows or {}).items():
        if isinstance(v, dict) and ("longs" in v or "shorts" in v):
            out[ex] = {"longs": float(v.get("longs") or 0), "shorts": float(v.get("shorts") or 0)}
    return out

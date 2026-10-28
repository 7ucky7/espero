"""Hyperliquid **testnet** order path. The only code in espero that signs anything.

Guard rails, in the order they are checked, every time an exchange is built:

1. `HL_NETWORK` must be `testnet`.
2. `ESPERO_ALLOW_HL_TESTNET=1` must be set (a second, explicit opt-in).
3. `HL_API_URL`, if set, must be a testnet URL. The exchange is built on the
   testnet constant regardless; the env can refuse, never redirect.
4. `HL_PRIVATE_KEY` is read here and nowhere else, and only after 1-3 pass.

The signer is the official SDK (`hyperliquid-python-sdk`), installed as the
`hl` extra. Mainnet is not reachable from this module: the base URL is a
constant, and it is asserted after construction.

The mirror at the bottom shadows a carry paper book's perp leg with real
testnet orders (ALO, resting at the hour's price) so the maker-fill assumption
behind #12 can be measured instead of assumed. The spot leg stays paper: there
is no spot market for these coins on the testnet.
"""
from __future__ import annotations

import math
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

TESTNET_URL = "https://api.hyperliquid-testnet.xyz"
MAX_SIG_FIGS = 5
MAX_DECIMALS_PERP = 6


class TestnetRefused(RuntimeError):
    """Raised, never caught here, when the environment does not describe a testnet-only setup."""


def guard(env: Optional[dict] = None) -> str:
    """Return the private key only when every testnet guard passes."""
    env = os.environ if env is None else env
    network = (env.get("HL_NETWORK") or "").strip().lower()
    if network != "testnet":
        raise TestnetRefused("HL_NETWORK must be 'testnet' to sign anything (mainnet signing is not implemented)")
    if (env.get("ESPERO_ALLOW_HL_TESTNET") or "").strip() != "1":
        raise TestnetRefused("set ESPERO_ALLOW_HL_TESTNET=1 to allow testnet orders")
    override = (env.get("HL_API_URL") or "").strip()
    if override and "testnet" not in override:
        raise TestnetRefused(f"HL_API_URL={override!r} is not a testnet URL; refusing")
    key = (env.get("HL_PRIVATE_KEY") or "").strip()
    if not key:
        raise TestnetRefused("HL_PRIVATE_KEY is empty: create an API wallet in the testnet UI and put its key in .env")
    return key


# -------------------------------------------------------------------- rounding
def round_size(sz: float, sz_decimals: int) -> float:
    return math.floor(abs(sz) * 10 ** sz_decimals) / 10 ** sz_decimals


def round_price(px: float, sz_decimals: int, side: str) -> float:
    """Hyperliquid accepts at most 5 significant figures and 6 − szDecimals
    decimals on a perp price. A sell is rounded up and a buy down so the
    rounded order never crosses further than the asked price."""
    if px <= 0:
        raise ValueError("price must be positive")
    decimals = min(MAX_DECIMALS_PERP - sz_decimals, max(0, MAX_SIG_FIGS - 1 - int(math.floor(math.log10(px)))))
    step = 10 ** -decimals
    units = px / step
    units = math.ceil(units - 1e-9) if side == "sell" else math.floor(units + 1e-9)
    return round(units * step, decimals)


def parse_order_response(resp: Any) -> dict:
    """Flatten the SDK's order response to {status, oid, filled, avg_px, error}."""
    try:
        st = resp["response"]["data"]["statuses"][0]
    except (KeyError, IndexError, TypeError):
        return {"status": "error", "oid": None, "filled": 0.0, "avg_px": None,
                "error": str(resp)[:200]}
    if "resting" in st:
        return {"status": "resting", "oid": int(st["resting"]["oid"]), "filled": 0.0, "avg_px": None, "error": None}
    if "filled" in st:
        f = st["filled"]
        return {"status": "filled", "oid": int(f["oid"]), "filled": float(f["totalSz"]),
                "avg_px": float(f["avgPx"]), "error": None}
    return {"status": "error", "oid": None, "filled": 0.0, "avg_px": None, "error": str(st.get("error", st))[:200]}


# -------------------------------------------------------------------- exchange
@dataclass
class OrderResult:
    coin: str
    side: str
    size: float
    price: float
    tif: str
    status: str
    oid: Optional[int]
    filled: float
    avg_px: Optional[float]
    error: Optional[str]


class TestnetExchange:
    """Thin, testnet-only wrapper over the SDK's Exchange and Info clients.

    `exchange` / `info` can be injected (tests); when they are, no key is read
    and nothing is built. `meta` is {coin: szDecimals}."""

    def __init__(self, env: Optional[dict] = None, exchange=None, info=None,
                 meta: Optional[Dict[str, int]] = None, address: Optional[str] = None):
        if exchange is None:
            key = guard(env)
            from eth_account import Account
            from hyperliquid.exchange import Exchange
            from hyperliquid.info import Info
            wallet = Account.from_key(key)
            exchange = Exchange(wallet, base_url=TESTNET_URL)
            info = info or Info(base_url=TESTNET_URL, skip_ws=True)
            address = address or wallet.address
            if getattr(exchange, "base_url", TESTNET_URL) != TESTNET_URL:
                raise TestnetRefused("exchange is not on the testnet URL; refusing")
        self.ex = exchange
        self.info = info
        self.address = address or ""
        self._meta = meta

    @property
    def meta(self) -> Dict[str, int]:
        if self._meta is None:
            m = self.info.meta()
            self._meta = {u["name"]: int(u["szDecimals"]) for u in m["universe"]}
        return self._meta

    def limit(self, coin: str, side: str, size: float, price: float, tif: str = "Alo",
              reduce_only: bool = False) -> OrderResult:
        """Resting limit order. `tif` Alo = add-liquidity-only (rejected rather
        than crossing: the maker test), Gtc = may take, Ioc = take or cancel."""
        if side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        if coin not in self.meta:
            raise ValueError(f"{coin}: not a testnet perp")
        sd = self.meta[coin]
        sz, px = round_size(size, sd), round_price(price, sd, side)
        if sz <= 0:
            raise ValueError(f"{coin}: size {size} rounds to zero at {sd} decimals")
        resp = self.ex.order(coin, side == "buy", sz, px, {"limit": {"tif": tif}}, reduce_only=reduce_only)
        p = parse_order_response(resp)
        return OrderResult(coin, side, sz, px, tif, **p)

    def cancel(self, coin: str, oid: int) -> bool:
        resp = self.ex.cancel(coin, int(oid))
        return isinstance(resp, dict) and resp.get("status") == "ok"

    def open_orders(self) -> List[dict]:
        return list(self.info.open_orders(self.address))

    def fills(self, since_ts: int = 0) -> List[dict]:
        out = []
        for f in self.info.user_fills(self.address):
            if int(f.get("time", 0)) // 1000 >= since_ts:
                out.append(f)
        return out

    def positions(self) -> dict:
        from . import hyperliquid as hl
        return hl.user_state(self.address, fetch=hl.testnet_post)


# ---------------------------------------------------------------------- mirror
MIRROR_SCHEMA = """
CREATE TABLE IF NOT EXISTS testnet_mirror (
    position_id INTEGER PRIMARY KEY, coin TEXT,
    open_oid INTEGER, open_px REAL, open_size REAL, open_status TEXT, open_filled REAL DEFAULT 0, open_ts INTEGER,
    close_oid INTEGER, close_px REAL, close_status TEXT, close_filled REAL DEFAULT 0, close_ts INTEGER,
    note TEXT
);
"""


class TestnetMirror:
    """Shadow a CarryBook's perp leg on the testnet with ALO orders at the
    hour's perp price. One row per paper position; statuses are refreshed from
    the venue's open orders and fills on every sync. The answer it produces is
    the fill rate of resting orders, the number #12 assumed to be 100%."""

    def __init__(self, db: sqlite3.Connection, exchange: TestnetExchange):
        self.db = db
        self.ex = exchange
        self.db.executescript(MIRROR_SCHEMA)

    def rows(self) -> List[sqlite3.Row]:
        return self.db.execute("SELECT * FROM testnet_mirror ORDER BY position_id").fetchall()

    def sync(self, positions: List[sqlite3.Row], closed: List[sqlite3.Row], prices: Dict[str, float],
             now: Optional[int] = None) -> List[str]:
        now = now or int(time.time())
        out: List[str] = []
        known = {r["position_id"]: r for r in self.rows()}

        # 1. new paper positions -> resting short
        for p in positions:
            if p["id"] in known:
                continue
            px = prices.get(p["coin"])
            if px is None:
                continue
            try:
                r = self.ex.limit(p["coin"], "sell", p["qty_perp"], px, tif="Alo")
            except Exception as exc:  # noqa: BLE001 - record, do not crash the paper book
                r = OrderResult(p["coin"], "sell", p["qty_perp"], px, "Alo", "error", None, 0.0, None, str(exc)[:200])
            self.db.execute(
                "INSERT INTO testnet_mirror (position_id, coin, open_oid, open_px, open_size, open_status, "
                "open_filled, open_ts, note) VALUES (?,?,?,?,?,?,?,?,?)",
                (p["id"], p["coin"], r.oid, r.price, r.size, r.status, r.filled, now, r.error))
            out.append(f"testnet {p['coin']}: short {r.size} @ {r.price} ALO -> {r.status}"
                       + (f" ({r.error})" if r.error else ""))

        # 2. paper closes -> reduce-only buy (only if the open ever filled)
        for c in closed:
            m = known.get(c["id"])
            if m is None or m["close_oid"] is not None or m["close_status"] is not None:
                continue
            px = prices.get(c["coin"])
            if px is None:
                continue
            if m["open_status"] not in ("filled", "part"):
                # nothing on the venue to close; cancel the resting open if any
                if m["open_oid"] and m["open_status"] == "resting":
                    try:
                        self.ex.cancel(c["coin"], m["open_oid"])
                    except Exception:  # noqa: BLE001
                        pass
                self.db.execute("UPDATE testnet_mirror SET close_status='unfilled_open', close_ts=? "
                                "WHERE position_id=?", (now, c["id"]))
                out.append(f"testnet {c['coin']}: paper closed, open never filled -> cancelled")
                continue
            try:
                r = self.ex.limit(c["coin"], "buy", m["open_filled"], px, tif="Alo", reduce_only=True)
            except Exception as exc:  # noqa: BLE001
                r = OrderResult(c["coin"], "buy", m["open_filled"], px, "Alo", "error", None, 0.0, None, str(exc)[:200])
            self.db.execute("UPDATE testnet_mirror SET close_oid=?, close_px=?, close_status=?, close_filled=?, "
                            "close_ts=?, note=COALESCE(note,'') || ? WHERE position_id=?",
                            (r.oid, r.price, r.status, r.filled, now, r.error or "", c["id"]))
            out.append(f"testnet {c['coin']}: close buy {r.size} @ {r.price} ALO -> {r.status}")

        # 3. refresh resting orders from the venue
        self.refresh(out, now=now)
        self.db.commit()
        return out

    def refresh(self, out: Optional[List[str]] = None, now: Optional[int] = None, grace: int = 60) -> None:
        """Pull statuses from the venue. An order placed less than `grace`
        seconds ago that the venue does not list yet is left as it is, so a
        just-placed order is not misread as cancelled."""
        out = out if out is not None else []
        now = now or int(time.time())
        try:
            open_oids = {int(o["oid"]) for o in self.ex.open_orders()}
            fills = self.ex.fills()
        except Exception as exc:  # noqa: BLE001
            out.append(f"testnet: status refresh failed: {exc}")
            return
        filled: Dict[int, float] = {}
        for f in fills:
            filled[int(f["oid"])] = filled.get(int(f["oid"]), 0.0) + float(f["sz"])
        for m in self.rows():
            for leg in ("open", "close"):
                oid, status = m[f"{leg}_oid"], m[f"{leg}_status"]
                if not oid or status in ("filled", "cancelled", "error", "unfilled_open"):
                    continue
                got = filled.get(oid, 0.0)
                size = m["open_size"] if leg == "open" else m["open_filled"]
                fresh = (m[f"{leg}_ts"] or 0) > now - grace
                new = ("filled" if size and got >= size * 0.999 else
                       "part" if got > 0 else
                       "resting" if oid in open_oids or fresh else "cancelled")
                if new != status or got != m[f"{leg}_filled"]:
                    self.db.execute(f"UPDATE testnet_mirror SET {leg}_status=?, {leg}_filled=? WHERE position_id=?",
                                    (new, got, m["position_id"]))
                    out.append(f"testnet {m['coin']}: {leg} order {oid} {status} -> {new} ({got} filled)")

    def summary(self) -> dict:
        rows = self.rows()
        opens = [r for r in rows if r["open_oid"]]
        return {
            "orders": len(opens),
            "filled": sum(1 for r in opens if r["open_status"] == "filled"),
            "part": sum(1 for r in opens if r["open_status"] == "part"),
            "resting": sum(1 for r in opens if r["open_status"] == "resting"),
            "cancelled": sum(1 for r in opens if r["open_status"] in ("cancelled", "unfilled_open")),
            "errors": sum(1 for r in rows if r["open_status"] == "error"),
        }

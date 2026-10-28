"""The order book, as a thing you can read, record and replay.

Coinbase Exchange's level-2 book and recent trades are public REST endpoints,
polled here about once a second. That is not a websocket, and the module says
so: the timestamps are when *we* read, which is what a fill simulator needs to
be honest about. A recorder writes every snapshot to a JSONL file so a day can
be replayed at any speed with no network, which is how the fast screen is
tested and practised.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from .data import http_json

BOOK_URL = "https://api.exchange.coinbase.com/products/{product}/book?level=2"
TRADES_URL = "https://api.exchange.coinbase.com/products/{product}/trades?limit={limit}"
Level = Tuple[float, float]   # (price, size)


@dataclass
class Trade:
    id: int
    ts: float
    side: str        # taker side: "buy" hit the ask, "sell" hit the bid
    price: float
    size: float


@dataclass
class BookSnapshot:
    ts: float
    product: str
    bids: List[Level] = field(default_factory=list)   # best first, descending price
    asks: List[Level] = field(default_factory=list)   # best first, ascending price
    trades: List[Trade] = field(default_factory=list)  # since the previous snapshot

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0][0] if self.asks else None

    @property
    def mid(self) -> Optional[float]:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2

    @property
    def spread_bps(self) -> Optional[float]:
        m = self.mid
        if not m:
            return None
        return 1e4 * (self.best_ask - self.best_bid) / m

    def depth_ahead(self, side: str, price: float) -> float:
        """Size resting at prices that would fill before a new order at `price`
        on `side`, plus the size already at `price`: the queue a new order
        joins at the back of."""
        levels = self.bids if side == "buy" else self.asks
        better = (lambda p: p >= price) if side == "buy" else (lambda p: p <= price)
        return float(sum(s for p, s in levels if better(p)))

    def imbalance(self, levels: int = 5) -> Optional[float]:
        """(bid size - ask size) / (bid + ask) over the top levels, in [-1, 1]."""
        b = sum(s for _, s in self.bids[:levels])
        a = sum(s for _, s in self.asks[:levels])
        return (b - a) / (b + a) if (b + a) > 0 else None

    def to_json(self) -> str:
        return json.dumps({
            "ts": self.ts, "product": self.product,
            "bids": self.bids[:25], "asks": self.asks[:25],
            "trades": [[t.id, t.ts, t.side, t.price, t.size] for t in self.trades],
        })

    @classmethod
    def from_json(cls, line: str) -> "BookSnapshot":
        d = json.loads(line)
        return cls(d["ts"], d["product"], [tuple(x) for x in d["bids"]], [tuple(x) for x in d["asks"]],
                   [Trade(*t) for t in d["trades"]])


# ------------------------------------------------------------------ live feed
def _parse_time(s: str) -> float:
    from datetime import datetime, timezone
    s = s.rstrip("Z")
    if "." in s:                          # microseconds may have 6 digits or fewer
        head, frac = s.split(".")
        s = f"{head}.{frac[:6].ljust(6, '0')}"
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()


class CoinbaseBook:
    """Polls the public book and trades. `read()` returns a snapshot whose
    trades are the ones not seen on the previous read."""

    def __init__(self, product: str, trades_limit: int = 100):
        self.product = product
        self.trades_limit = trades_limit
        self.last_trade_id: Optional[int] = None

    def read(self) -> BookSnapshot:
        book = http_json(BOOK_URL.format(product=self.product))
        raw_trades = http_json(TRADES_URL.format(product=self.product, limit=self.trades_limit))
        now = time.time()
        bids = [(float(p), float(s)) for p, s, _ in book.get("bids", [])]
        asks = [(float(p), float(s)) for p, s, _ in book.get("asks", [])]
        trades: List[Trade] = []
        newest = self.last_trade_id
        for t in raw_trades:
            tid = int(t["trade_id"])
            if self.last_trade_id is not None and tid <= self.last_trade_id:
                continue
            trades.append(Trade(tid, _parse_time(t["time"]), t["side"], float(t["price"]), float(t["size"])))
            newest = tid if newest is None else max(newest, tid)
        if self.last_trade_id is None:
            trades = []                   # the first read has no "since"; do not count history
        self.last_trade_id = newest
        trades.sort(key=lambda t: t.id)
        return BookSnapshot(now, self.product, bids, asks, trades)


# ------------------------------------------------------------ record / replay
class Recorder:
    """Append every snapshot to a JSONL file. One file per session."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")   # noqa: SIM115 - kept open on purpose
        self.n = 0

    def write(self, snap: BookSnapshot) -> None:
        self._fh.write(snap.to_json() + "\n")
        self._fh.flush()
        self.n += 1

    def close(self) -> None:
        self._fh.close()


def replay(path: Path) -> Iterator[BookSnapshot]:
    """Yield the recorded snapshots in order. The caller sets the pace."""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield BookSnapshot.from_json(line)

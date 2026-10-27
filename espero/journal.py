"""SQLite journal: every signal, order, fill and equity mark, in order.

The point is not logging. The point is that after a crash you can reconstruct
exactly what the bot thought and did, and that the same file is the evidence
you show when someone asks for a track record.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .signals import Signal

SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    product TEXT NOT NULL, ts INTEGER NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (product, ts)
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product TEXT, ts INTEGER, side TEXT, confidence REAL, strategies TEXT
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    product TEXT, created_ts INTEGER, side TEXT, size REAL, reason TEXT,
    status TEXT, filled_ts INTEGER, filled_px REAL, fee REAL
);
CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,
    product TEXT, entry_ts INTEGER, entry_px REAL, size REAL, entry_fee REAL,
    stop REAL, target REAL, exit_ts INTEGER, exit_px REAL, pnl REAL, reason TEXT
);
CREATE TABLE IF NOT EXISTS equity (
    ts INTEGER PRIMARY KEY, cash REAL, position_value REAL, equity REAL
);
"""


@dataclass
class Position:
    id: str
    product: str
    entry_ts: int
    entry_px: float
    size: float
    stop: float
    target: float
    entry_fee: float = 0.0


@dataclass
class PendingOrder:
    id: str
    product: str
    created_ts: int
    side: str
    size: float
    reason: str


class Journal:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=5.0)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")   # a reader never blocks the writer
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ---------------------------------------------------------------- bars
    def has_bar(self, product: str, ts: int) -> bool:
        row = self.db.execute(
            "SELECT 1 FROM bars WHERE product=? AND ts=?", (product, ts)
        ).fetchone()
        return row is not None

    def add_bar(self, product: str, bar: dict) -> bool:
        """Insert a closed bar. Returns False if it was already known."""
        cur = self.db.execute(
            "INSERT OR IGNORE INTO bars(product, ts, open, high, low, close, volume) "
            "VALUES (?,?,?,?,?,?,?)",
            (product, int(bar["ts"]), bar["open"], bar["high"], bar["low"],
             bar["close"], bar.get("volume", 0.0)),
        )
        self.db.commit()
        return cur.rowcount > 0

    def last_bar_ts(self, product: str) -> Optional[int]:
        row = self.db.execute(
            "SELECT MAX(ts) AS ts FROM bars WHERE product=?", (product,)
        ).fetchone()
        return row["ts"] if row and row["ts"] is not None else None

    # ------------------------------------------------------------- signals
    def add_signal(self, product: str, ts: int, sig: Signal) -> None:
        self.db.execute(
            "INSERT INTO signals(product, ts, side, confidence, strategies) VALUES (?,?,?,?,?)",
            (product, ts, sig.side, sig.confidence, json.dumps([sig.strategy])),
        )
        self.db.commit()

    def signals(self, limit: int = 20) -> List[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

    # -------------------------------------------------------------- orders
    def add_order(self, order: PendingOrder) -> None:
        self.db.execute(
            "INSERT INTO orders(id, product, created_ts, side, size, reason, status) "
            "VALUES (?,?,?,?,?,?,'pending')",
            (order.id, order.product, order.created_ts, order.side, order.size, order.reason),
        )
        self.db.commit()

    def pending_order(self, product: str) -> Optional[PendingOrder]:
        row = self.db.execute(
            "SELECT * FROM orders WHERE status='pending' AND product=? ORDER BY created_ts LIMIT 1",
            (product,),
        ).fetchone()
        if row is None:
            return None
        return PendingOrder(row["id"], row["product"], row["created_ts"],
                            row["side"], row["size"], row["reason"])

    def fill_order(self, order_id: str, ts: int, px: float, fee: float) -> None:
        self.db.execute(
            "UPDATE orders SET status='filled', filled_ts=?, filled_px=?, fee=? WHERE id=?",
            (ts, px, fee, order_id),
        )
        self.db.commit()

    def cancel_order(self, order_id: str, reason: str = "cancelled") -> None:
        self.db.execute("UPDATE orders SET status=? WHERE id=?", (reason, order_id))
        self.db.commit()

    # ----------------------------------------------------------- positions
    def open_position(self, position: Position) -> None:
        self.db.execute(
            "INSERT INTO positions(id, product, entry_ts, entry_px, size, entry_fee, "
            "stop, target) VALUES (?,?,?,?,?,?,?,?)",
            (position.id, position.product, position.entry_ts, position.entry_px,
             position.size, position.entry_fee, position.stop, position.target),
        )
        self.db.commit()

    def current_position(self, product: str) -> Optional[Position]:
        row = self.db.execute(
            "SELECT * FROM positions WHERE product=? AND exit_ts IS NULL "
            "ORDER BY entry_ts DESC LIMIT 1",
            (product,),
        ).fetchone()
        if row is None:
            return None
        return Position(row["id"], row["product"], row["entry_ts"],
                        row["entry_px"], row["size"], row["stop"], row["target"],
                        row["entry_fee"] or 0.0)

    def close_position(self, position_id: str, ts: int, px: float, pnl: float,
                       reason: str) -> None:
        self.db.execute(
            "UPDATE positions SET exit_ts=?, exit_px=?, pnl=?, reason=? WHERE id=?",
            (ts, px, pnl, reason, position_id),
        )
        self.db.commit()

    def closed_positions(self) -> List[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM positions WHERE exit_ts IS NOT NULL ORDER BY exit_ts"
        ).fetchall()

    # -------------------------------------------------------------- equity
    def mark_equity(self, ts: int, cash: float, position_value: float) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO equity(ts, cash, position_value, equity) VALUES (?,?,?,?)",
            (ts, cash, position_value, cash + position_value),
        )
        self.db.commit()

    def latest_equity(self) -> tuple[float, float]:
        row = self.db.execute(
            "SELECT * FROM equity ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return 0.0, 0.0
        return row["cash"], row["equity"]

    def equity_curve(self) -> List[sqlite3.Row]:
        return self.db.execute("SELECT * FROM equity ORDER BY ts").fetchall()

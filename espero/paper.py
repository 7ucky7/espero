"""Paper trading: the backtest loop, but time moves forward and state is on disk.

Rules that are not negotiable here:

* a bar must be closed before it can produce a signal
* a signal is filled on the NEXT bar's open, never the bar it came from
* every decision is written to the journal before it can affect money
* restarting the process resumes the open position instead of forgetting it
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List

import pandas as pd

from .indicators import add_indicators
from .journal import Journal, PendingOrder, Position
from .risk import RiskLimits, check_buy
from .signals import combine, signals_at


@dataclass
class PaperConfig:
    product: str = "BTC-USD"
    granularity: int = 3600
    initial: float = 500.0
    fee: float = 0.0          # per side; 0.0002 hyperliquid-ish, 0.006 coinbase
    slippage: float = 0.0005  # per side
    warmup: int = 50
    stop_pct: float = 0.05
    target_pct: float = 0.10
    limits: RiskLimits = field(default_factory=RiskLimits)


class PaperTrader:
    def __init__(self, journal: Journal, cfg: PaperConfig):
        self.journal = journal
        self.cfg = cfg
        cash, _ = journal.latest_equity()
        self.cash = cash if cash else cfg.initial
        self.position = journal.current_position(cfg.product)
        self.pending = journal.pending_order(cfg.product)

    # ------------------------------------------------------------------ api
    def on_bar(self, bar: dict) -> List[str]:
        """Process one closed bar. Returns human-readable events."""
        ts = int(bar["ts"])
        close = float(bar["close"])
        events: List[str] = []

        if not self.journal.add_bar(self.cfg.product, bar):
            return ["duplicate bar ignored"]

        # 1. exits on the open position (never on the bar it was opened)
        if self.position is not None and self.position.entry_ts != ts:
            px, reason = self._exit_trigger(bar)
            if px is not None:
                events.append(self._close(px, ts, reason))

        # 2. fill whatever was queued at the previous close
        if self.pending is not None:
            if ts - self.pending.created_ts > 2 * self.cfg.granularity:
                self.journal.cancel_order(self.pending.id, "stale")
                events.append("cancelled stale order")
            else:
                events.append(self._fill(self.pending, bar, ts))
            self.pending = None

        # 3. decide at the close
        signal = self._signal_at_close()
        if signal is not None:
            self.journal.add_signal(self.cfg.product, ts, signal)
            if signal.side == "BUY" and self.position is None and self.pending is None:
                equity = self._equity(close)
                decision = check_buy(
                    equity=equity,
                    cash=self.cash,
                    open_positions=0,
                    day_pnl=self._day_pnl(equity),
                    confidence=signal.confidence,
                    limits=self.cfg.limits,
                )
                if decision.allowed:
                    size = decision.notional / close
                    self.pending = PendingOrder(str(uuid.uuid4())[:8], self.cfg.product,
                                                ts, "BUY", size, "signal")
                    self.journal.add_order(self.pending)
                    events.append(f"queued BUY {size:.6f} for next open "
                                  f"(notional {decision.notional:.2f})")
                else:
                    events.append(f"blocked BUY: {decision.reason}")
            elif signal.side == "SELL" and self.position is not None and self.pending is None:
                in_profit = close > self.position.entry_px
                if in_profit or signal.confidence > 0.8:
                    self.pending = PendingOrder(str(uuid.uuid4())[:8], self.cfg.product,
                                                ts, "SELL", self.position.size, "signal")
                    self.journal.add_order(self.pending)
                    events.append("queued SELL for next open")

        self.journal.mark_equity(ts, self.cash, self._position_value(close))
        return events

    # -------------------------------------------------------------- helpers
    def _signal_at_close(self):
        """Mirror of the backtest: indicators over the last N closed bars."""
        rows = self.journal.db.execute(
            "SELECT ts, open, high, low, close, volume FROM bars "
            "WHERE product=? ORDER BY ts DESC LIMIT ?",
            (self.cfg.product, self.cfg.warmup + 100),
        ).fetchall()
        if len(rows) < self.cfg.warmup + 2:
            return None
        df = pd.DataFrame([dict(r) for r in reversed(rows)])
        df["dt"] = pd.to_datetime(df["ts"], unit="s", utc=True)
        d = add_indicators(df)
        return combine(signals_at(d.iloc[-1], d.iloc[-2]))

    def _exit_trigger(self, bar: dict):
        pos, open_px = self.position, float(bar["open"])
        if open_px <= pos.stop:
            return open_px, "gap_stop"
        if open_px >= pos.target:
            return open_px, "gap_target"
        if float(bar["low"]) <= pos.stop:
            return pos.stop, "stop"
        if float(bar["high"]) >= pos.target:
            return pos.target, "target"
        return None, ""

    def _fill(self, order: PendingOrder, bar: dict, ts: int) -> str:
        open_px = float(bar["open"])
        if order.side == "BUY":
            px = open_px * (1 + self.cfg.slippage)
            size = order.size
            fee = px * size * self.cfg.fee
            self.cash -= px * size + fee
            self.position = Position(
                id=str(uuid.uuid4())[:8], product=self.cfg.product, entry_ts=ts,
                entry_px=px, size=size, stop=px * (1 - self.cfg.stop_pct),
                target=px * (1 + self.cfg.target_pct), entry_fee=fee,
            )
            self.journal.open_position(self.position)
            self.journal.fill_order(order.id, ts, px, fee)
            return f"filled BUY {size:.6f} @ {px:.2f}"

        px = open_px * (1 - self.cfg.slippage)
        pos = self.position
        fee = px * pos.size * self.cfg.fee
        pnl = (px - pos.entry_px) * pos.size - fee - pos.entry_fee
        self.cash += px * pos.size - fee
        self.journal.fill_order(order.id, ts, px, fee)
        self.journal.close_position(pos.id, ts, px, pnl, "signal")
        self.position = None
        return f"filled SELL @ {px:.2f}  pnl {pnl:+.2f}"

    def _close(self, exit_px: float, ts: int, reason: str) -> str:
        pos = self.position
        px = exit_px * (1 - self.cfg.slippage)
        fee = px * pos.size * self.cfg.fee
        pnl = (px - pos.entry_px) * pos.size - fee - pos.entry_fee
        self.cash += px * pos.size - fee
        self.journal.close_position(pos.id, ts, px, pnl, reason)
        self.position = None
        return f"exit {reason} @ {px:.2f}  pnl {pnl:+.2f}"

    def _position_value(self, price: float) -> float:
        return self.position.size * price if self.position else 0.0

    def _equity(self, price: float) -> float:
        return self.cash + self._position_value(price)

    def _day_pnl(self, equity: float) -> float:
        day = datetime.now(timezone.utc).date().isoformat()
        row = self.journal.db.execute(
            "SELECT cash, position_value FROM equity WHERE date(ts,'unixepoch')=? "
            "ORDER BY ts LIMIT 1", (day,),
        ).fetchone()
        if row is None:
            return 0.0
        return equity - (row["cash"] + row["position_value"])

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
from .signals import MIN_CONFIDENCE, combine, signals_at
from .venues import FUNDING_PERIOD_S, VENUES


@dataclass
class PaperConfig:
    product: str = "BTC-USD"
    granularity: int = 3600
    initial: float = 500.0
    fee: float = 0.0          # per side; 0.0002 hyperliquid-ish, 0.006 coinbase
    funding_8h: float = 0.0   # perps: fraction of notional a long pays per 8h period
    funding_period: int = FUNDING_PERIOD_S   # how often it settles
    slippage: float = 0.0005  # per side
    warmup: int = 50
    stop_pct: float = 0.05
    target_pct: float = 0.10
    limits: RiskLimits = field(default_factory=RiskLimits)

    @classmethod
    def for_venue(cls, venue: str, **kw) -> "PaperConfig":
        """Taker fee and funding from the venue table. The paper loop fills at the
        next open, which is a market order, so it pays the taker side."""
        v = VENUES[venue]
        return cls(fee=v.taker_bps / 1e4, funding_8h=v.funding_bps_8h / 1e4,
                   funding_period=v.funding_period_s, **kw)


def funding_due(prev_ts: int, ts: int, entry_ts: int, notional: float, rate: float,
                period: int = FUNDING_PERIOD_S) -> float:
    """Funding owed for each settlement in (prev_ts, ts] that falls after
    `entry_ts`. `rate` is the fraction of notional per 8h; `period` is how often
    the venue settles (8h on most, hourly on Hyperliquid), and the 8h rate is
    pro-rated to it. Longs pay a positive rate. Shared by every paper book that
    can hold a perp."""
    if not rate:
        return 0.0
    first = (prev_ts // period + 1) * period
    n = sum(1 for t in range(first, ts + 1, period) if t > entry_ts)
    return n * notional * rate * period / FUNDING_PERIOD_S


class PaperTrader:
    def __init__(self, journal: Journal, cfg: PaperConfig):
        self.journal = journal
        self.cfg = cfg
        self._load()

    def _load(self) -> None:
        """In-memory state from the journal: at start, and again after a bar
        failed and its writes were rolled back."""
        cash, _ = self.journal.latest_equity()
        self.cash = cash if cash else self.cfg.initial
        self.position = self.journal.current_position(self.cfg.product)
        self.pending = self.journal.pending_order(self.cfg.product)

    # ------------------------------------------------------------------ api
    def on_bar(self, bar: dict) -> List[str]:
        """Process one closed bar as one transaction. Returns human-readable
        events. If anything raises, the bar's writes are rolled back, memory is
        reloaded from the journal and the error propagates; the same bar can
        then be fed again."""
        try:
            with self.journal.transaction():
                return self._on_bar(bar)
        except Exception:
            self._load()
            raise

    def _on_bar(self, bar: dict) -> List[str]:
        ts = int(bar["ts"])
        close = float(bar["close"])
        events: List[str] = []

        prev_ts = self.journal.last_bar_ts(self.cfg.product)
        if not self.journal.add_bar(self.cfg.product, bar):
            return ["duplicate bar ignored"]

        # 0. perp funding for every settlement the open position was held through
        if self.position is not None and self.cfg.funding_8h and prev_ts is not None:
            paid = self._funding(prev_ts, ts, close)
            if paid:
                events.append(f"funding paid {paid:.4f}")

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
        if signal is not None and signal.confidence < MIN_CONFIDENCE:
            # the backtest ignores anything under the floor; so must we, or the
            # paper and live books run a different strategy from the tested one
            signal = None
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

    def _funding(self, prev_ts: int, ts: int, price: float) -> float:
        """Charge funding for each settlement time in (prev_ts, ts] that falls
        after the position was opened. Longs pay a positive rate."""
        pos = self.position
        paid = funding_due(prev_ts, ts, pos.entry_ts, pos.size * price, self.cfg.funding_8h,
                           self.cfg.funding_period)
        if not paid:
            return 0.0
        self.cash -= paid
        pos.entry_fee += paid
        self.journal.charge_position(pos.id, paid)
        return paid

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

        pos = self.position
        if pos is None:
            # a stop or target already closed it earlier in this bar
            self.journal.cancel_order(order.id, "no position")
            return "SELL cancelled, position already closed"
        px = open_px * (1 - self.cfg.slippage)
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


def compare_venues(bars: List[dict], venues: List[str], product: str = "BTC-USD",
                   granularity: int = 3600, initial: float = 500.0,
                   state_dir=None) -> List[dict]:
    """Replay the same closed bars through a fresh paper book per venue.

    Same bars, same signals, same fills; only the fee and funding differ. This
    is the only fair way to compare venues, because a live loop on each would
    see different bars and draw different conclusions from noise."""
    import tempfile
    from pathlib import Path

    out = []
    with tempfile.TemporaryDirectory(dir=state_dir) as d:
        for v in venues:
            j = Journal(Path(d) / f"{v}.db")
            t = PaperTrader(j, PaperConfig.for_venue(v, product=product,
                                                     granularity=granularity, initial=initial))
            funding = 0.0
            for b in bars:
                for e in t.on_bar(b):
                    if e.startswith("funding paid"):
                        funding += float(e.split()[-1])
            last = float(bars[-1]["close"]) if bars else 0.0
            closed = j.closed_positions()
            fees = sum((r["fee"] or 0.0) for r in j.db.execute(
                "SELECT fee FROM orders WHERE status='filled'").fetchall())
            out.append({
                "venue": v, "name": VENUES[v].name, "trades": len(closed),
                "wins": sum(1 for r in closed if (r["pnl"] or 0) > 0),
                "fees": fees, "funding": funding,
                "equity": t._equity(last), "pnl": t._equity(last) - initial,
            })
            j.db.close()
    return out

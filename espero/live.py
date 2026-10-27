"""Live (and dry-run) execution on top of the same signal code as the backtest.

Differences from paper trading, stated loudly:

* the fill is a real market order at the moment the bar closes, not the next
  bar's open -- the journal records both so the slippage is measurable
* stops are software stops checked once per bar, not exchange-side orders. If
  the process dies, the stop dies with it. That is why the kill switch exists
* every order is capped in notional and gated by a daily loss limit
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import pandas as pd

from .broker import Ack, Broker, BrokerError, new_client_id
from .indicators import add_indicators
from .journal import Journal, Position
from .risk import RiskLimits, check_buy
from .signals import MIN_CONFIDENCE, combine, signals_at


@dataclass
class LiveConfig:
    product: str = "BTC-USD"
    quote_currency: str = "USD"
    base_currency: str = "BTC"
    granularity: int = 3600
    fee: float = 0.006          # coinbase taker; change if you know your tier
    slippage: float = 0.0005
    warmup: int = 50
    stop_pct: float = 0.05
    target_pct: float = 0.10
    max_notional: float = 25.0        # hard cap per order
    max_daily_loss: float = 15.0      # kill switch, in quote currency
    limits: RiskLimits = field(default_factory=RiskLimits)


class LiveTrader:
    def __init__(self, journal: Journal, broker: Broker, cfg: LiveConfig,
                 kill_file: str = "KILL"):
        self.journal = journal
        self.broker = broker
        self.cfg = cfg
        self.kill_file = Path(kill_file)
        self.position: Optional[Position] = journal.current_position(cfg.product)
        self.day_start_equity: Optional[float] = None

    # ------------------------------------------------------------------ safety
    def halted(self) -> Optional[str]:
        if self.kill_file.exists():
            return f"kill switch present ({self.kill_file})"
        if not self.broker.live:
            return None
        equity = self.equity()
        if self.day_start_equity is None:
            self.day_start_equity = equity
        if equity - self.day_start_equity <= -self.cfg.max_daily_loss:
            return f"daily loss limit ({equity - self.day_start_equity:+.2f})"
        return None

    def equity(self) -> float:
        cash = self.broker.balance(self.cfg.quote_currency)
        size = self.position.size if self.position else 0.0
        return cash + size * self.broker.price(self.cfg.product)

    # --------------------------------------------------------------------- run
    def on_bar(self, bar: dict) -> List[str]:
        ts, close = int(bar["ts"]), float(bar["close"])
        events: List[str] = []

        if not self.journal.add_bar(self.cfg.product, bar):
            return ["duplicate bar ignored"]

        stop_reason = self.halted()
        if stop_reason:
            return [f"halted: {stop_reason}"]

        if self.position is not None and self.position.entry_ts != ts:
            exit_px = self._exit_trigger(bar)
            if exit_px is not None:
                events.append(self._sell(exit_px, ts))

        signal = self._signal_at_close()
        if signal is not None:
            self.journal.add_signal(self.cfg.product, ts, signal)
            if signal.side == "BUY" and self.position is None:
                events.append(self._buy(close, signal.confidence, ts))

        self.journal.mark_equity(ts, self.broker.balance(self.cfg.quote_currency),
                                 self.position.size * close if self.position else 0.0)
        return events

    # ---------------------------------------------------------------- helpers
    def _signal_at_close(self):
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

    def _exit_trigger(self, bar: dict) -> Optional[float]:
        pos = self.position
        if float(bar["open"]) <= pos.stop:
            return float(bar["open"])
        if float(bar["open"]) >= pos.target:
            return float(bar["open"])
        if float(bar["low"]) <= pos.stop:
            return pos.stop
        if float(bar["high"]) >= pos.target:
            return pos.target
        return None

    def _buy(self, price: float, confidence: float, ts: int) -> str:
        equity = self.equity()
        decision = check_buy(equity, self.broker.balance(self.cfg.quote_currency),
                             0, 0.0, confidence, self.cfg.limits)
        if not decision.allowed:
            return f"blocked BUY: {decision.reason}"
        notional = min(decision.notional, self.cfg.max_notional)
        if notional < self.cfg.limits.min_notional:
            return f"blocked BUY: notional {notional:.2f} below minimum"
        client_id = new_client_id("buy")
        ack = self.broker.market_buy(self.cfg.product, notional, client_id)
        fill_px = ack.filled_px or price
        size = (ack.filled_size or notional / fill_px)
        fee = ack.fee or notional * self.cfg.fee
        self.position = Position(
            id=client_id, product=self.cfg.product, entry_ts=ts,
            entry_px=fill_px, size=size, stop=fill_px * (1 - self.cfg.stop_pct),
            target=fill_px * (1 + self.cfg.target_pct), entry_fee=fee,
        )
        self.journal.open_position(self.position)
        return f"BUY {notional:.2f} {self.cfg.product} @ {fill_px:.2f} [{ack.status}]"

    def _sell(self, price: float, ts: int) -> str:
        pos = self.position
        client_id = new_client_id("sell")
        ack = self.broker.market_sell(self.cfg.product, pos.size, client_id)
        fill_px = ack.filled_px or price
        pnl = (fill_px - pos.entry_px) * pos.size - pos.entry_fee
        self.journal.close_position(pos.id, ts, fill_px, pnl, "live_exit")
        self.position = None
        return f"SELL {pos.size:.8f} {self.cfg.product} @ {fill_px:.2f} pnl {pnl:+.2f} [{ack.status}]"

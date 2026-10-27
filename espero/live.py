"""Live (and dry-run) execution on top of the same signal code as the backtest.

STATUS: EXPERIMENTAL. The paper accounts (`tsmom`, `xs`) are the product; this
module is a dry-run tool that can, with two explicit opt-ins, send real orders.
It has never been reconciled against a venue and should not hold money you
would miss.

Differences from paper trading, stated loudly:

* the fill is a real market order at the moment the bar closes, not the next
  bar's open -- the journal records both so the slippage is measurable
* stops are software stops checked once per bar, not exchange-side orders. If
  the process dies, the stop dies with it. That is why the kill switch exists
* every order is capped in notional and gated by a daily loss limit that
  resets at the UTC day boundary, and by the same pre-trade risk gate the
  paper trader uses, fed with the real day's P&L
* a SELL signal exits the position under the same rule the backtest and the
  paper trader use (in profit, or confidence above 0.8). The first version
  only exited on stop/target, which was a different strategy from the one
  that was tested
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import pandas as pd

from .broker import Broker, new_client_id
from .indicators import add_indicators
from .journal import Journal, Position
from .risk import RiskLimits, check_buy
from .signals import combine, signals_at

SELL_OVERRIDE_CONFIDENCE = 0.8   # a SELL at a loss needs this much conviction


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
        self.day: Optional[str] = None

    # ------------------------------------------------------------------ safety
    def _roll_day(self, ts: int) -> None:
        """Reset the daily loss baseline when the bar belongs to a new UTC day."""
        day = datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
        if day != self.day:
            self.day = day
            self.day_start_equity = self.equity()

    def day_pnl(self) -> float:
        if self.day_start_equity is None:
            return 0.0
        return self.equity() - self.day_start_equity

    def halted(self) -> Optional[str]:
        if self.kill_file.exists():
            return f"kill switch present ({self.kill_file})"
        pnl = self.day_pnl()
        if pnl <= -self.cfg.max_daily_loss:
            return f"daily loss limit ({pnl:+.2f})"
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

        self._roll_day(ts)
        stop_reason = self.halted()
        if stop_reason:
            return [f"halted: {stop_reason}"]

        if self.position is not None and self.position.entry_ts != ts:
            exit_px, reason = self._exit_trigger(bar)
            if exit_px is not None:
                events.append(self._sell(exit_px, ts, reason))

        signal = self._signal_at_close()
        if signal is not None:
            self.journal.add_signal(self.cfg.product, ts, signal)
            if signal.side == "BUY" and self.position is None:
                events.append(self._buy(close, signal.confidence, ts))
            elif signal.side == "SELL" and self.position is not None:
                in_profit = close > self.position.entry_px
                if in_profit or signal.confidence > SELL_OVERRIDE_CONFIDENCE:
                    events.append(self._sell(close, ts, "signal"))

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

    def _buy(self, price: float, confidence: float, ts: int) -> str:
        equity = self.equity()
        decision = check_buy(equity, self.broker.balance(self.cfg.quote_currency),
                             1 if self.position else 0, self.day_pnl(), confidence,
                             self.cfg.limits)
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

    def _sell(self, price: float, ts: int, reason: str = "live_exit") -> str:
        pos = self.position
        client_id = new_client_id("sell")
        ack = self.broker.market_sell(self.cfg.product, pos.size, client_id)
        fill_px = ack.filled_px or price
        exit_fee = ack.fee or fill_px * pos.size * self.cfg.fee
        pnl = (fill_px - pos.entry_px) * pos.size - pos.entry_fee - exit_fee
        self.journal.close_position(pos.id, ts, fill_px, pnl, reason)
        self.position = None
        return (f"SELL {pos.size:.8f} {self.cfg.product} @ {fill_px:.2f} "
                f"pnl {pnl:+.2f} ({reason}) [{ack.status}]")

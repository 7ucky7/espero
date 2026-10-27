"""One long-only position, one bar at a time, filled when it is physically possible.

Two execution models, and the difference between them is the whole point:

    next_bar : signal from bar i's close -> fill at bar i+1's open   (honest)
    same_bar : signal from bar i's close -> fill at bar i's open     (look-ahead)

`same_bar` exists only to reproduce the bug the original repo shipped. Do not
use it to evaluate a strategy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from .indicators import add_indicators
from .signals import MIN_CONFIDENCE, Signal, combine, signals_at

TIMINGS = ("next_bar", "same_bar")
SIZINGS = ("risk2pct", "full")


@dataclass(frozen=True)
class Config:
    initial: float = 10_000.0
    fee: float = 0.001          # per side, e.g. 0.006 for a 60 bps taker
    slippage: float = 0.0005    # per side, applied to the fill price
    stop_pct: float = 0.05
    target_pct: float = 0.10
    timing: str = "next_bar"
    sizing: str = "risk2pct"
    risk_per_trade: float = 0.02
    warmup: int = 50

    def __post_init__(self) -> None:
        if self.timing not in TIMINGS:
            raise ValueError(f"timing must be one of {TIMINGS}")
        if self.sizing not in SIZINGS:
            raise ValueError(f"sizing must be one of {SIZINGS}")


@dataclass
class Trade:
    entry_i: int
    exit_i: int
    entry_px: float
    exit_px: float
    size: float
    fees: float
    pnl: float
    reason: str

    @property
    def return_pct(self) -> float:
        notional = self.entry_px * self.size
        return 100 * self.pnl / notional if notional else 0.0


@dataclass
class Result:
    equity: pd.Series
    trades: List[Trade] = field(default_factory=list)
    fees: float = 0.0

    def metrics(self) -> dict:
        eq = self.equity
        ret = eq.iloc[-1] / eq.iloc[0] - 1
        years = max(len(eq) / 365.25, 1e-9)
        dr = (eq / eq.shift(1) - 1).dropna()
        wins = [t for t in self.trades if t.pnl > 0]
        return {
            "total_return_pct": 100 * ret,
            "cagr_pct": 100 * ((1 + ret) ** (1 / years) - 1),
            "sharpe": float(np.sqrt(365) * dr.mean() / dr.std()) if dr.std() > 0 else 0.0,
            "max_drawdown_pct": 100 * float((eq / eq.cummax() - 1).min()),
            "trades": len(self.trades),
            "win_rate_pct": 100 * len(wins) / len(self.trades) if self.trades else 0.0,
            "avg_trade_pct": float(np.mean([t.return_pct for t in self.trades])) if self.trades else 0.0,
            "fees_paid": float(self.fees),
            "final_equity": float(eq.iloc[-1]),
        }


def run(df: pd.DataFrame, cfg: Config) -> Result:
    """Simulate one long-only position over `df` (needs open/high/low/close/dt)."""
    d = add_indicators(df).reset_index(drop=True)
    equity = np.zeros(len(d))
    cash = cfg.initial
    pos: Optional[dict] = None
    trades: List[Trade] = []
    fees = 0.0
    pending: Optional[Tuple[int, Signal]] = None

    for i in range(len(d)):
        row = d.iloc[i]
        px_open, px_close = float(row["open"]), float(row["close"])

        # ---- exits: gaps first, then intrabar stop (before target), then target
        if pos is not None:
            exit_px, reason = None, ""
            if px_open <= pos["stop"]:
                exit_px, reason = px_open, "gap_stop"
            elif px_open >= pos["target"]:
                exit_px, reason = px_open, "gap_target"
            elif float(row["low"]) <= pos["stop"]:
                exit_px, reason = pos["stop"], "stop"
            elif float(row["high"]) >= pos["target"]:
                exit_px, reason = pos["target"], "target"
            if exit_px is not None and i > pos["i"]:
                cash, fees, pos = _close(cash, fees, pos, exit_px, i, reason, cfg, trades)

        # ---- fills queued by the previous bar
        if pending is not None and pending[0] == i:
            _, sig = pending
            pending = None
            if sig.side == "BUY" and pos is None:
                pos, cash, fees = _open(cash, fees, i, px_open, sig.confidence, cfg)
            elif sig.side == "SELL" and pos is not None:
                cash, fees, pos = _close(cash, fees, pos, px_open, i, "signal", cfg, trades)

        # ---- signals from this bar's close
        if i >= cfg.warmup:
            combo = combine(signals_at(row, d.iloc[i - 1]))
            if combo and combo.confidence >= MIN_CONFIDENCE:
                if combo.side == "BUY" and pos is None:
                    if cfg.timing == "same_bar":
                        pos, cash, fees = _open(cash, fees, i, px_open, combo.confidence, cfg)
                    else:
                        pending = (i + 1, combo)
                elif combo.side == "SELL" and pos is not None:
                    in_profit = px_close > pos["entry_px"]
                    if in_profit or combo.confidence > 0.8:
                        if cfg.timing == "same_bar":
                            cash, fees, pos = _close(cash, fees, pos, px_open, i, "signal", cfg, trades)
                        else:
                            pending = (i + 1, combo)

        equity[i] = _equity(cash, pos, px_close)

    return Result(pd.Series(equity, index=d["dt"]), trades, fees)


def _notional(cfg: Config, cash: float, confidence: float) -> float:
    if cfg.sizing == "full":
        return max(cash * 0.98, 0.0)
    conf_factor = (confidence - MIN_CONFIDENCE) / (1 - MIN_CONFIDENCE)
    return max(cash * cfg.risk_per_trade * conf_factor, 0.0)


def _equity(cash: float, pos: Optional[dict], price: float) -> float:
    return cash if pos is None else cash + pos["size"] * price


def _open(cash: float, fees: float, i: int, px: float, confidence: float, cfg: Config):
    notional = _notional(cfg, cash, confidence)
    if notional < 1.0:
        return None, cash, fees
    fill = px * (1 + cfg.slippage)
    size = notional / fill
    fee = notional * cfg.fee
    pos = {
        "i": i,
        "entry_px": fill,
        "size": size,
        "entry_fee": fee,
        "stop": fill * (1 - cfg.stop_pct),
        "target": fill * (1 + cfg.target_pct),
    }
    return pos, cash - notional - fee, fees + fee


def _close(cash: float, fees: float, pos: dict, px: float, i: int, reason: str,
           cfg: Config, trades: List[Trade]):
    fill = px * (1 - cfg.slippage)
    fee = fill * pos["size"] * cfg.fee
    pnl = (fill - pos["entry_px"]) * pos["size"] - fee - pos["entry_fee"]
    trades.append(Trade(pos["i"], i, pos["entry_px"], fill, pos["size"],
                        fee + pos["entry_fee"], pnl, reason))
    return cash + fill * pos["size"] - fee, fees + fee, None

"""The gate every order passes through before it can cost money.

This lives below the strategy on purpose: a strategy that returns a BUY signal
has not been allowed to decide size, and cannot bypass any of these checks.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    max_position_pct: float = 0.25     # never more than 25% of equity in one position
    max_open_positions: int = 1
    daily_loss_cap_pct: float = 0.03   # stop trading for the day at -3%
    min_notional: float = 10.0
    risk_per_trade: float = 0.01       # 1% of equity is at risk if the stop triggers
    stop_pct: float = 0.05


@dataclass
class Decision:
    allowed: bool
    notional: float = 0.0
    reason: str = ""


def size_position(equity: float, confidence: float, limits: RiskLimits) -> float:
    """Risk-based sizing: notional such that (notional * stop_pct) is the risk budget."""
    if equity <= 0:
        return 0.0
    risk_budget = equity * limits.risk_per_trade
    by_risk = risk_budget / max(limits.stop_pct, 1e-9)
    by_cap = equity * limits.max_position_pct
    return max(0.0, min(by_risk, by_cap))


def check_buy(equity: float, cash: float, open_positions: int, day_pnl: float,
              confidence: float, limits: RiskLimits) -> Decision:
    if open_positions >= limits.max_open_positions:
        return Decision(False, reason="max open positions")
    if equity <= 0:
        return Decision(False, reason="no equity")
    if day_pnl <= -limits.daily_loss_cap_pct * equity:
        return Decision(False, reason="daily loss cap hit")
    notional = size_position(equity, confidence, limits)
    if notional < limits.min_notional:
        return Decision(False, reason=f"notional {notional:.2f} below minimum")
    if notional > cash:
        notional = cash * 0.99
        if notional < limits.min_notional:
            return Decision(False, reason="not enough cash")
    return Decision(True, notional=notional, reason="ok")


def check_sell(open_positions: int) -> Decision:
    if open_positions == 0:
        return Decision(False, reason="nothing to sell")
    return Decision(True, reason="ok")

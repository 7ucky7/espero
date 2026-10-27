"""Where idle cash goes, decided by a rule the bot can defend.

The question "T-bills or USDC?" has three inputs that matter and one that doesn't:

  yield            what it pays
  liquidity        how fast it becomes USD again
  counterparty     who is holding it, and what happens if they fail
  (not) narrative  "stablecoins are the future" is not an input

So each vehicle gets a stated risk penalty in *annual percentage points*, and the
bot picks the highest net yield above a threshold, keeping a liquidity reserve.

The penalty is a judgement, written down here so it can be argued with -- not
hidden in a model.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Vehicle:
    name: str
    apy: float              # current annual yield, e.g. 0.043
    risk_penalty: float     # annual pp deducted for custody / depeg / operational risk
    liquidity_days: int     # 0 = same day, 1 = T+1, 2 = T+2
    min_ticket: float       # smallest sensible transfer
    note: str = ""

    @property
    def net(self) -> float:
        return self.apy - self.risk_penalty


# Defaults reflect the state of the world in late 2026; pass your own to override.
DEFAULT_VEHICLES: List[Vehicle] = [
    Vehicle("SGOV", apy=0.0430, risk_penalty=0.005, liquidity_days=1, min_ticket=50,
            note="0-3m Treasury ETF, T+1, no credit risk"),
    Vehicle("BIL", apy=0.0425, risk_penalty=0.005, liquidity_days=1, min_ticket=50,
            note="1-3m Treasury ETF, T+1, no credit risk"),
    Vehicle("USDC", apy=0.0400, risk_penalty=0.020, liquidity_days=0, min_ticket=25,
            note="Coinbase reward rate; custody + depeg risk (Mar-2023 traded at $0.87)"),
    Vehicle("USD", apy=0.0, risk_penalty=0.0, liquidity_days=0, min_ticket=0,
            note="uninvested cash, always available"),
]


@dataclass
class CashDecision:
    vehicle: str
    amount: float
    reserve: float
    reason: str
    candidates: List[tuple]  # (name, net) for the audit trail


def choose(cash: float, vehicles: Optional[List[Vehicle]] = None,
           reserve_pct: float = 0.10, min_edge: float = 0.005) -> CashDecision:
    """Sweep everything above the reserve into the best net-yielding vehicle.

    Returns a decision even when the answer is "leave it in USD", with the reason.
    """
    vehicles = vehicles or DEFAULT_VEHICLES
    reserve = cash * reserve_pct
    sweepable = cash - reserve
    candidates = [(v.name, round(v.net, 4)) for v in vehicles]

    if sweepable <= 0:
        return CashDecision("USD", 0.0, cash, "nothing above the reserve", candidates)

    eligible = [v for v in vehicles if v.name != "USD" and v.min_ticket <= sweepable]
    if not eligible:
        return CashDecision("USD", 0.0, reserve,
                            f"sweepable ${sweepable:.0f} below every minimum ticket", candidates)

    best = max(eligible, key=lambda v: v.net)
    if best.net < min_edge:
        return CashDecision("USD", 0.0, reserve,
                            f"best net {best.net:.2%} below {min_edge:.2%} threshold", candidates)

    return CashDecision(
        vehicle=best.name,
        amount=sweepable,
        reserve=reserve,
        reason=f"{best.name}: {best.apy:.2%} yield - {best.risk_penalty:.2%} risk = "
               f"{best.net:.2%} net, T+{best.liquidity_days}",
        candidates=candidates,
    )


def carry(cash: float, apy: float, days: float) -> float:
    """Interest on idle cash for a holding period, simple accrual."""
    return max(cash, 0.0) * max(apy, 0.0) * max(days, 0.0) / 365.0

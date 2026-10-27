"""Resting limit orders, simulated against a recorded book, pessimistically.

The rules, each chosen to under-fill rather than over-fill:

* **post-only**: a bid at or above the best ask (or an ask at or below the
  best bid) is rejected, never crossed. A maker order that would take is not a
  maker order.
* **queue position**: when placed, the order joins the back of the queue at
  its price: everything resting at that price or better is ahead of it. It
  fills only after that much volume has traded at or through its price.
* **fills come from prints**: an order fills only for the volume that actually
  traded at or through its price since the last snapshot, after the queue
  ahead has been consumed. If the price touched but nothing printed, nothing
  filled.
* **gaps fill at the order price**, not better. Price improvement is a gift
  the simulator does not hand out.

Every fill carries the TCA fields: the mid when the decision was made, the
fill price, the delay, the fee. `tca.py` already knows how to read them.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .book import BookSnapshot


@dataclass
class LimitOrder:
    id: str
    side: str              # "buy" | "sell"
    price: float
    size: float
    placed_ts: float
    decision_mid: float    # mid at the moment the human said yes
    queue_ahead: float     # size ahead of us at our price when placed
    filled: float = 0.0
    fee_paid: float = 0.0
    status: str = "resting"   # resting | filled | cancelled | rejected
    fills: List["Fill"] = field(default_factory=list)

    @property
    def remaining(self) -> float:
        return max(0.0, self.size - self.filled)

    @property
    def avg_fill(self) -> Optional[float]:
        if not self.fills:
            return None
        return sum(f.price * f.size for f in self.fills) / sum(f.size for f in self.fills)


@dataclass
class Fill:
    order_id: str
    ts: float
    side: str
    price: float
    size: float
    fee: float
    decision_mid: float
    delay_s: float

    @property
    def slippage_bps(self) -> float:
        """Fill versus the mid at decision time, signed so positive is worse."""
        sign = 1 if self.side == "buy" else -1
        return 1e4 * sign * (self.price - self.decision_mid) / self.decision_mid


class PaperExchange:
    """Holds resting orders and a cash/inventory position for one product."""

    def __init__(self, cash: float, maker_fee: float = 0.0, taker_fee: float = 0.001):
        self.cash = cash
        self.inventory = 0.0
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee
        self.orders: Dict[str, LimitOrder] = {}
        self.fills: List[Fill] = []
        self.last: Optional[BookSnapshot] = None

    # ----------------------------------------------------------- placement
    def place_post_only(self, snap: BookSnapshot, side: str, price: float, size: float,
                        decision_mid: Optional[float] = None) -> LimitOrder:
        oid = uuid.uuid4().hex[:10]
        mid = decision_mid if decision_mid is not None else (snap.mid or price)
        order = LimitOrder(oid, side, price, size, snap.ts, mid, snap.depth_ahead(side, price))
        crosses = (side == "buy" and snap.best_ask is not None and price >= snap.best_ask) or \
                  (side == "sell" and snap.best_bid is not None and price <= snap.best_bid)
        if crosses:
            order.status = "rejected"
            return order
        if side == "buy" and price * size > self.cash:
            order.status = "rejected"
            return order
        if side == "sell" and size > self.inventory + 1e-12:
            order.status = "rejected"
            return order
        self.orders[oid] = order
        return order

    def cancel(self, oid: str) -> Optional[LimitOrder]:
        o = self.orders.pop(oid, None)
        if o:
            o.status = "cancelled"
        return o

    def cancel_all(self) -> List[LimitOrder]:
        return [self.cancel(oid) for oid in list(self.orders)]

    # ----------------------------------------------------------- matching
    def on_snapshot(self, snap: BookSnapshot) -> List[Fill]:
        """Advance every resting order by the trades in this snapshot."""
        new: List[Fill] = []
        for oid in list(self.orders):
            o = self.orders[oid]
            # volume that printed at or through our price, i.e. would have hit us
            if o.side == "buy":
                through = sum(t.size for t in snap.trades if t.price <= o.price)
            else:
                through = sum(t.size for t in snap.trades if t.price >= o.price)
            if through <= 0:
                continue
            eaten = min(through, o.queue_ahead)
            o.queue_ahead -= eaten
            available = through - eaten
            if available <= 0:
                continue
            qty = min(available, o.remaining)
            fee = qty * o.price * self.maker_fee
            f = Fill(o.id, snap.ts, o.side, o.price, qty, fee, o.decision_mid, snap.ts - o.placed_ts)
            o.fills.append(f)
            o.filled += qty
            o.fee_paid += fee
            if o.side == "buy":
                self.cash -= qty * o.price + fee
                self.inventory += qty
            else:
                self.cash += qty * o.price - fee
                self.inventory -= qty
            self.fills.append(f)
            new.append(f)
            if o.remaining <= 1e-12:
                o.status = "filled"
                del self.orders[oid]
        self.last = snap
        return new

    # -------------------------------------------------------------- marks
    def equity(self, snap: Optional[BookSnapshot] = None) -> float:
        snap = snap or self.last
        mid = snap.mid if snap and snap.mid else 0.0
        return self.cash + self.inventory * mid

    def resting(self) -> List[LimitOrder]:
        return list(self.orders.values())

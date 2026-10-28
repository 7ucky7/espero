"""打板 — "hit the board": chase the altcoin that is breaking out on abnormal volume.

The Chinese retail quant playbook, written down as rules so it can be tested
instead of felt. Hypothesis #10; the parameters below are frozen in
research/PREREGISTRATION_DEGEN.md and are not to be tuned here.

Three pieces, in the order money flows through them:

* `features` / `scan`: per-coin causal features on closed 5-minute bars, then
  a cross-sectional rank across the universe. Pure; the only I/O is the
  injected fetcher.
* `DegenTrader`: a multi-coin long-only paper book on the shared Journal. An
  entry fills at the NEXT bar's open; every stop, trail and target is in units
  of the coin's own ATR, so a coin that swings 3% an hour gets a wider stop than
  one that swings 0.3%.
* `replay` / `compare_venues`: the same trader driven over history, once per
  venue, so the backtest and the live loop cannot disagree about the rules.
"""
from __future__ import annotations

import logging
import tempfile
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from .indicators import atr as atr_
from .journal import Journal, PendingOrder, Position
from .ops import ts_zscore
from .paper import funding_due
from .risk import RiskLimits, check_buy
from .venues import FUNDING_PERIOD_S, VENUES

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- frozen (#10)
GRANULARITY = 300          # 5-minute bars
BURST_BARS = 12            # the last hour
VOL_WINDOW = 48            # the coin's own last 4 hours
ATR_PERIOD = 14
HIGH_WINDOW = 48           # a new 4-hour high is the trigger
VOL_Z_MIN = 2.0
NEAR_PCT = 0.005           # "near": within 0.5% of the high
NEAR_VOL_Z = 1.5
STOP_ATR = 2.0
TRAIL_ATR = 2.5
TARGET_ATR = 3.0
TIME_STOP_BARS = 36        # 3 hours
MAX_OPEN = 3
TOP = 60
MIN_DOLLAR_VOLUME = 2e6
WARMUP = max(VOL_WINDOW, HIGH_WINDOW) + 2
FEATURE_COLS = ("burst", "vol_z", "atr", "range_x", "breakout", "near")


# -------------------------------------------------------------------- features
def features(df: pd.DataFrame) -> pd.DataFrame:
    """Attach the frozen features to a bar frame, every one causal. Rows before
    the warmup carry NaN and can never be a candidate. Never mutates the input."""
    out = df.copy()
    close, high, low, vol = out["close"], out["high"], out["low"], out["volume"]
    out["burst"] = np.log(close / close.shift(BURST_BARS))
    out["vol_z"] = ts_zscore(np.log(vol + 1.0), VOL_WINDOW)
    out["atr"] = atr_(out, ATR_PERIOD)
    out["range_x"] = (high - low) / out["atr"].replace(0, np.nan)
    prior_high = high.shift(1).rolling(HIGH_WINDOW).max()
    out["breakout"] = (close > prior_high) & prior_high.notna()
    out["near"] = (close >= prior_high * (1 - NEAR_PCT)) & ~out["breakout"] & prior_high.notna()
    return out


def is_candidate(row) -> bool:
    """The entry rule, on one feature row. Liquidity is checked by the caller."""
    return bool(row["breakout"]) and float(row["vol_z"]) >= VOL_Z_MIN and float(row["burst"]) > 0 \
        and not np.isnan(float(row["atr"])) and float(row["atr"]) > 0


def status_of(row, liquid: bool = True) -> str:
    if row.get("error"):
        return "error"
    if is_candidate(row):
        return "BREAKOUT" if liquid else "breakout (illiquid)"
    if bool(row.get("near")) and float(row.get("vol_z") or 0) >= NEAR_VOL_Z:
        return "near"
    return ""


def rank_rows(rows: List[dict]) -> List[dict]:
    """Cross-sectional score: the mean percentile rank of burst, vol_z and
    range_x across whatever coins are in `rows`. Errors and warmup rows get no
    score and sort last."""
    ok = [r for r in rows if not r.get("error") and not any(pd.isna(r.get(c)) for c in ("burst", "vol_z", "range_x"))]
    if ok:
        frame = pd.DataFrame(ok)[["burst", "vol_z", "range_x"]]
        score = frame.rank(pct=True).mean(axis=1)
        for r, s in zip(ok, score):
            r["score"] = float(s)
    for r in rows:
        r.setdefault("score", float("nan"))
        r["status"] = status_of(r, r.get("dollar_volume", MIN_DOLLAR_VOLUME) >= MIN_DOLLAR_VOLUME)
    rows.sort(key=lambda r: (pd.isna(r["score"]), -(r["score"] if not pd.isna(r["score"]) else 0)))
    return rows


def last_row(product: str, df: pd.DataFrame, dollar_volume: float = float("nan")) -> dict:
    f = features(df).iloc[-1]
    row = {"product": product, "ts": int(f["ts"]), "close": float(f["close"]), "dollar_volume": dollar_volume}
    for c in FEATURE_COLS:
        row[c] = f[c]
    return row


def scan(universe: List[dict], fetch: Callable[[str, int, int], pd.DataFrame],
         pause: float = 0.12, sleep=time.sleep) -> List[dict]:
    """One row per coin in `universe` (dicts with `product` and `dollar_volume`,
    as `data.degen_universe` returns), ranked. A fetch failure is an error row,
    never a silent omission."""
    rows: List[dict] = []
    for i, u in enumerate(universe):
        p = u["product"]
        try:
            df = fetch(p, GRANULARITY, 300)
            if len(df) < WARMUP:
                raise ValueError(f"only {len(df)} bars")
            rows.append(last_row(p, df, float(u.get("dollar_volume", float("nan")))))
        except Exception as exc:  # noqa: BLE001 - shown in the table as an error row
            rows.append({"product": p, "error": f"{type(exc).__name__}: {exc}",
                         "dollar_volume": u.get("dollar_volume", float("nan"))})
        if pause and i < len(universe) - 1:
            sleep(pause)
    return rank_rows(rows)


# ---------------------------------------------------------------------- trader
@dataclass
class DegenConfig:
    venue: str = "binanceus"
    initial: float = 500.0
    fee: float = 0.0002         # per side, taker
    funding_8h: float = 0.0
    funding_period: int = FUNDING_PERIOD_S
    slippage: float = 0.0005
    granularity: int = GRANULARITY
    min_dollar_volume: float = MIN_DOLLAR_VOLUME
    limits: RiskLimits = field(default_factory=lambda: RiskLimits(max_open_positions=MAX_OPEN))

    @classmethod
    def for_venue(cls, venue: str, **kw) -> "DegenConfig":
        v = VENUES[venue]
        return cls(venue=venue, fee=v.taker_bps / 1e4, funding_8h=v.funding_bps_8h / 1e4,
                   funding_period=v.funding_period_s, **kw)


class DegenTrader:
    """Long-only, up to MAX_OPEN coins at once, one open position per coin.

    `on_cycle` takes one *feature row* per coin (the latest closed bar with the
    columns `features` adds) and does, in order: funding, pending fills at this
    bar's open, exits, trailing-stop ratchets, then new entries at the close.
    """

    def __init__(self, journal: Journal, cfg: DegenConfig):
        self.journal = journal
        self.cfg = cfg
        self.last_close: Dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        """In-memory state from the journal: at start, and again after a cycle
        failed and its writes were rolled back."""
        journal = self.journal
        cash, _ = journal.latest_equity()
        self.cash = cash if cash else self.cfg.initial
        self.positions: Dict[str, Position] = {p.product: p for p in journal.open_positions()}
        self.pending: Dict[str, PendingOrder] = {o.product: o for o in journal.pending_orders()}
        self.high_water: Dict[str, float] = {}
        for p in self.positions.values():
            # the same rule as a running book: start at the fill, then every later bar's
            # high (the fill bar is skipped there, so it is skipped here)
            row = journal.db.execute("SELECT MAX(high) AS h FROM bars WHERE product=? AND ts>?",
                                     (p.product, p.entry_ts)).fetchone()
            h = float(row["h"]) if row and row["h"] is not None else p.entry_px
            self.high_water[p.product] = max(h, p.entry_px)

    # ------------------------------------------------------------------ api
    def held(self) -> List[str]:
        """Products the book must keep watching: open positions and queued orders."""
        return sorted(set(self.positions) | set(self.pending))

    def on_cycle(self, rows: Dict[str, dict]) -> List[str]:
        """`rows`: product -> the newest closed bar with features. Bars already in
        the journal are skipped, so a repeated cycle is harmless. One cycle is
        one transaction: on any error it is rolled back, memory is reloaded and
        the error propagates."""
        try:
            with self.journal.transaction():
                return self._on_cycle(rows)
        except Exception:
            self._load()
            raise

    def _on_cycle(self, rows: Dict[str, dict]) -> List[str]:
        events: List[str] = []
        fresh: Dict[str, dict] = {}
        for product, bar in rows.items():
            prev_ts = self.journal.last_bar_ts(product)
            if self.journal.add_bar(product, bar):
                fresh[product] = dict(bar, prev_ts=prev_ts)
        if not fresh:
            return events
        ts = max(int(b["ts"]) for b in fresh.values())
        for product, bar in fresh.items():
            self.last_close[product] = float(bar["close"])

        # 1. funding, fills queued at the last close, exits, trail
        for product, bar in fresh.items():
            bts = int(bar["ts"])
            pos = self.positions.get(product)
            if pos is not None and self.cfg.funding_8h and bar["prev_ts"] is not None:
                paid = funding_due(int(bar["prev_ts"]), bts, pos.entry_ts, pos.size * float(bar["close"]),
                                   self.cfg.funding_8h, self.cfg.funding_period)
                if paid:
                    self.cash -= paid
                    pos.entry_fee += paid
                    self.journal.charge_position(pos.id, paid)
                    events.append(f"{product}: funding paid {paid:.4f}")
            order = self.pending.pop(product, None)
            if order is not None:
                if bts - order.created_ts > 2 * self.cfg.granularity:
                    self.journal.cancel_order(order.id, "stale")
                    events.append(f"{product}: cancelled stale {order.side}")
                else:
                    events.append(self._fill(order, bar, bts))
            pos = self.positions.get(product)
            if pos is None or pos.entry_ts == bts:
                continue
            px, reason = self._exit_trigger(pos, bar)
            if px is not None:
                events.append(self._close(pos, px, bts, reason))
                continue
            hw = max(self.high_water.get(product, pos.entry_px), float(bar["high"]))
            self.high_water[product] = hw
            trail = hw - TRAIL_ATR * float(bar["atr"]) if not pd.isna(bar["atr"]) else pos.stop
            if trail > pos.stop:
                pos.stop = trail
                self.journal.update_stop(pos.id, trail)
                events.append(f"{product}: trail -> {trail:.6g}")
            held_bars = (bts - pos.entry_ts) // self.cfg.granularity
            if held_bars >= TIME_STOP_BARS and product not in self.pending:
                o = PendingOrder(uuid.uuid4().hex[:8], product, bts, "SELL", pos.size, "time")
                self.pending[product] = o
                self.journal.add_order(o)
                events.append(f"{product}: time stop, queued SELL for next open")

        # 2. entries: the ranked scan over every coin that has a fresh bar
        # a held coin fetched only to manage its exit is not part of the frozen
        # universe, so it neither enters the cross-sectional rank nor gets bought
        ranked = rank_rows([dict(b, product=p) for p, b in fresh.items() if b.get("in_universe", True)])
        for r in ranked:
            if r["status"] != "BREAKOUT":
                continue
            p = r["product"]
            if p in self.positions or p in self.pending:
                continue
            if len(self.positions) + sum(1 for o in self.pending.values() if o.side == "BUY") >= MAX_OPEN:
                events.append(f"{p}: breakout, no slot")
                continue
            close, a = float(r["close"]), float(r["atr"])
            equity = self.equity()
            limits = replace(self.cfg.limits, stop_pct=STOP_ATR * a / close, max_open_positions=MAX_OPEN)
            held = len(self.positions) + sum(1 for o in self.pending.values() if o.side == "BUY")
            d = check_buy(equity=equity, cash=self.cash, open_positions=held,
                          day_pnl=self._day_pnl(equity, ts), confidence=float(r["score"]), limits=limits)
            if not d.allowed:
                events.append(f"{p}: breakout blocked, {d.reason}")
                continue
            size = d.notional / close
            o = PendingOrder(uuid.uuid4().hex[:8], p, ts, "BUY", size,
                             f"breakout score={r['score']:.2f} vol_z={r['vol_z']:.1f}")
            self.pending[p] = o
            self.journal.add_order(o)
            events.append(f"{p}: BREAKOUT score {r['score']:.2f} vol_z {r['vol_z']:.1f}, "
                          f"queued BUY {d.notional:.2f} for next open")

        self.journal.mark_equity(ts, self.cash, self.position_value())
        return events

    # -------------------------------------------------------------- money
    def _fill(self, order: PendingOrder, bar: dict, ts: int) -> str:
        product, open_px = order.product, float(bar["open"])
        if order.side == "BUY":
            px = open_px * (1 + self.cfg.slippage)
            a = float(bar["atr"])
            fee = px * order.size * self.cfg.fee
            self.cash -= px * order.size + fee
            pos = Position(uuid.uuid4().hex[:8], product, ts, px, order.size,
                           stop=px - STOP_ATR * a, target=px + TARGET_ATR * a, entry_fee=fee)
            self.positions[product] = pos
            self.high_water[product] = px
            self.journal.open_position(pos)
            self.journal.fill_order(order.id, ts, px, fee)
            return f"{product}: filled BUY {order.size:.6g} @ {px:.6g}  stop {pos.stop:.6g} target {pos.target:.6g}"
        pos = self.positions.get(product)
        if pos is None:
            self.journal.cancel_order(order.id, "no position")
            return f"{product}: SELL cancelled, nothing held"
        px = open_px * (1 - self.cfg.slippage)
        self.journal.fill_order(order.id, ts, px, 0.0)
        return self._close(pos, px, ts, order.reason, slip=False)

    def _exit_trigger(self, pos: Position, bar: dict):
        open_px = float(bar["open"])
        if open_px <= pos.stop:
            return open_px, "gap_stop"
        if open_px >= pos.target:
            return open_px, "gap_target"
        if float(bar["low"]) <= pos.stop:
            return pos.stop, "stop"
        if float(bar["high"]) >= pos.target:
            return pos.target, "target"
        return None, ""

    def _close(self, pos: Position, exit_px: float, ts: int, reason: str, slip: bool = True) -> str:
        px = exit_px * (1 - self.cfg.slippage) if slip else exit_px
        fee = px * pos.size * self.cfg.fee
        pnl = (px - pos.entry_px) * pos.size - fee - pos.entry_fee
        self.cash += px * pos.size - fee
        self.journal.close_position(pos.id, ts, px, pnl, reason)
        self.positions.pop(pos.product, None)
        self.high_water.pop(pos.product, None)
        return f"{pos.product}: exit {reason} @ {px:.6g}  pnl {pnl:+.2f}"

    def position_value(self) -> float:
        return sum(p.size * self.last_close.get(p.product, p.entry_px) for p in self.positions.values())

    def equity(self) -> float:
        return self.cash + self.position_value()

    def _day_pnl(self, equity: float, ts: int) -> float:
        """Since the first mark of the bar's UTC day, so replay and live agree."""
        day = datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
        row = self.journal.db.execute(
            "SELECT cash, position_value FROM equity WHERE date(ts,'unixepoch')=? ORDER BY ts LIMIT 1", (day,),
        ).fetchone()
        return 0.0 if row is None else equity - (row["cash"] + row["position_value"])


# ---------------------------------------------------------------------- replay
def replay(frames: Dict[str, pd.DataFrame], venue: str, initial: float = 500.0,
           dollar_volume: Optional[Dict[str, float]] = None, state: Optional[Path] = None) -> dict:
    """Drive `DegenTrader` over history: `frames` is product -> OHLCV bars with
    a `ts` column. Features are computed once per coin, causally, then the bars
    are fed in timestamp order exactly as the live loop would see them."""
    dollar_volume = dollar_volume or {}
    feats = {p: features(df.sort_values("ts").reset_index(drop=True)) for p, df in frames.items()}
    by_ts: Dict[int, Dict[str, dict]] = {}
    for p, f in feats.items():
        dv = dollar_volume.get(p, MIN_DOLLAR_VOLUME)
        for rec in f.iloc[WARMUP:].to_dict("records"):
            rec = dict(rec, dollar_volume=dv)
            rec.pop("dt", None)
            by_ts.setdefault(int(rec["ts"]), {})[p] = rec
    tmp = None
    if state is None:
        tmp = tempfile.TemporaryDirectory()
        state = Path(tmp.name) / f"degen-{venue}.db"
    journal = Journal(state)
    try:
        trader = DegenTrader(journal, DegenConfig.for_venue(venue, initial=initial))
        for ts in sorted(by_ts):
            trader.on_cycle(by_ts[ts])
        return summarize(journal, trader, venue, initial)
    finally:
        journal.close()
        if tmp:
            tmp.cleanup()


def summarize(journal: Journal, trader: DegenTrader, venue: str, initial: float) -> dict:
    closed = journal.closed_positions()
    pnls = [float(r["pnl"]) for r in closed]
    gross_win = sum(x for x in pnls if x > 0)
    gross_loss = -sum(x for x in pnls if x < 0)
    curve = [float(r["equity"]) for r in journal.equity_curve()]
    peak, dd = initial, 0.0
    for e in curve:
        peak = max(peak, e)
        dd = max(dd, peak - e)
    fees = sum(float(r["entry_fee"] or 0) for r in closed)
    if gross_loss > 0:
        pf = gross_win / gross_loss
    else:
        pf = float("inf") if gross_win > 0 else float("nan")
    reasons: Dict[str, int] = {}
    for r in closed:
        reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    return {
        "venue": venue, "name": VENUES[venue].name, "trades": len(pnls),
        "wins": sum(1 for x in pnls if x > 0),
        "hit": (sum(1 for x in pnls if x > 0) / len(pnls)) if pnls else float("nan"),
        "profit_factor": pf,
        "pnl": sum(pnls), "entry_fees": fees, "max_dd": dd, "max_dd_pct": dd / initial,
        "equity": trader.equity(), "open": len(trader.positions), "reasons": reasons,
    }


def compare_venues(frames: Dict[str, pd.DataFrame], venues: List[str], initial: float = 500.0,
                   dollar_volume: Optional[Dict[str, float]] = None) -> List[dict]:
    return [replay(frames, v, initial, dollar_volume) for v in venues]


# -------------------------------------------------------------------- verdict
CRITERIA = (
    ("trades >= 30", lambda r, _k: r["trades"] >= 30),
    ("profit factor > 1.3", lambda r, _k: r["profit_factor"] > 1.3),
    ("net P&L > 0", lambda r, _k: r["pnl"] > 0),
    ("max drawdown < 15%", lambda r, _k: r["max_dd_pct"] < 0.15),
    ("net P&L > 0 on Kraken fees", lambda _r, k: k is not None and k["pnl"] > 0),
)


def verdict(rows: List[dict]) -> List[dict]:
    """The five pre-registered criteria against the Binance.US row, with the
    Kraken row as the fee-robustness check. All five or FAIL."""
    by = {r["venue"]: r for r in rows}
    b, k = by.get("binanceus"), by.get("kraken")
    if b is None:
        return [{"criterion": c, "met": False, "actual": "no binanceus row"} for c, _ in CRITERIA]
    out = []
    for name, fn in CRITERIA:
        try:
            met = bool(fn(b, k))
        except (TypeError, KeyError):
            met = False
        out.append({"criterion": name, "met": met})
    return out

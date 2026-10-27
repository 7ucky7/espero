"""The wide panel: one DataFrame per field, dates down, coins across.

Cross-sectional research needs every asset on one calendar. This module
builds that from the same per-symbol loader the paper accounts use, keeps a
CSV copy so research runs are reproducible offline, and computes a *dated*
eligibility mask so a coin is only in the universe from the day it has enough
history and enough dollar volume -- never because it exists in 2026.

Survivorship is disclosed, not fixed: the coin list is today's list. What the
mask fixes is the other half of the bias, using a coin before it was tradable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from . import data, ops
from .xs import UNIVERSE

log = logging.getLogger(__name__)

FIELDS = ("open", "high", "low", "close", "volume")
DEFAULT_DIR = Path("data/panel")


@dataclass
class MarketPanel:
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame
    errors: Dict[str, str] = field(default_factory=dict)

    @property
    def dollar_volume(self) -> pd.DataFrame:
        return self.close * self.volume

    @property
    def coins(self) -> List[str]:
        return list(self.close.columns)

    @property
    def index(self) -> pd.DatetimeIndex:
        return self.close.index

    def first_trade(self) -> pd.Series:
        """First date with a close, per coin: the lower bound of 'listed since'."""
        return self.close.apply(lambda s: s.first_valid_index())

    def save(self, directory: Path = DEFAULT_DIR) -> Path:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        for f in FIELDS:
            getattr(self, f).to_csv(directory / f"{f}.csv")
        self.first_trade().rename("first_trade").to_csv(directory / "universe.csv")
        return directory

    @classmethod
    def load(cls, directory: Path = DEFAULT_DIR) -> "MarketPanel":
        directory = Path(directory)
        frames = {f: pd.read_csv(directory / f"{f}.csv", index_col=0, parse_dates=True) for f in FIELDS}
        return cls(**frames)

    def slice(self, start=None, end=None) -> "MarketPanel":
        kw = {f: getattr(self, f).loc[start:end] for f in FIELDS}
        return MarketPanel(**kw, errors=dict(self.errors))


def build(coins: Optional[List[str]] = None, span: str = "5y",
          fetch: Callable[[str, str], pd.DataFrame] = None,
          quote: str = "USD") -> MarketPanel:
    """Fetch every coin and align on the union calendar. Missing days stay NaN:
    a forward-filled price is a fabricated price."""
    coins = coins or UNIVERSE
    fetch = fetch or data.yahoo_daily
    per_field: Dict[str, Dict[str, pd.Series]] = {f: {} for f in FIELDS}
    errors: Dict[str, str] = {}
    for c in coins:
        try:
            df = fetch(f"{c}-{quote}", span)
        except Exception as exc:  # noqa: BLE001 - recorded, the panel is still built
            errors[c] = f"{type(exc).__name__}: {exc}"
            continue
        if df.empty:
            errors[c] = "empty"
            continue
        dt = pd.to_datetime(df["dt"], utc=True).dt.tz_localize(None).dt.normalize()
        for f in FIELDS:
            s = pd.Series(df[f].to_numpy(dtype=float), index=dt)
            per_field[f][c] = s[~s.index.duplicated(keep="last")].sort_index()
    if not per_field["close"]:
        raise RuntimeError(f"panel: nothing loaded ({len(errors)} errors)")
    frames = {f: pd.DataFrame(per_field[f]).sort_index() for f in FIELDS}
    for c, why in errors.items():
        log.warning("panel: %s not loaded: %s", c, why)
    return MarketPanel(**frames, errors=errors)


def build_coinbase(coins: Optional[List[str]] = None, days: int = 365, granularity: int = 3600,
                   fetch: Callable[[str, int, int], pd.DataFrame] = None,
                   quote: str = "USD") -> MarketPanel:
    """Intraday panel from Coinbase Exchange public candles, one calendar of
    `granularity`-second bars. Coins Coinbase does not list are recorded in
    `errors`, never substituted. A missing bar stays NaN."""
    coins = coins or UNIVERSE
    fetch = fetch or data.fetch
    per_field: Dict[str, Dict[str, pd.Series]] = {f: {} for f in FIELDS}
    errors: Dict[str, str] = {}
    for c in coins:
        try:
            df = fetch(f"{c}-{quote}", days, granularity)
        except Exception as exc:  # noqa: BLE001 - recorded, the panel is still built
            errors[c] = f"{type(exc).__name__}: {exc}"
            continue
        if df.empty:
            errors[c] = "empty"
            continue
        stamp = df["dt"] if "dt" in df else df["time"]
        dt = pd.to_datetime(stamp, utc=True).dt.tz_localize(None)
        for f in FIELDS:
            s = pd.Series(df[f].to_numpy(dtype=float), index=dt)
            per_field[f][c] = s[~s.index.duplicated(keep="last")].sort_index()
    if not per_field["close"]:
        raise RuntimeError(f"panel: nothing loaded ({len(errors)} errors)")
    frames = {f: pd.DataFrame(per_field[f]).sort_index() for f in FIELDS}
    for c, why in errors.items():
        log.warning("panel: %s not loaded: %s", c, why)
    return MarketPanel(**frames, errors=errors)


def eligible(p: MarketPanel, min_history: int = 365, min_dollar_volume: float = 1e6,
             volume_window: int = 30) -> pd.DataFrame:
    """True where a coin may be ranked on that date, using only that date's past.

    * at least `min_history` closes so far (the pre-registered 365)
    * trailing-median dollar volume above `min_dollar_volume`, so the top of a
      ranking cannot be a coin nobody can buy
    """
    history = p.close.notna().cumsum()
    liquid = ops.ts_mean(p.dollar_volume, volume_window) >= min_dollar_volume
    return (history >= min_history) & liquid & p.close.notna()

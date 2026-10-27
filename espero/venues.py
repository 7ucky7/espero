"""Venue registry: fees, symbol conventions and minimums in one place.

The fee number is the single most important field in this repo. A strategy with
a 1% edge per month is profitable at 2 bps and dead at 120 bps, and the code
should make that impossible to forget.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class Venue:
    name: str
    maker_bps: float
    taker_bps: float
    symbol: str          # "{base}" is substituted, e.g. "{base}-USD"
    min_notional: float
    api: str             # adapter class name in espero.broker
    asset_class: str = "crypto"   # "crypto" or "equity"


VENUES: Dict[str, Venue] = {
    "binanceus": Venue("Binance.US", maker_bps=0.0, taker_bps=2.0,
                       symbol="{base}USD", min_notional=5.0, api="BinanceUSBroker"),
    "kraken": Venue("Kraken", maker_bps=25.0, taker_bps=40.0,
                    symbol="{base}USD", min_notional=5.0, api="KrakenBroker"),
    "coinbase": Venue("Coinbase Advanced", maker_bps=60.0, taker_bps=120.0,
                      symbol="{base}-USD", min_notional=1.0, api="CoinbaseBroker"),
    "alpaca": Venue("Alpaca", maker_bps=0.0, taker_bps=0.0,
                    symbol="{base}", min_notional=1.0, api="AlpacaBroker",
                    asset_class="equity"),
}


def round_trip_bps(venue: str, maker: bool = False) -> float:
    v = VENUES[venue]
    side = v.maker_bps if maker else v.taker_bps
    return 2 * side


def symbol(venue: str, base: str) -> str:
    return VENUES[venue].symbol.format(base=base.upper())


def cheapest_for(bases: List[str], asset_class: str = "crypto") -> str:
    """Venue with the lowest taker fee in the given asset class."""
    eligible = [(k, v) for k, v in VENUES.items() if v.asset_class == asset_class]
    if not eligible:
        raise ValueError(f"no venue for {asset_class}")
    return min(eligible, key=lambda kv: (kv[1].taker_bps, kv[1].min_notional))[0]


def compare_table(bases: List[str]) -> List[tuple]:
    rows = []
    for key, v in VENUES.items():
        rows.append((v.name, v.maker_bps, v.taker_bps, round_trip_bps(key),
                     v.symbol.format(base=bases[0] if bases else "BTC"),
                     v.asset_class))
    return sorted(rows, key=lambda r: r[1])

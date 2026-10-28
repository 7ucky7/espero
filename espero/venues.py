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
    kind: str = "spot"            # "spot" or "perp"
    funding_bps_8h: float = 0.0   # perps: what a long pays every 8h (assumed constant)
    funding_period_s: int = 8 * 3600   # how often funding settles; Hyperliquid is hourly


FUNDING_PERIOD_S = 8 * 3600       # 00:00, 08:00, 16:00 UTC on most venues


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
    # A generic USDT/USD perpetual at base tier. The fees are typical of the large
    # perp venues; funding is the long-run average for BTC (0.01% per 8h, longs
    # pay). Real funding swings with the market and can flip sign or exceed 0.1%.
    # US residents cannot use Binance, Bybit or OKX perps; the regulated US route
    # (Coinbase perpetual-style futures) has its own schedule. Check it before
    # trusting these numbers for anything but a comparison.
    "perp": Venue("Perp (generic, base tier)", maker_bps=2.0, taker_bps=5.0,
                  symbol="{base}-PERP", min_notional=5.0, api="",
                  kind="perp", funding_bps_8h=1.0),
    # Hyperliquid base tier (no staking discount, no volume tier). Funding settles
    # hourly and the live rate is quoted per hour by the `info` endpoint; 1 bp per
    # 8h is the venue's idle-market baseline (0.01% per 8h ≈ 0.00125% per hour,
    # about 10.95% a year, the rate seen on idle coins). This row said 3.0 until
    # 2026-10-28; no running loop or published result used it.
    # Hyperliquid excludes US persons from trading; this row exists for paper books.
    "hyperliquid": Venue("Hyperliquid (base tier)", maker_bps=1.5, taker_bps=4.5,
                         symbol="{base}", min_notional=10.0, api="",
                         kind="perp", funding_bps_8h=1.0, funding_period_s=3600),
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

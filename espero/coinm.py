"""Binance COIN-M liquidation snapshots (data.binance.vision, 2023-06-25 → 2024-10-14).

Parsing for #26 (research/PREREGISTRATION_LIQ2.md), after the user's script
(binance_liq_daily.py): every row appears twice in Binance's file, and
de-duplicating on (time, price, last_fill_quantity) reproduces Tardis's feed.
Rows come out as `liq.liquidations` makes them, so #18's code reads them unchanged.
"""
from __future__ import annotations

import io

import pandas as pd

URL = ("https://data.binance.vision/data/futures/cm/daily/liquidationSnapshot/"
       "{sym}/{sym}-liquidationSnapshot-{day}.zip")
CONTRACT_USD = {"BTC": 100.0}          # Binance's documented COIN-M sizes; every other coin $10
DEFAULT_CONTRACT_USD = 10.0
COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT", "TRX", "LTC", "BCH", "ATOM",
         "ETC", "XLM", "NEAR", "OP", "FIL", "RUNE", "AAVE", "EOS", "THETA", "XTZ", "ALGO", "WLD"]
VENUE = "binance-coinm"


def symbol(coin: str) -> str:
    return f"{coin}USD_PERP"


def liquidations(text: str, coin: str) -> pd.DataFrame:
    """One snapshot file -> ts (seconds), side (`buy`: a short liquidated; `sell`: a long),
    usd = filled contracts x the contract size, venue."""
    df = pd.read_csv(io.StringIO(text))
    df = df.drop_duplicates(["time", "price", "last_fill_quantity"])
    side = df["side"].str.lower()
    keep = side.isin(("buy", "sell"))
    usd = df["last_fill_quantity"].astype(float) * CONTRACT_USD.get(coin, DEFAULT_CONTRACT_USD)
    return pd.DataFrame({"ts": df["time"].astype("int64").to_numpy()[keep.to_numpy()] / 1000.0,
                         "side": side[keep].to_numpy(), "usd": usd[keep].to_numpy(), "venue": VENUE})

"""#31's forward paper test (research/FORWARD_BIDS2.md): resting bids two ATRs under
#20's breakdowns, sold at the breakdown price or after 4 hours. It reads the 5-minute
files #24's job records (espero/lowsfwd.py) and runs #30's fill model (espero/bids.py)
with #31's settings. Nothing trades, and the running numbers decide nothing.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Sequence

import pandas as pd

from . import bids, liq, lows, lowsfwd
from .xs import UNIVERSE

FORWARD_FROM = "2026-10-30"
FORWARD_TO = "2027-03-31"
HALF = "2027-01-01"
NAMES = ("Oct-Dec", "Jan-Mar")
K_ATR = 2.0
HOLD = 48                     # four hours
TAKER_BARS = 48               # #24's trade
LEDGER = "bids_fwd_trades.csv"


def ledger(data: Path = lowsfwd.DATA, coins: Sequence[str] = UNIVERSE) -> pd.DataFrame:
    """Every breakdown in the window with its resting bid's fate, per coin."""
    out = []
    for c in coins:
        files = sorted((Path(data) / liq.symbol("binance-futures", c)).glob("*.zip"))
        if not files:
            continue
        b = lows.bars(pd.concat([lowsfwd.read(f.read_bytes()) for f in files], ignore_index=True))
        ev = bids.events(b, None, FORWARD_FROM, FORWARD_TO, k=K_ATR, hold=HOLD, taker_bars=TAKER_BARS)
        out.append(ev.assign(coin=c))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=bids.COLUMNS + ["coin"])


def criteria(ev: pd.DataFrame) -> List[dict]:
    return bids.criteria(ev, half=HALF, names=NAMES)


def run(state_dir: Path, data: Path = lowsfwd.DATA) -> dict:
    """Rebuild the ledger from the recorded files and say where it stands (it decides nothing)."""
    ev = ledger(data)
    ev.to_csv(Path(state_dir) / LEDGER, index=False, float_format="%.8g")
    done = ev[ev["complete"].astype(bool)]
    fills = done[done["filled"].astype(bool)]
    note = f"mark: {len(fills)} fills of {len(done)} breakdowns on {fills['day'].nunique()} days"
    if len(fills):
        note += f" ({1e4 * float(fills.groupby('day')['net'].mean().mean()):+.1f} bps a fill net; decides nothing)"
    return {"note": note, "equity": None}

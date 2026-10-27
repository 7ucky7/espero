"""Espero -- a small, honest crypto research harness.

Built after auditing a 12k-line trading bot that turned out never to have run.
The rule here is simple: no number is reported unless the fill that produced it
was physically possible.
"""
from __future__ import annotations

__version__ = "0.1.0"

from .backtest import Config, Result, Trade, run  # noqa: F401
from .indicators import add_indicators  # noqa: F401
from .signals import Signal, combine, signals_at  # noqa: F401

__all__ = ["Config", "Result", "Trade", "run", "add_indicators", "Signal", "combine",
           "signals_at", "__version__"]

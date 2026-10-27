"""Result tables and the equity chart.

The chart needs Pillow (`pip install espero[chart]`); everything else is
numpy + pandas only.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd

from .backtest import Config, Result, run

CASES = [
    ("as coded (look-ahead), 2% notional, 10 bps", Config(timing="same_bar", fee=0.001, sizing="risk2pct")),
    ("honest, 2% notional, 10 bps", Config(timing="next_bar", fee=0.001, sizing="risk2pct")),
    ("as coded (look-ahead), full size, 10 bps", Config(timing="same_bar", fee=0.001, sizing="full")),
    ("honest, full size, 10 bps", Config(timing="next_bar", fee=0.001, sizing="full")),
    ("honest, full size, 60 bps", Config(timing="next_bar", fee=0.006, sizing="full")),
]


def buy_and_hold(df: pd.DataFrame) -> dict:
    first, last = df["close"].iloc[0], df["close"].iloc[-1]
    years = len(df) / 365.25
    return {
        "total_return_pct": 100 * (last / first - 1),
        "cagr_pct": 100 * ((last / first) ** (1 / years) - 1),
    }


def matrix(df: pd.DataFrame) -> List[dict]:
    rows = []
    for label, cfg in CASES:
        m = run(df, cfg).metrics()
        m.update({"case": label, "timing": cfg.timing, "fee_bps": cfg.fee * 1e4,
                  "sizing": cfg.sizing})
        rows.append(m)
    return rows


def format_matrix(rows: List[dict], bh: dict) -> str:
    head = (f"{'case':46s} {'ret%':>8s} {'cagr%':>7s} {'sharpe':>6s} "
            f"{'maxdd%':>7s} {'n':>4s} {'win%':>5s} {'fees$':>9s}")
    lines = [head, "-" * len(head)]
    for r in rows:
        lines.append(
            f"{r['case']:46s} {r['total_return_pct']:8.2f} {r['cagr_pct']:7.2f} "
            f"{r['sharpe']:6.2f} {r['max_drawdown_pct']:7.2f} {r['trades']:4d} "
            f"{r['win_rate_pct']:5.1f} {r['fees_paid']:9.2f}"
        )
    lines.append("")
    lines.append(f"{'buy & hold':46s} {bh['total_return_pct']:8.2f} {bh['cagr_pct']:7.2f}")
    return "\n".join(lines)


def equity_png(df: pd.DataFrame, out: Path, initial: float = 10_000.0) -> Path:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("charting needs Pillow: pip install 'espero[chart]'") from exc

    series: Dict[str, List[float]] = {}
    for label, cfg in [
        ("as coded (look-ahead, 10bps)", Config(timing="same_bar", fee=0.001, sizing="full")),
        ("honest (next bar, 10bps)", Config(timing="next_bar", fee=0.001, sizing="full")),
        ("honest + real fees (60bps)", Config(timing="next_bar", fee=0.006, sizing="full")),
    ]:
        series[label] = list(run(df, cfg).equity.values)
    series["buy & hold"] = list(initial * df["close"] / df["close"].iloc[0])

    colors = {
        "as coded (look-ahead, 10bps)": (214, 69, 69),
        "honest (next bar, 10bps)": (47, 111, 208),
        "honest + real fees (60bps)": (122, 79, 208),
        "buy & hold": (58, 167, 109),
    }

    w, h, s = 1000, 460, 2

    def font(size: int):
        try:
            return ImageFont.load_default(size=size * s)
        except TypeError:  # older Pillow
            return ImageFont.load_default()

    img = Image.new("RGB", (w * s, h * s), (251, 251, 250))
    d = ImageDraw.Draw(img)
    left, right, top, bottom = 70, 20, 60, 46
    lo = min(min(v) for v in series.values()) * 0.96
    hi = max(max(v) for v in series.values()) * 1.04

    def X(i: int, n: int) -> float:
        return (left + (w - left - right) * i / max(n - 1, 1)) * s

    def Y(v: float) -> float:
        return (h - bottom - (h - top - bottom) * (v - lo) / (hi - lo)) * s

    start, end = df["dt"].iloc[0].date(), df["dt"].iloc[-1].date()
    d.text((left * s, 16 * s), f"BTC-USD · ${initial:,.0f} · {start} to {end}",
           fill=(30, 30, 30), font=font(17))
    d.text((left * s, 40 * s), "same four strategies; only the execution rule and the fee assumption change",
           fill=(120, 120, 115), font=font(11))

    for frac in (0, .25, .5, .75, 1.0):
        y = Y(lo + (hi - lo) * frac)
        d.line([(left * s, y), ((w - right) * s, y)], fill=(230, 230, 226), width=s)
        d.text(((left - 8) * s, y - 6 * s), f"${(lo + (hi - lo) * frac) / 1000:.1f}k",
               fill=(150, 150, 145), font=font(10), anchor="rm")

    for label, vals in series.items():
        pts = [(X(i, len(vals)), Y(v)) for i, v in enumerate(vals)]
        d.line(pts, fill=colors[label], width=int(1.9 * s), joint="curve")

    d.rectangle([(w - 344) * s, 56 * s, (w - 18) * s, 146 * s], fill=(251, 251, 250))
    y = 66
    for label in series:
        d.line([((w - 330) * s, y * s), ((w - 310) * s, y * s)], fill=colors[label], width=int(2.6 * s))
        d.text(((w - 302) * s, y * s), label, fill=(45, 45, 45), font=font(11), anchor="lm")
        y += 20

    for frac in (0, .33, .66, 1.0):
        d.text((X(int((len(df) - 1) * frac), len(df) - 1), (h - 22) * s),
               str((start.year + (end.year - start.year) * frac).__int__()),
               fill=(150, 150, 145), font=font(10), anchor="mm")

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.resize((w, h), Image.LANCZOS).save(out)
    return out

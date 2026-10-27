"""Static HTML dashboard for the paper accounts.

Reads tsmom.db / paper.db / live.db and writes one self-contained file with
inline SVG. No server, no framework, no JavaScript dependencies -- open it in
a browser and it works offline.

    espero dashboard                 # -> dashboard.html
    espero dashboard --open          # also opens it
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from . import tsmom as tsm


def _read_account(path: Path) -> list[dict]:
    if not path.exists():
        return []
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute("SELECT * FROM account ORDER BY ts").fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        db.close()
    return [dict(r) for r in rows]


def _sparkline(values: list[float], w: int = 640, h: int = 160, pad: int = 10) -> str:
    if len(values) < 2:
        return f'<svg width="{w}" height="{h}"><text x="20" y="80" fill="#777" font-size="13">' \
               f'not enough history yet</text></svg>'
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1e-9
    pts = []
    for i, v in enumerate(values):
        x = pad + (w - 2 * pad) * i / (len(values) - 1)
        y = h - pad - (h - 2 * pad) * (v - lo) / span
        pts.append(f"{x:.1f},{y:.1f}")
    up = values[-1] >= values[0]
    color = "#3aa76d" if up else "#d64545"
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{" ".join(pts)}"/>'
            f'</svg>')


def _positions(latest: dict) -> dict:
    """Mark held units to the latest available price."""
    units = json.loads(latest.get("units") or "{}")
    if not units:
        return {}
    try:
        px = tsm.closes(tsm.load_series("2y")).iloc[-1]
    except Exception:  # noqa: BLE001 - dashboard must render offline
        return {a: 0.0 for a in units}
    return {a: u * float(px[a]) for a, u in units.items() if a in px}


def render(tsmom_db: Path = Path("tsmom.db"), paper_db: Path = Path("paper.db"),
           live_db: Path = Path("live.db")) -> str:
    rows = _read_account(tsmom_db)
    cards = []
    total = 0.0

    if rows:
        latest = rows[-1]
        cash = float(latest["cash"])
        stored = json.loads(latest.get("positions") or "{}")
        positions = {k: float(v) for k, v in stored.items()} or _positions(latest)
        equity = cash + sum(positions.values())
        total += equity
        weights = json.loads(latest.get("weights") or "{}")
        # prefer the snapshot taken at decision time; live signals are a fallback
        sig = {k: float(v) for k, v in json.loads(latest.get("signals") or "{}").items()}
        sig_note = "as of the last decision"
        if not sig:
            try:
                sig = tsm.signals(tsm.load_series("2y"))
                sig_note = "live (no decision snapshot stored)"
            except Exception:  # noqa: BLE001
                sig_note = ""

        def _row(a: str, v: float) -> str:
            r = sig.get(a)
            txt = f"{100 * r:+.1f}%" if r is not None else "n/a"
            cls = "pos" if (r or 0) > 0 else "neg"
            return (f"<tr><td>{a}</td><td class='num'>{100 * weights.get(a, 0):.0f}%</td>"
                    f"<td class='num'>{v:,.2f}</td><td class='num {cls}'>{txt}</td></tr>")

        pos_rows = "".join(_row(a, v) for a, v in sorted(positions.items()) if v > 0) \
            or "<tr><td colspan='4' class='muted'>all cash</td></tr>"

        curve = [float(r["equity"]) for r in rows]
        as_of = datetime.fromtimestamp(int(latest["ts"]), timezone.utc).date()

        cards.append(f"""
        <section class="card">
          <h2>Cross-asset trend <span class="pill">paper</span></h2>
          <div class="big">${equity:,.2f}</div>
          <div class="sub">as of {as_of} · cash ${cash:,.2f} · {sum(1 for v in positions.values() if v > 0)} positions
            · {sig_note}</div>
          {_sparkline(curve)}
          <table>
            <thead><tr><th>asset</th><th class="num">target</th><th class="num">value</th>
            <th class="num">12m</th></tr></thead>
            <tbody>{pos_rows}</tbody>
          </table>
          <div class="sub">{len(rows)} journal entries · last action: {latest.get('note', '')}</div>
        </section>""")

    for name, path, label in (("Paper (bar strategy)", paper_db, "paper"),
                              ("Live (dry run)", live_db, "live")):
        if not path.exists():
            continue
        db = sqlite3.connect(path)
        try:
            eq = db.execute("SELECT ts, equity FROM equity ORDER BY ts").fetchall()
        except sqlite3.OperationalError:
            db.close()
            continue
        db.close()
        if not eq:
            continue
        values = [float(e[1]) for e in eq]
        total += values[-1]
        as_of = datetime.fromtimestamp(int(eq[-1][0]), timezone.utc).date()
        cards.append(f"""
        <section class="card">
          <h2>{name} <span class="pill">{label}</span></h2>
          <div class="big">${values[-1]:,.2f}</div>
          <div class="sub">as of {as_of} · {len(values)} marks</div>
          {_sparkline(values)}
        </section>""")

    if not cards:
        cards.append('<section class="card"><h2>No accounts yet</h2>'
                     '<div class="sub">run <code>espero tsmom --cash 100</code> first</div></section>')

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>espero dashboard</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ background:#111315; color:#e6e6e6; font:14px/1.5 ui-sans-serif,system-ui,-apple-system,sans-serif;
         margin:0; padding:32px; }}
  h1 {{ font-size:18px; font-weight:600; margin:0 0 4px; }}
  .muted, .sub {{ color:#8b8f94; font-size:12px; }}
  .wrap {{ max-width:760px; margin:0 auto; }}
  .top {{ display:flex; justify-content:space-between; align-items:baseline; margin-bottom:24px; }}
  .total {{ font-size:24px; font-weight:600; }}
  .card {{ background:#191c1f; border:1px solid #262a2e; border-radius:10px; padding:20px; margin-bottom:16px; }}
  h2 {{ font-size:14px; font-weight:600; margin:0 0 8px; color:#c9ced4; }}
  .pill {{ font-size:10px; text-transform:uppercase; letter-spacing:.06em; color:#8b8f94;
           border:1px solid #33383d; border-radius:999px; padding:2px 8px; margin-left:6px; }}
  .big {{ font-size:28px; font-weight:600; letter-spacing:-.02em; }}
  table {{ width:100%; border-collapse:collapse; margin-top:12px; font-size:13px; }}
  th {{ text-align:left; font-weight:500; color:#8b8f94; font-size:11px; text-transform:uppercase;
        letter-spacing:.04em; border-bottom:1px solid #262a2e; padding:6px 0; }}
  td {{ padding:6px 0; border-bottom:1px solid #1e2225; }}
  .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .pos {{ color:#3aa76d; }} .neg {{ color:#d64545; }}
  svg {{ display:block; margin:14px 0 4px; }}
  code {{ background:#24282c; padding:1px 5px; border-radius:4px; }}
</style></head>
<body><div class="wrap">
  <div class="top">
    <div><h1>espero</h1><div class="muted">paper accounts · generated {now}</div></div>
    <div class="total">${total:,.2f}</div>
  </div>
  {''.join(cards)}
  <div class="muted">Not investment advice. Paper only — no exchange keys, no orders.</div>
</div></body></html>"""


def write(out: str | Path = "dashboard.html", **paths) -> Path:
    out = Path(out)
    out.write_text(render(**paths), encoding="utf-8")
    return out

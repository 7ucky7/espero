"""Read-only scan of Polymarket liquidity rewards.

Answers one question: for a given bankroll, what would quoting near the mid in
each market actually pay per day, and how crowded is it already?

    python research/lp_scan.py --bankroll 500

No keys, no orders, no wallet. It reads public Gamma data and estimates your
pro-rata share of the daily reward pool.

The estimate is deliberately conservative: it treats all book liquidity as
qualifying, when only quotes inside the reward spread count. Real share can be
higher, competition is also real, and none of this accounts for inventory P&L --
which is the part that can lose money.
"""
from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request

GAMMA = "https://gamma-api.polymarket.com/markets"
UA = {"User-Agent": "espero-lp-scan/0.1"}


def fetch_page(limit: int, offset: int) -> list[dict]:
    q = urllib.parse.urlencode({
        "active": "true", "closed": "false", "limit": limit, "offset": offset,
        "order": "liquidity", "ascending": "false",
    })
    req = urllib.request.Request(GAMMA + "?" + q, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def scan(bankroll: float, pages: int, limit: int = 100) -> list[dict]:
    rows = []
    seen = set()
    for p in range(pages):
        for m in fetch_page(limit, p * limit):
            question = m.get("question") or ""
            if question in seen:
                continue
            seen.add(question)
            liquidity = float(m.get("liquidityNum") or 0)
            rewards = m.get("clobRewards") or []
            daily = sum(float(r.get("rewardsDailyRate") or 0) for r in rewards)
            if daily <= 0 or liquidity <= 0:
                continue
            share = bankroll / (liquidity + bankroll)
            rows.append({
                "market": question,
                "daily_rate": daily,
                "liquidity": liquidity,
                "share_pct": 100 * share,
                "est_per_day": daily * share,
                "pool_yield_pct": 100 * 365 * daily / liquidity,
                "end": (m.get("endDate") or "")[:10],
            })
    rows.sort(key=lambda r: -r["est_per_day"])
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bankroll", type=float, default=500.0)
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()

    rows = scan(args.bankroll, args.pages)
    if not rows:
        print("no reward markets found")
        return 1

    total_pool = sum(r["daily_rate"] for r in rows)
    print(f"{len(rows)} reward-paying markets scanned  |  {total_pool:,.0f} USDC/day paid out  "
          f"|  bankroll ${args.bankroll:,.0f}\n")
    head = f"{'market':46s} {'pool/day':>9s} {'liquidity':>12s} {'your share':>10s} {'$/day':>8s} {'pool APY':>8s}"
    print(head)
    print("-" * len(head))
    for r in rows[: args.top]:
        print(f"{r['market'][:46]:46s} {r['daily_rate']:9,.0f} {r['liquidity']:12,.0f} "
              f"{r['share_pct']:9.4f}% {r['est_per_day']:8.3f} {r['pool_yield_pct']:7.1f}%")

    best = rows[0]
    print(f"\nbest case at ${args.bankroll:,.0f}: ${best['est_per_day']:.3f}/day "
          f"= ${best['est_per_day']*30:.2f}/month = ${best['est_per_day']*365:.0f}/year")
    need = 15.0 / (best["est_per_day"] / args.bankroll) if best["est_per_day"] else float("inf")
    print(f"capital needed for $15/day at the best observed ratio: ${need:,.0f}")
    print("\nconservative estimate: all book liquidity treated as qualifying, no inventory P&L")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

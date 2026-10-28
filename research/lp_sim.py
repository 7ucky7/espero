"""Paper liquidity provision on one Polymarket market.

Quotes a bid and an ask around the mid, accrues the market's reward pool
pro-rata, and marks inventory to market. No keys, no orders.

    python research/lp_sim.py --match "Likud" --bankroll 500 --days 30

Honest limits, because this is a feasibility check and not a backtest:

* fills are inferred from midpoint crossings, not from the real book, so there
  is no queue position and no partial fills
* no adverse selection beyond the price move itself
* rewards assume full uptime, two-sided quotes at full size, and a constant
  liquidity pool -- all three are optimistic
* one market at a time, no hedging
"""
from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request

import pandas as pd

GAMMA = "https://gamma-api.polymarket.com/markets"
HISTORY = "https://clob.polymarket.com/prices-history"
UA = {"User-Agent": "espero-lp-sim/0.1"}


def get(url: str) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def find_market(match: str, pages: int = 3) -> dict:
    for page in range(pages):
        q = urllib.parse.urlencode({"active": "true", "closed": "false", "limit": 100,
                                    "offset": page * 100, "order": "liquidity",
                                    "ascending": "false"})
        for m in get(GAMMA + "?" + q):
            if match.lower() in (m.get("question") or "").lower() and m.get("clobRewards"):
                return m
    raise SystemExit(f"no reward-paying market matching {match!r}")


def price_history(token_id: str) -> pd.Series:
    q = urllib.parse.urlencode({"market": token_id, "interval": "max", "fidelity": 60})
    data = get(HISTORY + "?" + q).get("history", [])
    if not data:
        raise SystemExit("no price history")
    s = pd.Series([p["p"] for p in data],
                  index=pd.to_datetime([p["t"] for p in data], unit="s", utc=True))
    return s.sort_index()


def simulate(prices: pd.Series, bankroll: float, spread: float, reward_per_day: float,
             liquidity: float, days: int) -> dict:
    if len(prices) < 2:
        raise SystemExit("not enough price history")
    end = prices.index[-1]
    start = max(prices.index[0], end - pd.Timedelta(days=days))
    p = prices[prices.index >= start]

    cash = bankroll
    shares = 0.0
    rewards = 0.0
    fills = {"bid": 0, "ask": 0}
    max_inventory = 0.0
    quote_size = bankroll * 0.25          # notional per side

    for i in range(len(p) - 1):
        mid, nxt = float(p.iloc[i]), float(p.iloc[i + 1])
        bid, ask = mid - spread, mid + spread
        bid = max(bid, 0.01)
        ask = min(ask, 0.99)

        if nxt <= bid and cash >= quote_size:
            shares += quote_size / bid
            cash -= quote_size
            fills["bid"] += 1
        elif nxt >= ask and shares * ask >= quote_size * 0.25:
            sell_shares = min(shares, quote_size / ask)
            cash += sell_shares * ask
            shares -= sell_shares
            fills["ask"] += 1

        # pro-rata share of the daily pool for one hourly period of full uptime
        share = quote_size / (liquidity + quote_size)
        rewards += reward_per_day / 24 * share
        max_inventory = max(max_inventory, shares * mid)

    final_mid = float(p.iloc[-1])
    equity = cash + shares * final_mid
    return {
        "hours": len(p), "start": str(p.index[0])[:16], "end": str(p.index[-1])[:16],
        "rewards": rewards, "fills_bid": fills["bid"], "fills_ask": fills["ask"],
        "inventory_shares": shares, "inventory_value": shares * final_mid,
        "max_inventory": max_inventory, "cash": cash, "equity": equity,
        # trading P&L, before rewards. Rewards are never added to cash, so they must
        # not be subtracted here (the first version did, understating it by `rewards`)
        "net": equity - bankroll,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", default="Likud")
    ap.add_argument("--bankroll", type=float, default=500.0)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--spread", type=float, default=0.02, help="half-spread in probability")
    args = ap.parse_args()

    m = find_market(args.match)
    token = json.loads(m["clobTokenIds"])[0]
    rate = sum(float(r.get("rewardsDailyRate") or 0) for r in m["clobRewards"])
    liquidity = float(m.get("liquidityNum") or 0)

    print(f"market    {m['question']}")
    print(f"pool      ${rate:,.0f}/day   liquidity ${liquidity:,.0f}   "
          f"resolves {m.get('endDate','')[:10]}")
    prices = price_history(token)
    print(f"history   {len(prices)} hourly points  {prices.index[0].date()} .. {prices.index[-1].date()}")

    r = simulate(prices, args.bankroll, args.spread, rate, liquidity, args.days)
    print(f"\nwindow    {r['start']} .. {r['end']}  ({r['hours']}h)")
    print(f"fills     bid {r['fills_bid']}  ask {r['fills_ask']}")
    print(f"rewards   ${r['rewards']:.2f}")
    print(f"trading   ${r['net']:+.2f}   (inventory {r['inventory_shares']:.1f} shares "
          f"= ${r['inventory_value']:.2f}, peak ${r['max_inventory']:.2f})")
    print(f"equity    ${r['equity']:.2f}  = bankroll + trading P&L")
    print(f"total     ${r['equity'] - args.bankroll + r['rewards']:+.2f} "
          f"({100*(r['equity'] - args.bankroll + r['rewards'])/args.bankroll:+.1f}%) over {args.days}d")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

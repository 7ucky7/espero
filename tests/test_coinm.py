"""#26: COIN-M snapshots de-duplicated, sides named, contracts in dollars; and the
criteria's own halves."""
from __future__ import annotations

import unittest

from espero import coinm, liq
from tests.test_liq import table

HEADER = ("time,side,order_type,time_in_force,original_quantity,price,average_price,order_status,"
          "last_fill_quantity,accumulated_fill_quantity\n")


class TestSnapshot(unittest.TestCase):
    def test_duplicates_sides_and_dollars(self):
        rows = ["1700000000000,SELL,LIMIT,IOC,5,30000,30000,FILLED,5,5",
                "1700000000000,SELL,LIMIT,IOC,5,30000,30000,FILLED,5,5",      # Binance writes each row twice
                "1700000001500,BUY,LIMIT,IOC,3,30100,30100,FILLED,3,3"]
        btc = coinm.liquidations(HEADER + "\n".join(rows) + "\n", "BTC")
        self.assertEqual(list(btc["side"]), ["sell", "buy"])                  # sell: a long liquidated
        self.assertEqual(list(btc["usd"]), [500.0, 300.0])                     # $100 a BTC contract
        self.assertEqual(list(btc["ts"]), [1700000000.0, 1700000001.5])
        self.assertEqual(list(coinm.liquidations(HEADER + rows[2] + "\n", "ETH")["usd"]), [30.0])   # $10 otherwise

    def test_symbols(self):
        self.assertEqual(coinm.symbol("BTC"), "BTCUSD_PERP")
        self.assertEqual(len(coinm.COINS), 26)


class TestSplit(unittest.TestCase):
    def test_criteria_take_the_windows_own_halves(self):
        ev = table()
        days = sorted(ev["day"].unique())
        mid = days[len(days) // 2]
        ev.loc[ev["day"] >= mid, "y60"] = -ev.loc[ev["day"] >= mid, "y60"]
        self.assertFalse(liq.criteria(ev, split=mid)[2]["met"])


if __name__ == "__main__":
    unittest.main()

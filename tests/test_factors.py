import unittest

from qc_krx import factors

CAL = ["20180427", "20180430", "20180502", "20180503", "20180504", "20180626", "20180627", "20180628", "20180629"]


class FactorsTest(unittest.TestCase):
    def test_ex_dividend_date(self):
        # Record date on a trading day: ex-date is the trading day before it.
        self.assertEqual(factors.ex_dividend_date("20180629", CAL), "20180628")
        # Record date on a holiday (e.g. 12/31): use the last trading day on/before it, then step back.
        self.assertEqual(factors.ex_dividend_date("20180701", CAL), "20180628")
        self.assertIsNone(factors.ex_dividend_date("20180427", CAL))

    def test_split_and_dividend(self):
        # Samsung-like: 50:1 split on 20180504 (base 53,000 vs prev close 2,650,000), then a dividend.
        closes = [("20180502", 2650000), ("20180503", 2650000), ("20180504", 51900),
                  ("20180627", 47950), ("20180628", 47000), ("20180629", 46650)]
        bases = {"20180503": 2650000, "20180504": 53000, "20180627": 51900, "20180628": 47950, "20180629": 47000}
        rows, used = factors.factor_rows(closes, bases, [("20180630", 361.0)], CAL)
        div = 1 - 361 / 47950
        self.assertEqual(rows[0], ["20180502", factors._fmt(div), "0.02", "0"])
        self.assertEqual(rows[1], ["20180503", factors._fmt(div), "0.02", "2650000"])
        self.assertEqual(rows[2], ["20180627", factors._fmt(div), "1", "47950"])
        self.assertEqual(rows[-1], ["20501231", "1", "1", "0"])
        self.assertEqual([u["type"] for u in used], ["adjustment", "dividend"])
        # Adjusted price is continuous across the split: 2,650,000 x 0.02 = 53,000 = KRX base.
        self.assertAlmostEqual(2650000 * float(rows[1][2]), 53000)

    def test_dividend_on_adjustment_day_is_skipped(self):
        closes = [("20180627", 10000), ("20180628", 9000)]
        rows, used = factors.factor_rows(closes, {"20180628": 9500}, [("20180629", 500.0)], CAL)
        self.assertEqual([u["type"] for u in used], ["adjustment"])
        self.assertEqual(rows[0], ["20180627", "1", "0.95", "10000"])

    def test_no_events(self):
        rows, used = factors.factor_rows([("20180627", 100), ("20180628", 101)], {"20180628": 100}, [], CAL)
        self.assertEqual((rows, used), ([], []))

    def test_map_rows(self):
        self.assertEqual(factors.map_rows("0052D0", "20200102", "20261006", "20261006"),
                         [["20200102", "0052d0"], ["20501231", "0052d0"]])
        self.assertEqual(factors.map_rows("000030", "20141119", "20190212", "20261006"),
                         [["20141119", "000030"], ["20190212", "000030"]])


if __name__ == "__main__":
    unittest.main()

import datetime as dt
import gzip
import tempfile
import unittest
from pathlib import Path

from qc_krx import yahoo

KST = yahoo.KST


class FakeYahoo:
    """Daily bars for every weekday in the range; can rate limit."""

    def __init__(self, rate_limits=0):
        self.rate_limits, self.calls = rate_limits, []

    def __call__(self, symbol, start, end, interval):
        self.calls.append((symbol, start, end, interval))
        if self.rate_limits:
            self.rate_limits -= 1
            raise yahoo.RateLimited("429")
        out, d = [], start
        while d < end:
            if d.weekday() < 5:
                out.append((dt.datetime.combine(d, dt.time(0, 0), KST), 1000.0, 1010.0, 990.0, 1005.0, 100))
            d += dt.timedelta(days=1)
        return out


def no_sleep(_):
    pass


class YahooTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.today = dt.date(2026, 10, 12)  # Monday
        self.start = dt.date(2026, 10, 1)

    def tearDown(self):
        self.tmp.cleanup()

    def pacer(self, **kw):
        return yahoo.Pacer(min_interval=0, jitter=0, sleep=no_sleep, **kw)

    def test_daily_files_and_log(self):
        fake = FakeYahoo()
        n = yahoo.scrape_daily(self.root, ["005930", "069500"], self.start, pacer=self.pacer(), fetch=fake,
                               today=self.today)
        self.assertEqual(n, 2)
        self.assertEqual(fake.calls[0], ("005930.KS", self.start, self.today, "1d"))  # today excluded
        lines = (self.root / "raw" / "yahoo" / "daily" / "005930.csv").read_text().splitlines()
        self.assertEqual(lines[0], "date,open,high,low,close,volume")
        self.assertEqual(lines[1], "20261001,1000,1010,990,1005,100")
        log = (self.root / "raw" / "yahoo" / "fetch_log.csv").read_text().splitlines()
        self.assertEqual(len(log), 3)  # header + 2 requests

    def test_rate_limit_backoff_then_stop(self):
        waits = []
        pacer = yahoo.Pacer(min_interval=0, jitter=0, backoff=(5, 10), sleep=waits.append)
        yahoo.scrape_daily(self.root, ["005930"], self.start, pacer=pacer, fetch=FakeYahoo(rate_limits=2),
                           today=self.today)
        self.assertEqual(waits[:2], [5, 10])  # backed off twice, then succeeded
        with self.assertRaises(yahoo.Stopped):
            yahoo.scrape_daily(self.root, ["000660"], self.start,
                               pacer=yahoo.Pacer(min_interval=0, jitter=0, backoff=(1,), sleep=no_sleep),
                               fetch=FakeYahoo(rate_limits=99), today=self.today)

    def test_request_budget(self):
        with self.assertRaises(yahoo.Stopped):
            yahoo.scrape_daily(self.root, ["005930", "000660", "069500"], self.start,
                               pacer=self.pacer(max_requests=2), fetch=FakeYahoo(), today=self.today)
        # What was fetched before stopping is kept.
        self.assertEqual(len(list((self.root / "raw" / "yahoo" / "daily").iterdir())), 2)

    def test_out_of_scope_market(self):
        with self.assertRaises(yahoo.YahooError):
            yahoo.symbol_for("035720", "KOSDAQ")
        self.assertEqual(yahoo.symbol_for("069500", "ETF"), "069500.KS")

    def test_top_codes(self):
        d = self.root / "raw" / "krx" / "KOSPI" / "2026"
        d.mkdir(parents=True)
        with gzip.open(d / "20261008.csv.gz", "wt", encoding="utf-8") as f:
            f.write("ISU_CD,MKTCAP\n000001,10\n000002,30\n000003,20\n")
        self.assertEqual(yahoo.top_codes(self.root, 2), ["000002", "000003"])
        self.assertEqual(yahoo.known_markets(self.root)["000001"], "KOSPI")


if __name__ == "__main__":
    unittest.main()

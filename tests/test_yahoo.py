import datetime as dt
import gzip
import tempfile
import unittest
import zipfile
from pathlib import Path

from qc_krx import yahoo

KST = yahoo.KST


def bars_for(day: dt.date, n: int = 3, start_price: int = 1000):
    return [(dt.datetime.combine(day, dt.time(9, i), KST), start_price + i, start_price + i + 5,
             start_price + i - 5, start_price + i, 100 + i) for i in range(n)]


class FakeYahoo:
    """Returns bars for every weekday except the ones in ``holidays``; can rate limit."""

    def __init__(self, holidays=(), rate_limits=0):
        self.holidays, self.rate_limits, self.calls = set(holidays), rate_limits, []

    def __call__(self, symbol, start, end, interval):
        self.calls.append((symbol, start, end, interval))
        if self.rate_limits:
            self.rate_limits -= 1
            raise yahoo.RateLimited("429")
        out, d = [], start
        while d < end:
            if d.weekday() < 5 and d not in self.holidays:
                out += bars_for(d)
                # a pre-market bar that must be dropped
                out.append((dt.datetime.combine(d, dt.time(8, 30), KST), 1, 1, 1, 1, 1))
            d += dt.timedelta(days=1)
        return out


def no_sleep(_):
    pass


class YahooTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.today = dt.date(2026, 10, 12)  # Monday

    def tearDown(self):
        self.tmp.cleanup()

    def pacer(self, **kw):
        return yahoo.Pacer(min_interval=0, jitter=0, sleep=no_sleep, **kw)

    def test_minute_backfill_chunks_holidays_and_resume(self):
        holiday = dt.date(2026, 10, 7)
        fake = FakeYahoo(holidays={holiday})
        stats = yahoo.scrape_minute(self.root, ["005930"], pacer=self.pacer(), fetch=fake, today=self.today)
        # 28-day lookback in chunks of at most 7 days: 4 requests, all for 005930.KS 1m.
        self.assertEqual(len(fake.calls), 4)
        self.assertTrue(all(c[0] == "005930.KS" and c[3] == "1m" and (c[2] - c[1]).days <= 7 for c in fake.calls))
        self.assertEqual(fake.calls[-1][2], self.today)  # nothing from today (unfinished)
        rows = yahoo.read_minute_day(yahoo.minute_path(self.root, "005930", "20261008"))
        self.assertEqual([r["time"] for r in rows], ["09:00", "09:01", "09:02"])  # 08:30 dropped
        self.assertEqual(rows[0]["open"], "1000")
        # The holiday is stored as an empty file so it isn't requested again.
        self.assertEqual(yahoo.read_minute_day(yahoo.minute_path(self.root, "005930", "20261007")), [])
        self.assertEqual(stats["empty_days"], 1)
        # A second run on the same day requests nothing; a week later only the new days.
        fake.calls.clear()
        yahoo.scrape_minute(self.root, ["005930"], pacer=self.pacer(), fetch=fake, today=self.today)
        self.assertEqual(fake.calls, [])
        yahoo.scrape_minute(self.root, ["005930"], pacer=self.pacer(), fetch=fake,
                            today=self.today + dt.timedelta(days=7))
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0][1], self.today)

    def test_rate_limit_backoff_then_stop(self):
        waits = []
        fake = FakeYahoo(rate_limits=2)
        pacer = yahoo.Pacer(min_interval=0, jitter=0, backoff=(5, 10), sleep=waits.append)
        yahoo.scrape_minute(self.root, ["005930"], pacer=pacer, fetch=fake, today=self.today)
        self.assertEqual(waits[:2], [5, 10])  # backed off twice, then succeeded
        fake = FakeYahoo(rate_limits=99)
        with self.assertRaises(yahoo.Stopped):
            yahoo.scrape_minute(self.root, ["000660"], pacer=yahoo.Pacer(min_interval=0, jitter=0, backoff=(1,),
                                                                         sleep=no_sleep), fetch=fake, today=self.today)

    def test_request_budget(self):
        with self.assertRaises(yahoo.Stopped):
            yahoo.scrape_minute(self.root, ["005930"], pacer=self.pacer(max_requests=2), fetch=FakeYahoo(),
                                today=self.today)
        # What was fetched before stopping is kept.
        self.assertTrue(any((self.root / "raw" / "yahoo" / "minute" / "005930").iterdir()))
        log = (self.root / "raw" / "yahoo" / "fetch_log.csv").read_text().splitlines()
        self.assertEqual(len(log), 3)  # header + 2 requests

    def test_out_of_scope_market(self):
        with self.assertRaises(yahoo.YahooError):
            yahoo.symbol_for("035720", "KOSDAQ")
        self.assertEqual(yahoo.symbol_for("069500", "ETF"), "069500.KS")

    def test_lean_minute_file(self):
        day = dt.date(2026, 10, 8)
        yahoo.write_minute_day(yahoo.minute_path(self.root, "005930", "20261008"),
                               [(dt.datetime.combine(day, dt.time(9, 0), KST), 264000.0, 264500.0, 263500.0, 264250.0, 1200)])
        yahoo.write_minute_day(yahoo.minute_path(self.root, "005930", "20261009"), [])
        self.assertEqual(yahoo.build_lean_minute(self.root), 1)
        path = self.root / "lean" / "equity" / "krx" / "minute" / "005930" / "20261008_trade.zip"
        with zipfile.ZipFile(path) as z:
            self.assertEqual(z.namelist(), ["20261008_005930_minute_trade.csv"])
            line = z.read("20261008_005930_minute_trade.csv").decode().strip()
        self.assertEqual(line, "32400000,2640000000,2645000000,2635000000,2642500000,1200")
        self.assertEqual(yahoo.build_lean_minute(self.root), 0)  # up to date

    def test_minute_limits(self):
        with self.assertRaises(yahoo.YahooError):
            yahoo.scrape_minute(self.root, [f"{i:06d}" for i in range(yahoo.MAX_MINUTE_CODES + 1)],
                                pacer=self.pacer(), fetch=FakeYahoo(), today=self.today)
        yahoo.scrape_minute(self.root, ["005930"], pacer=self.pacer(), fetch=FakeYahoo(), today=self.today)
        yahoo.build_lean_minute(self.root)
        lean = self.root / "lean" / "equity" / "krx" / "minute" / "005930"
        self.assertTrue((lean / "20260915_trade.zip").exists())
        self.assertGreater(yahoo.prune_minute(self.root, keep_days=7, today=self.today), 0)
        days = sorted(p.name[:8] for p in (self.root / "raw" / "yahoo" / "minute" / "005930").iterdir())
        self.assertEqual(days[0], "20261005")
        yahoo.build_lean_minute(self.root)  # LEAN files follow the raw ones
        self.assertFalse((lean / "20260915_trade.zip").exists())
        self.assertTrue((lean / "20261005_trade.zip").exists())

    def test_top_codes(self):
        d = self.root / "raw" / "krx" / "KOSPI" / "2026"
        d.mkdir(parents=True)
        with gzip.open(d / "20261008.csv.gz", "wt", encoding="utf-8") as f:
            f.write("ISU_CD,MKTCAP\n000001,10\n000002,30\n000003,20\n")
        self.assertEqual(yahoo.top_codes(self.root, 2), ["000002", "000003"])
        self.assertEqual(yahoo.known_markets(self.root)["000001"], "KOSPI")


if __name__ == "__main__":
    unittest.main()

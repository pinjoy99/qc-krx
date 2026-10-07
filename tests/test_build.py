import tempfile
import unittest
import zipfile
from pathlib import Path

from qc_krx import build

DAILY_CSV = (
    "﻿basDt,종목코드,종목명,mrktCtg,clpr,vs,fltRt,mkp,hipr,lopr,trqu,trPrc,lstgStCnt,mrktTotAmt\n"
    "20261006,005930,삼성전자,KOSPI,272000,-4000,-1.45,278500,279000,270000,12913819,1,1,1\n"
    "20261006,000001,무거래,KOSDAQ,1000,0,0,0,0,0,0,0,1,1\n"
)


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "raw" / "daily").mkdir(parents=True)
        (self.root / "raw" / "history").mkdir(parents=True)
        (self.root / "raw" / "daily" / "quotes_20261006.csv").write_text(DAILY_CSV, encoding="utf-8")
        (self.root / "raw" / "history" / "005930.csv").write_text(
            "date,close,volume\n20261002,276000,11501250\n20261006,272000,12913819\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_daily_archive_overrides_history_and_fills_zero_ohl(self):
        daily = build.load_daily_archive(self.root)
        self.assertEqual(daily["005930"]["20261006"], (278500, 279000, 270000, 272000, 12913819, "daily"))
        # No-trade day: open/high/low reported as 0 fall back to close.
        self.assertEqual(daily["000001"]["20261006"], (1000, 1000, 1000, 1000, 0, "daily"))

        hist = build.load_history(self.root / "raw" / "history" / "005930.csv")
        merged = build.merge(hist, daily["005930"])
        self.assertEqual(merged[0], ("20261002", (276000, 276000, 276000, 276000, 11501250, "history")))
        self.assertEqual(merged[1][1][-1], "daily")

    def test_build_writes_ohlcv_and_lean(self):
        self.assertEqual(build.build(self.root), 2)
        csv_text = (self.root / "ohlcv" / "005930.csv").read_text(encoding="utf-8")
        self.assertIn("20261006,278500,279000,270000,272000,12913819,daily", csv_text)
        with zipfile.ZipFile(self.root / "lean" / "equity" / "krx" / "daily" / "005930.zip") as z:
            lines = z.read("005930.csv").decode().splitlines()
        self.assertEqual(lines[-1], "20261006 00:00,2785000000,2790000000,2700000000,2720000000,12913819")


if __name__ == "__main__":
    unittest.main()

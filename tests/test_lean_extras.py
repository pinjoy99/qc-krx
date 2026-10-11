import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from qc_krx import lean_extras
from qc_krx.krx_api import write_day


def kospi_row(d, code, close, cap):
    return {"BAS_DD": d, "ISU_CD": code, "ISU_NM": "x", "MKT_NM": "KOSPI", "TDD_CLSPRC": close,
            "ACC_TRDVOL": "10", "ACC_TRDVAL": "1,000", "MKTCAP": cap, "LIST_SHRS": "5"}


class LeanExtrasTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_universe_files(self):
        write_day(self.root / "raw" / "krx" / "KOSPI" / "2018" / "20180504.csv.gz",
                  [kospi_row("20180504", "005930", "51900", "333"), kospi_row("20180504", "000001", "", "1")])
        write_day(self.root / "raw" / "krx" / "ETF" / "2018" / "20180504.csv.gz",
                  [{"BAS_DD": "20180504", "ISU_CD": "069500", "TDD_CLSPRC": "30000", "ACC_TRDVOL": "1",
                    "ACC_TRDVAL": "30000", "MKTCAP": "9", "LIST_SHRS": "3"}])
        write_day(self.root / "raw" / "krx" / "KOSPI" / "2018" / "20180505.csv.gz", [])  # holiday
        lean = self.root / "lean"
        self.assertEqual(lean_extras.build_universe(self.root, lean), 1)
        with zipfile.ZipFile(lean / "equity" / "krx" / "universe" / "20180504.zip") as z:
            lines = z.read("20180504.csv").decode().splitlines()
        self.assertEqual(lines, ["code,market,close,volume,value,market_cap,shares",
                                 "005930,KOSPI,51900,10,1000,333,5",
                                 "069500,ETF,30000,1,30000,9,3"])
        # Up to date -> not rewritten; a newer raw file -> rewritten.
        self.assertEqual(lean_extras.build_universe(self.root, lean), 0)
        raw = self.root / "raw" / "krx" / "KOSPI" / "2018" / "20180504.csv.gz"
        future = time.time() + 10
        os.utime(raw, (future, future))
        self.assertEqual(lean_extras.build_universe(self.root, lean), 1)

    def test_index_files(self):
        (self.root / "index").mkdir()
        (self.root / "index" / "KOSPI200.csv").write_text(
            "date,open,high,low,close,volume,value,market_cap\n20100104,221.67,223.49,221.66,223.49,85967328,1,1\n")
        self.assertEqual(lean_extras.build_lean_indices(self.root, self.root / "lean"), 1)
        with zipfile.ZipFile(self.root / "lean" / "index" / "krx" / "daily" / "kospi200.zip") as z:
            self.assertEqual(z.read("kospi200.csv").decode(), "20100104 00:00,221.67,223.49,221.66,223.49,85967328\n")


if __name__ == "__main__":
    unittest.main()

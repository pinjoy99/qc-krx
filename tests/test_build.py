import tempfile
import unittest
import zipfile
from pathlib import Path

from qc_krx import build
from qc_krx.krx_api import write_day


def krx_row(d, code, o, h, l, c, v, change="0", market="KOSPI"):
    return {"BAS_DD": d, "ISU_CD": code, "ISU_NM": "x", "MKT_NM": market, "TDD_OPNPRC": o, "TDD_HGPRC": h,
            "TDD_LWPRC": l, "TDD_CLSPRC": c, "CMPPREVDD_PRC": change, "ACC_TRDVOL": v}


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        raw = self.root / "raw" / "krx" / "KOSPI" / "2026"
        write_day(raw / "20261002.csv.gz", [krx_row("20261002", "005930", "273,500", "277,000", "271,500",
                                                    "276,000", "11,501,250")])
        write_day(raw / "20261006.csv.gz", [krx_row("20261006", "005930", "278500", "279000", "270000", "272000",
                                                    "12913819", "-4000"),
                                            krx_row("20261006", "000001", "0", "0", "0", "1000", "0")])
        # aikstockdata files are check-only: they must not create or change any output.
        (self.root / "raw" / "history").mkdir(parents=True)
        (self.root / "raw" / "history" / "999999.csv").write_text("date,close,volume\n20261006,5,5\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_writes_ohlcv_and_lean_from_krx_only(self):
        lean = self.root / "lean" / "equity" / "krx"
        stale = lean / "daily" / "999999.zip"  # left over from a build that used aikstockdata
        stale.parent.mkdir(parents=True)
        stale.write_bytes(b"")
        self.assertEqual(build.build(self.root), 2)
        csv_text = (self.root / "ohlcv" / "005930.csv").read_text(encoding="utf-8")
        self.assertIn("20261006,278500,279000,270000,272000,12913819,krx", csv_text)
        # No-trade day: open/high/low reported as 0 fall back to the close.
        self.assertIn("20261006,1000,1000,1000,1000,0,krx", (self.root / "ohlcv" / "000001.csv").read_text())
        with zipfile.ZipFile(lean / "daily" / "005930.zip") as z:
            lines = z.read("005930.csv").decode().splitlines()
        self.assertEqual(lines[-1], "20261006 00:00,2785000000,2790000000,2700000000,2720000000,12913819")
        self.assertFalse((self.root / "ohlcv" / "999999.csv").exists())
        self.assertFalse(stale.exists())
        self.assertIn("005930,x,KOSPI,20261002,20261006", (self.root / "securities.csv").read_text())


if __name__ == "__main__":
    unittest.main()

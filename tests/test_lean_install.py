import json
import tempfile
import unittest
from pathlib import Path

from qc_krx import lean_install
from qc_krx.krx_api import write_day


class LeanInstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root, self.lean = base / "data", base / "Lean" / "Data"
        (self.root / "lean" / "equity" / "krx" / "daily").mkdir(parents=True)
        (self.root / "lean" / "equity" / "krx" / "daily" / "005930.zip").write_bytes(b"zip")
        row = lambda d, c: {"BAS_DD": d, "ISU_CD": "005930", "TDD_CLSPRC": c}
        # Fri 2018-02-16 is Seollal: no prices that day.
        for d in ("20180214", "20180215", "20180219"):
            write_day(self.root / "raw" / "krx" / "KOSPI" / "2018" / f"{d}.csv.gz", [row(d, "100")])
        write_day(self.root / "raw" / "krx" / "ETF" / "2018" / "20180216.csv.gz", [row("20180216", "")])
        (self.lean / "market-hours").mkdir(parents=True)
        (self.lean / "symbol-properties").mkdir(parents=True)
        (self.lean / "market-hours" / "market-hours-database.json").write_text(json.dumps(
            {"entries": {"Index-krx-[*]": {"holidays": ["1/1/2018", "2/16/2018"]}}}))
        (self.lean / "symbol-properties" / "symbol-properties-database.csv").write_text(
            "market,symbol,type,description,quote_currency,contract_multiplier,minimum_price_variation,lot_size\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_trading_holidays(self):
        self.assertEqual(lean_install.trading_holidays(self.root), ["2/16/2018"])

    def test_install_is_idempotent(self):
        for _ in range(2):
            stats = lean_install.install(self.root, self.lean)
        self.assertEqual(stats["securities"], 1)
        self.assertEqual(stats["holidays_only_in_data"], [])
        self.assertTrue((self.lean / "equity" / "krx" / "daily" / "005930.zip").exists())
        entry = json.loads((self.lean / "market-hours" / "market-hours-database.json").read_text())["entries"]["Equity-krx-[*]"]
        self.assertEqual(entry["exchangeTimeZone"], "Asia/Seoul")
        self.assertEqual(entry["holidays"], ["1/1/2018", "2/16/2018"])
        self.assertIn({"start": "09:00:00", "end": "15:30:00", "state": "market"}, entry["monday"])
        spdb = (self.lean / "symbol-properties" / "symbol-properties-database.csv").read_text().splitlines()
        self.assertEqual(spdb.count("krx,[*],equity,,KRW,1,1,1"), 1)


if __name__ == "__main__":
    unittest.main()

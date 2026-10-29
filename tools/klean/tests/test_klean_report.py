import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve()
sys.path[:0] = [str(_HERE.parents[1]), str(_HERE.parents[3])]

from klean import report as rep
from klean.workspace import KleanError, Workspace
from test_klean_p1 import make_run

# Stands in for `dotnet QuantConnect.Report.dll`: checks what LEAN's Report reads from its current
# folder (config.json, template.html, css/, ReportCharts.py) and writes the destination.
FAKE_REPORT = """#!/usr/bin/env python3
import json, os, sys
cfg = json.load(open("config.json"))
missing = [f for f in ("template.html", "ReportCharts.py", "css/report.css") if not os.path.exists(f)]
if missing or len(sys.argv) != 2:
    print("missing", missing, sys.argv); sys.exit(3)
json.load(open(cfg["backtest-data-source-file"]))
open(cfg["report-destination"], "w").write("<html><head></head><body>" + json.dumps(cfg) + "</body></html>")
"""


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        out = root / "Lean" / "Report" / "bin" / "Release"
        (out / "css").mkdir(parents=True)
        for f in ("QuantConnect.Report.dll", "template.html", "ReportCharts.py", "css/report.css"):
            (out / f).write_text("x")
        fake = root / "fake-dotnet"
        fake.write_text(FAKE_REPORT)
        fake.chmod(0o755)
        self.ws = Workspace(root=root / "ws", lean_root=str(root / "Lean"))
        self.run = make_run(self.ws.root / "P", "2026-10-29_10-00-00", 110.0, {"Sharpe Ratio": "0.2"})
        (self.run / "manifest.json").write_text(json.dumps({
            "algorithm": "Algo", "language": "csharp", "parameters": {"holdings": "25"},
            "data_last_date": "20261007", "lean_commit": "80e7843f6456"}))
        self.patches = [mock.patch.object(rep, "dotnet", lambda: str(fake)),
                        mock.patch.object(rep, "ensure_packages", lambda ws, log=None: None),
                        mock.patch.object(rep, "python_env", lambda ws: {})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_description(self):
        self.assertEqual(rep.default_description(self.run),
                         "Algo (csharp); parameters holdings=25; run P/2026-10-29_10-00-00; "
                         "KRX data to 2026-10-07; LEAN 80e7843")

    def test_report_config_and_overwrite(self):
        r = rep.report(self.ws, self.run, strategy_version="v2", log=lambda *a: None)
        page = Path(r["report"])
        self.assertEqual(page, (self.run / "report.html").resolve())
        cfg = json.loads(page.read_text().split("<body>")[1].split("</body>")[0])
        self.assertEqual(cfg["strategy-name"], "P")
        self.assertEqual(cfg["strategy-version"], "v2")
        self.assertIn("holdings=25", cfg["strategy-description"])
        self.assertEqual(cfg["data-folder"], f"{self.ws.data}/")
        self.assertTrue(cfg["backtest-data-source-file"].endswith("Algo.json"))
        with self.assertRaises(KleanError):
            rep.report(self.ws, self.run, log=lambda *a: None)          # exists
        rep.report(self.ws, self.run, overwrite=True, strategy_description="", log=lambda *a: None)
        self.assertIn('"strategy-description": ""', page.read_text())
        with self.assertRaises(KleanError):
            rep.report(self.ws, self.run, destination=Path(self.tmp.name) / "r.pdf", log=lambda *a: None)

    def test_failure_and_pdf_tools(self):
        with mock.patch.object(rep, "dotnet", lambda: "false"):
            with self.assertRaises(KleanError) as e:
                rep.report(self.ws, self.run, log=lambda *a: None)
            self.assertIn("LEAN's Report failed", str(e.exception))
        page = Path(self.tmp.name) / "p.html"
        page.write_text("<html><head></head></html>")
        with mock.patch.object(rep.shutil, "which", lambda name: None):
            with self.assertRaises(KleanError):
                rep.to_pdf(page, page.with_suffix(".pdf"))


if __name__ == "__main__":
    unittest.main()

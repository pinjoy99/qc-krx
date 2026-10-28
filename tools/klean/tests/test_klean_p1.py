import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path[:0] = [str(_HERE.parents[1]), str(_HERE.parents[3])]

from klean import cli, projects, results
from klean.backtest import _value, launcher_args, results_folder, strip_json_comments, write_run_config
from klean.workspace import KleanError, Workspace

LEAN_CONFIG = """{
  // comment with "quotes" and a , comma
  "environment": "backtesting", // trailing comment
  "url": "https://example.com/a//b",  /* block
  comment */
  "maximum-data-points-per-chart-series": 1000,
  "environments": { "backtesting": { "live-mode": false, }, },
}
"""


def make_run(project: Path, name: str, equity_end: float, stats: dict, algo: str = "Algo") -> Path:
    run = project / "backtests" / name
    run.mkdir(parents=True)
    (run / f"{algo}-summary.json").write_text(json.dumps({"statistics": stats}))
    values = [[1700000000, 100.0, 100.0, 100.0, 100.0], [1700086400, 100.0, 101.0, 99.0, equity_end]]
    (run / f"{algo}.json").write_text(json.dumps(
        {"charts": {"Strategy Equity": {"series": {"Equity": {"values": values}}}}}))
    (run / f"{algo}-log.txt").write_text("line 1\nline 2\nline 3\n")
    (run / "console.txt").write_text("console\n")
    return run


class KleanP1Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.lean = base / "Lean"
        (self.lean / "Data" / "market-hours").mkdir(parents=True)
        (self.lean / "Data" / "symbol-properties").mkdir(parents=True)
        (self.lean / "Data" / "market-hours" / "market-hours-database.json").write_text(
            json.dumps({"entries": {"Index-krx-[*]": {"holidays": ["1/1/2026"]}}}))
        (self.lean / "Data" / "symbol-properties" / "symbol-properties-database.csv").write_text("h\n")
        launcher = self.lean / "Launcher" / "bin" / "Release"
        launcher.mkdir(parents=True)
        (launcher / "config.json").write_text(LEAN_CONFIG)
        self.root = base / "ws"
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["init", str(self.root), "--lean", str(self.lean)])
        self.ws = Workspace.load(self.root)
        self.cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def klean(self, *args) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(list(args))
        return code, out.getvalue()

    # ------------------------------------------------------------ LEAN config

    def test_strip_json_comments(self):
        cfg = json.loads(strip_json_comments(LEAN_CONFIG))
        self.assertEqual(cfg["url"], "https://example.com/a//b")   # // inside a string is kept
        self.assertEqual(cfg["maximum-data-points-per-chart-series"], 1000)
        self.assertEqual(cfg["environments"]["backtesting"]["live-mode"], False)

    def test_run_config_merges_extra_keys(self):
        run = self.root / "r"
        run.mkdir()
        path = write_run_config(self.ws, run, {"maximum-data-points-per-chart-series": "4000",
                                               "show-missing-data-logs": "true", "algorithm-id": "MyRun"})
        cfg = json.loads(path.read_text())
        self.assertEqual(cfg["maximum-data-points-per-chart-series"], 4000)
        self.assertIs(cfg["show-missing-data-logs"], True)
        self.assertEqual(cfg["algorithm-id"], "MyRun")
        self.assertEqual(cfg["environment"], "backtesting")
        self.assertEqual(_value('{"a": 1}'), {"a": 1})
        self.assertEqual(_value("text"), "text")

    def test_launcher_args_with_config_and_name(self):
        args = launcher_args(self.ws, "csharp", Path("/p/x.dll"), "A", Path("/r"), {}, Path("/r/config.json"), "my run")
        self.assertEqual(args[2:4], ["--config", "/r/config.json"])
        self.assertEqual(args[args.index("--backtest-name") + 1], "my run")
        self.assertNotIn("--parameters", args)

    def test_results_folder(self):
        p = self.root / "P"
        self.assertRegex(results_folder(p, None, "").name, r"^\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d$")
        self.assertRegex(results_folder(p, None, "first cs/run").name, r"_first-cs-run$")
        out = self.root / "custom"
        self.assertEqual(results_folder(p, out, "x"), out.resolve())
        (out / "f").parent.mkdir()
        (out / "f").write_text("x")
        with self.assertRaises(KleanError):
            results_folder(p, out, "")

    # ------------------------------------------------------------ config

    def test_config_commands(self):
        self.assertEqual(self.klean("config", "set", "maximum-data-points-per-chart-series", "4000")[0], 0)
        code, out = self.klean("config", "get", "maximum-data-points-per-chart-series")
        self.assertEqual(out.strip(), "4000")
        self.assertIn("(LEAN config)", self.klean("config", "list")[1])
        self.assertEqual(Workspace.load(self.root).lean_config, {"maximum-data-points-per-chart-series": "4000"})
        self.assertEqual(self.klean("config", "unset", "maximum-data-points-per-chart-series")[0], 0)
        self.assertEqual(Workspace.load(self.root).lean_config, {})
        self.assertEqual(self.klean("config", "get", "nope")[0], 1)
        self.assertEqual(self.klean("config", "unset", "lean_root")[0], 1)
        self.assertEqual(self.klean("config", "set", "lean_root", str(self.root))[0], 1)   # not a LEAN clone

    # ------------------------------------------------------------ projects

    def test_templates_and_delete(self):
        for t in projects.TEMPLATES:
            for lang in ("python", "csharp"):
                proj = projects.create(self.ws, f"{t}-{lang}", lang, t)
                main = proj / ("main.py" if lang == "python" else "Main.cs")
                self.assertIn("Asia/Seoul", main.read_text())
        self.assertIn("KrxTopMarketCapAlgorithm",
                      projects.python_algorithm_class(self.root / "top-market-cap-python" / "main.py"))
        self.assertEqual(projects.csharp_algorithm_class(self.root / "top-market-cap-csharp"), "KrxTopMarketCapAlgorithm")
        self.assertEqual(projects.csharp_algorithm_class(self.root / "empty-csharp"), "EmptyCsharp")
        with self.assertRaises(KleanError):
            projects.create(self.ws, "x", "python", "nope")
        self.assertEqual(self.klean("project-delete", "empty-python", "--yes")[0], 0)
        self.assertFalse((self.root / "empty-python").exists())
        with self.assertRaises(KleanError):
            projects.delete(self.ws, "data")         # not a project
        with self.assertRaises(KleanError):
            projects.delete(self.ws, "..")           # outside the workspace

    # ------------------------------------------------------------ results

    def test_resolve_compare_and_logs(self):
        stats = {"Total Orders": "1", "End Equity": "110", "Sharpe Ratio": "1.0"}
        a = make_run(self.root / "A", "2026-10-28_10-00-00", 110.0, stats)
        a2 = make_run(self.root / "A", "2026-10-28_11-00-00_second", 110.0, stats)
        b = make_run(self.root / "B", "2026-10-28_10-00-00", 110.0, stats)
        c = make_run(self.root / "C", "2026-10-28_10-00-00", 120.0, {**stats, "End Equity": "120"})
        self.assertEqual(results.resolve_run(self.ws, "A"), a2.resolve())             # latest
        self.assertEqual(results.resolve_run(self.ws, "A/2026-10-28_10"), a.resolve())  # prefix
        self.assertEqual(results.resolve_run(self.ws, "A@2026-10-28_11"), a2.resolve())
        self.assertEqual(results.resolve_run(self.ws, str(b)), b.resolve())             # folder
        with self.assertRaises(KleanError):
            results.resolve_run(self.ws, "A/2026")                                      # ambiguous
        _, rows, verdict = results.compare([a, b])
        self.assertTrue(verdict["identical"])
        self.assertTrue(verdict["equity_curves_identical"])
        _, rows, verdict = results.compare([a, c])
        self.assertFalse(verdict["identical"])
        self.assertEqual(verdict["differing"], ["End Equity"])
        self.assertFalse(verdict["equity_curves_identical"])
        code, out = self.klean("compare", "A", "C")
        self.assertIn("DIFFERENT: End Equity", out)
        code, out = self.klean("logs", "A", "--tail", "1")
        self.assertTrue(out.strip().endswith("line 3"))
        self.assertIn("console", self.klean("logs", "A", "--console")[1])

    # ------------------------------------------------------------ data status

    def test_data_status(self):
        krx = self.ws.data / "equity" / "krx"
        (krx / "daily").mkdir(parents=True)
        for code in ("005930", "000030"):
            (krx / "daily" / f"{code}.zip").write_bytes(b"z")
        (krx / "securities.csv").write_text(
            "code,name,market,krx_first_date,krx_last_date\n"
            "005930,Samsung,KOSPI,20100104,20261007\n000030,Woori,KOSPI,20100104,20190212\n")
        (krx / "universe").mkdir()
        (krx / "universe" / "20261007.zip").write_bytes(b"z")
        idx = self.ws.data / "index" / "krx" / "daily"
        idx.mkdir(parents=True)
        with zipfile.ZipFile(idx / "kospi200.zip", "w") as z:
            z.writestr("kospi200.csv", "20100104 00:00,1,1,1,1,0\n20261007 00:00,2,2,2,2,0\n")
        st = results.data_status(self.ws)
        self.assertEqual(st["securities"], 2)
        self.assertEqual((st["first_date"], st["last_date"]), ("20100104", "20261007"))
        self.assertEqual((st["active"], st["delisted_or_suspended"]), (1, 1))
        self.assertEqual(st["active_by_market"], {"KOSPI": 1})
        self.assertEqual(st["indices"]["kospi200"], {"first": "20100104", "last": "20261007"})
        self.assertEqual(st["market_hours"], {"installed": False, "holidays": 0})
        self.assertEqual(results.last_data_date(self.ws), "20261007")
        self.assertIn("MISSING", self.klean("data", "status")[1])


if __name__ == "__main__":
    unittest.main()

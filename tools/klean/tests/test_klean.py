import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

# Runnable from a clone without installing: tools/klean (klean) and the repo root (qc_krx).
_HERE = Path(__file__).resolve()
sys.path[:0] = [str(_HERE.parents[1]), str(_HERE.parents[3])]

from klean import cli, projects
from klean.backtest import launcher_args
from klean.workspace import KleanError, Workspace


class KleanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        # a minimal LEAN clone: Data/ config files + an (empty) launcher build folder
        self.lean = base / "Lean"
        (self.lean / "Data" / "market-hours").mkdir(parents=True)
        (self.lean / "Data" / "symbol-properties").mkdir(parents=True)
        (self.lean / "Data" / "equity" / "usa").mkdir(parents=True)   # vendor sample data
        (self.lean / "Data" / "market-hours" / "market-hours-database.json").write_text(
            json.dumps({"entries": {"Index-krx-[*]": {"holidays": ["1/1/2026"]}}}))
        (self.lean / "Data" / "symbol-properties" / "symbol-properties-database.csv").write_text(
            "market,symbol,type,description,quote_currency,contract_multiplier,minimum_price_variation,lot_size\n")
        (self.lean / "Launcher" / "bin" / "Release").mkdir(parents=True)
        self.ws_dir = base / "ws"
        self.zip = base / "lean.zip"
        with zipfile.ZipFile(self.zip, "w") as z:   # what `qc_krx lean-package` writes
            z.writestr("data/equity/krx/daily/005930.zip", b"zip")
            z.writestr("data/index/krx/daily/kospi200.zip", b"zip")

    def tearDown(self):
        self.tmp.cleanup()

    def init(self, *extra):
        return cli.main(["init", str(self.ws_dir), "--lean", str(self.lean), "--data-zip", str(self.zip), *extra])

    def test_init_copies_only_lean_config_and_installs_data(self):
        self.assertEqual(self.init(), 0)
        ws = Workspace.load(self.ws_dir / "sub" / "dir")   # found from below, like git
        self.assertEqual(ws.root, self.ws_dir.resolve())
        self.assertEqual(ws.lean_root, str(self.lean.resolve()))
        self.assertTrue((ws.data / "equity" / "krx" / "daily" / "005930.zip").exists())
        self.assertTrue((ws.data / "index" / "krx" / "daily" / "kospi200.zip").exists())
        self.assertFalse((ws.data / "equity" / "usa").exists())   # no vendor sample data by default
        mhdb = json.loads((ws.data / "market-hours" / "market-hours-database.json").read_text())
        self.assertIn("Equity-krx-[*]", mhdb["entries"])
        # LEAN's own files are untouched (copied, not edited in place)
        self.assertNotIn("Equity-krx", (self.lean / "Data" / "market-hours" / "market-hours-database.json").read_text())

    def test_sample_data_option(self):
        self.init("--sample-data")
        self.assertTrue((self.ws_dir / "data" / "equity" / "usa").exists())

    def test_project_create_python_and_csharp(self):
        self.init()
        ws = Workspace.load(self.ws_dir)
        py = projects.create(ws, "My First", "python")
        self.assertEqual(sorted(p.name for p in py.iterdir()), ["krx_models.py", "main.py"])
        self.assertEqual(projects.python_algorithm_class(py / "main.py"), "MyFirst")
        self.assertEqual(projects.language_of(py), "python")
        cs = projects.create(ws, "Top 20", "csharp")
        self.assertEqual(sorted(p.name for p in cs.iterdir()), ["KrxModels.cs", "Main.cs", "Top20.csproj"])
        self.assertEqual(projects.csharp_algorithm_class(cs), "Top20")
        self.assertEqual(projects.language_of(cs), "csharp")
        csproj = (cs / "Top20.csproj").read_text()
        self.assertIn(str(ws.launcher_dir), csproj)
        self.assertIn('Exclude="$(LeanBin)/QuantConnect.Algorithm.CSharp.dll"', csproj)
        with self.assertRaises(KleanError):
            projects.create(ws, "Top 20", "csharp")   # exists

    def test_class_names(self):
        self.assertEqual(projects.class_name("krx top-20 v2"), "KrxTop20V2")
        self.assertEqual(projects.class_name("2024 test"), "Krx2024Test")

    def test_launcher_args(self):
        self.init()
        ws = Workspace.load(self.ws_dir)
        args = launcher_args(ws, "python", Path("/p/main.py"), "MyAlgo", Path("/p/backtests/x"), {"weight": "0.5"})
        self.assertEqual(args[1:], ["QuantConnect.Lean.Launcher.dll", "--algorithm-type-name", "MyAlgo",
                                    "--algorithm-language", "Python", "--algorithm-location", "/p/main.py",
                                    "--data-folder", f"{ws.data}/", "--results-destination-folder", "/p/backtests/x",
                                    "--close-automatically", "true", "--parameters", "weight:0.5"])
        with self.assertRaises(KleanError):
            launcher_args(ws, "python", Path("/p/main.py"), "A", Path("/r"), {"bad": "a:b"})

    def test_backtest_needs_a_lean_build(self):
        self.init()
        ws = Workspace.load(self.ws_dir)
        projects.create(ws, "P", "python")
        with self.assertRaisesRegex(KleanError, "no LEAN build"):
            from klean.backtest import backtest
            backtest(ws, self.ws_dir / "P")
        self.assertEqual(cli.main(["backtest", str(self.ws_dir / "P")]), 1)


if __name__ == "__main__":
    unittest.main()

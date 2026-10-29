import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path[:0] = [str(_HERE.parents[1]), str(_HERE.parents[3])]

from klean import optimize, results
from klean.workspace import KleanError
from test_klean_p1 import make_run


class OptimizeTest(unittest.TestCase):
    def test_parameter_values_and_grid(self):
        self.assertEqual(optimize.parameter_values("h", "5", "30", "5"), ["5", "10", "15", "20", "25", "30"])
        self.assertEqual(optimize.parameter_values("w", "0.1", "0.3", "0.1"), ["0.1", "0.2", "0.3"])  # no float drift
        self.assertEqual(optimize.parameter_values("w", "1", "2", "0.75"), ["1", "1.75"])
        with self.assertRaises(KleanError):
            optimize.parameter_values("x", "3", "1", "1")
        with self.assertRaises(KleanError):
            optimize.parameter_values("x", "a", "1", "1")
        g = optimize.grid([("a", "1", "2", "1"), ("b", "10", "20", "10")])
        self.assertEqual(g, [{"a": "1", "b": "10"}, {"a": "1", "b": "20"}, {"a": "2", "b": "10"}, {"a": "2", "b": "20"}])
        with self.assertRaises(KleanError):
            optimize.grid([("a", "1", "2", "1"), ("a", "1", "2", "1")])

    def test_constraints_and_numbers(self):
        self.assertEqual(optimize.parse_constraint("Drawdown < 25"), ("Drawdown", "<", 25.0))
        self.assertEqual(optimize.parse_constraint("Sharpe Ratio >= 0.5"), ("Sharpe Ratio", ">=", 0.5))
        self.assertEqual(optimize.parse_constraint("Drawdown<=25%"), ("Drawdown", "<=", 25.0))
        with self.assertRaises(KleanError):
            optimize.parse_constraint("Drawdown small")
        self.assertEqual(optimize.number("22.398%"), 22.398)
        self.assertEqual(optimize.number("₩13395456.00"), 13395456.0)
        self.assertEqual(optimize.number("-0.012"), -0.012)
        self.assertIsNone(optimize.number(""))
        self.assertEqual(optimize.run_folder_name(5, {"holdings": "25", "w": "0.5"}), "005_holdings=25_w=0.5")

    def test_evaluate_best_and_ranking(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d) / "P"
            runs = []
            for i, (h, sharpe, dd) in enumerate([("5", "0.266", "50.2%"), ("20", "0.188", "31.2%"), ("25", "0.201", "30.4%")], 1):
                run = make_run(proj, f"r{i}", 1.0, {"Sharpe Ratio": sharpe, "Drawdown": dd, "End Equity": "1"})
                e = optimize.evaluate(run, "Sharpe Ratio", [optimize.parse_constraint("Drawdown < 35")])
                runs.append({"index": i, "folder": run.name, "parameters": {"holdings": h}, **e})
            (proj / "backtests" / "broken").mkdir()
            runs.append({"index": 4, "folder": "broken", "parameters": {"holdings": "30"},
                         **optimize.evaluate(proj / "backtests" / "broken", "Sharpe Ratio", [])})
            self.assertFalse(runs[0]["passes"])
            self.assertEqual(runs[0]["failed_constraints"], ["Drawdown < 35"])
            self.assertFalse(runs[3]["ok"])
            best = optimize.best_run(runs, "max")
            self.assertEqual(best["parameters"], {"holdings": "25"})
            self.assertEqual(optimize.best_run(runs, "min")["parameters"], {"holdings": "20"})
            summary = {"direction": "max", "target": "Sharpe Ratio", "parameters": [{"name": "holdings"}],
                       "runs": runs, "best": best["folder"]}
            header, rows = optimize.ranking(summary)
            self.assertEqual(header[:3], ["", "holdings", "Sharpe Ratio"])
            self.assertEqual([r[1] for r in rows], ["25", "20", "5", "30"])   # passing, failing, broken
            self.assertEqual(rows[0][0], "★")
            self.assertEqual(rows[2][-1], "fails: Drawdown < 35")
            self.assertEqual(rows[3][-1], "failed run")

    def test_estimate_and_limits(self):
        self.assertEqual(optimize.optimize(None, Path("."), [("h", "1", "10", "1")], estimate=True,
                                           max_concurrent=3), {"backtests": 10, "concurrent": 3})
        with self.assertRaises(KleanError):
            optimize.optimize(None, Path("."), [("h", "1", "1000", "1")], max_backtests=500)
        with self.assertRaises(KleanError):
            optimize.optimize(None, Path("."), [])
        self.assertEqual(results.label(Path("/w/P/optimizations/opt1/001_h=5")), "P/opt1/001_h=5")


if __name__ == "__main__":
    unittest.main()

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path[:0] = [str(_HERE.parents[1]), str(_HERE.parents[3])]

from klean import gui, projects
from klean.workspace import Workspace
from test_klean_p1 import make_run


class GuiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        lean = base / "Lean"
        (lean / "Launcher" / "bin" / "Release").mkdir(parents=True)
        (lean / "Data" / "market-hours").mkdir(parents=True)
        self.root = base / "ws"
        (self.root / "data").mkdir(parents=True)
        self.ws = Workspace(root=self.root, lean_root=str(lean))
        self.ws.save()
        projects.create(self.ws, "A", "python")
        stats = {"Total Orders": "1", "End Equity": "110", "Compounding Annual Return": "5%"}
        make_run(self.root / "A", "2026-10-28_10-00-00", 110.0, stats)
        make_run(self.root / "A", "2026-10-28_11-00-00", 110.0, stats)
        self.outside = make_run(base / "other", "2026-10-28_10-00-00", 1.0, stats)
        self.token = "t0ken"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), gui.make_handler(self.ws, self.token, gui.Jobs()))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def get(self, path, token=True, data=None, header=True):
        req = urllib.request.Request(self.base + path, data=data)
        if token and header:
            req.add_header("X-Klean-Token", self.token)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_token_required(self):
        self.assertEqual(self.get("/", token=False)[0], 403)
        self.assertEqual(self.get("/api/workspace?token=wrong", token=False)[0], 403)
        status, body = self.get(f"/?token={self.token}", token=False)
        self.assertEqual(status, 200)
        self.assertIn(b"<title>klean</title>", body)
        # POST needs the header (a cross-site form can't set it), the query token isn't enough
        self.assertEqual(self.get(f"/api/backtest?token={self.token}", header=False, data=b"{}")[0], 403)

    def test_api(self):
        w = json.loads(self.get("/api/workspace")[1])
        self.assertEqual([(p["name"], p["runs"]) for p in w["projects"]], [("A", 2)])
        p = json.loads(self.get("/api/project?name=A")[1])
        self.assertEqual([r["name"] for r in p["runs"]], ["2026-10-28_11-00-00", "2026-10-28_10-00-00"])
        r = json.loads(self.get("/api/run?ref=A")[1])
        self.assertEqual(r["ref"], "A/backtests/2026-10-28_11-00-00")
        self.assertEqual(r["equity"][-1], [1700086400, 110.0])
        c = json.loads(self.get("/api/compare?ref=A/2026-10-28_10&ref=A/2026-10-28_11")[1])
        self.assertTrue(c["verdict"]["identical"])
        self.assertEqual(json.loads(self.get("/api/log?ref=A&tail=1")[1])["lines"], ["line 3"])

    def test_outside_workspace_refused(self):
        status, body = self.get("/api/run?ref=" + urllib.request.quote(str(self.outside)))
        self.assertEqual(status, 400)
        self.assertIn(b"outside the workspace", body)
        status, _ = self.get("/api/backtest", data=json.dumps({"project": "../other"}).encode())
        self.assertEqual(status, 400)

    def test_optimization_api(self):
        opt = self.root / "A" / "optimizations" / "o1"
        stats = {"Sharpe Ratio": "0.2", "End Equity": "110", "Drawdown": "10%"}
        opt.mkdir(parents=True)
        for i, (h, sh) in enumerate([("5", "0.1"), ("10", "0.3")], 1):
            run = opt / f"{i:03d}_h={h}"
            run.mkdir()
            (run / "Algo-summary.json").write_text(json.dumps({"statistics": {**stats, "Sharpe Ratio": sh}}))
        runs = [{"index": i, "folder": f"{i:03d}_h={h}", "parameters": {"h": h}, "ok": True, "passes": True,
                 "target_value": float(sh), "failed_constraints": [], "stats": {"Sharpe Ratio": sh}}
                for i, (h, sh) in enumerate([("5", "0.1"), ("10", "0.3")], 1)]
        (opt / "optimization.json").write_text(json.dumps({
            "project": "A", "algorithm": "A", "language": "python", "strategy": "grid", "target": "Sharpe Ratio",
            "direction": "max", "constraints": [], "parameters": [{"name": "h", "min": "5", "max": "10", "step": "5"}],
            "lean_config": {}, "started_utc": "", "seconds": 1, "concurrent": 2, "runs": runs, "best": "002_h=10"}))
        p = json.loads(self.get("/api/project?name=A")[1])
        self.assertEqual(p["optimizations"][0]["best"]["parameters"], {"h": "10"})
        self.assertNotIn("optimizations/o1/optimization.json", p["files"])
        o = json.loads(self.get("/api/optimization?project=A&name=o1")[1])
        self.assertEqual(o["row_refs"], ["A/optimizations/o1/002_h=10", "A/optimizations/o1/001_h=5"])
        r = json.loads(self.get("/api/run?ref=" + urllib.request.quote("A/optimizations/o1/002_h=10"))[1])
        self.assertEqual(r["statistics"]["Sharpe Ratio"], "0.3")
        self.assertEqual(self.get("/api/optimization?project=A&name=..")[0], 400)

    def test_downsample(self):
        pts = [[i, i] for i in range(10000)]
        out = gui.downsample(pts, 100)
        self.assertEqual(len(out), 100)
        self.assertEqual(out[0], [0, 0])
        self.assertEqual(out[-1], [9999, 9999])


if __name__ == "__main__":
    unittest.main()

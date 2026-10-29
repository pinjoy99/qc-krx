import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path[:0] = [str(_HERE.parents[1]), str(_HERE.parents[3])]

from klean import results


class CodeSnapshotTest(unittest.TestCase):
    def test_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d) / "P"
            files = {"main.py": "x", "research.ipynb": "{}", "krx_models.py": "y", "lib/util.py": "z",
                     "data.csv": "1,2", ".gitignore": "*.pyc",
                     "backtests/r1/main.py": "old", "optimizations/o/code/main.py": "old", "bin/Release/P.dll": "b",
                     "obj/x": "o", "__pycache__/main.cpython-311.pyc": "c", ".ipynb_checkpoints/research.ipynb": "c",
                     ".vscode/settings.json": "{}", "lib/__pycache__/util.pyc": "c"}
            for f, text in files.items():
                (proj / f).parent.mkdir(parents=True, exist_ok=True)
                (proj / f).write_text(text)
            (proj / "big.bin").write_bytes(b"0" * (results.MAX_SNAPSHOT_BYTES + 1))
            names = [p.relative_to(proj).as_posix() for p in results.source_files(proj)]
            self.assertEqual(names, [".gitignore", "big.bin", "data.csv", "krx_models.py", "lib/util.py", "main.py",
                                     "research.ipynb"])
            self.assertEqual(sorted(results.project_files(proj)), names)
            dest = proj / "backtests" / "r2" / "code"
            self.assertEqual(results.snapshot_code(proj, dest), ["big.bin"])
            self.assertEqual((dest / "lib" / "util.py").read_text(), "z")
            self.assertEqual((dest / "research.ipynb").read_text(), "{}")
            self.assertFalse((dest / "big.bin").exists())
            # the snapshot itself (inside backtests/) isn't picked up by the next run
            self.assertNotIn("backtests/r2/code/main.py", results.project_files(proj))


if __name__ == "__main__":
    unittest.main()

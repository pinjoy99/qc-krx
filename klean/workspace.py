"""Workspace configuration (klean.json) and the environment klean needs: a LEAN source build,
the .NET SDK, and a CPython 3.11 environment for Python algorithms."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_NAME = "klean.json"
# The LEAN commit qc-krx was tested with (see docs/AUDIT.md).
LEAN_COMMIT = "80e7843f645673bcbeaab963049f76f20f6785e1"
LEAN_REPO = "https://github.com/QuantConnect/Lean.git"
# LEAN's Python requirements at that commit (DockerfileLeanFoundation); enough for the KRX models.
PYTHON_PACKAGES = ["pandas==2.3.3", "numpy==1.26.4"]
# LEAN's own config files a KRX workspace needs (no vendor sample data).
LEAN_CONFIG_DIRS = ["market-hours", "symbol-properties"]
LEAN_OPTIONAL_FILES = ["alternative/interest-rate/usa/interest-rate.csv"]
# qc-krx repository root (klean is run from a clone: `pip install -e .` or `python -m klean`).
REPO_ROOT = Path(__file__).resolve().parents[1]


class KleanError(Exception):
    pass


@dataclass
class Workspace:
    root: Path
    lean_root: str
    python_venv: str = ""
    python_dll: str = ""

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def launcher_dir(self) -> Path:
        return Path(self.lean_root) / "Launcher" / "bin" / "Release"

    def save(self) -> None:
        d = asdict(self)
        d.pop("root")
        (self.root / CONFIG_NAME).write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, start: Path) -> "Workspace":
        """The workspace containing ``start`` (searching parent folders like git does)."""
        start = start.resolve()
        for d in (start, *start.parents):
            if (d / CONFIG_NAME).exists():
                cfg = json.loads((d / CONFIG_NAME).read_text(encoding="utf-8"))
                return cls(root=d, **{k: cfg.get(k, "") for k in ("lean_root", "python_venv", "python_dll")})
        raise KleanError(f"no {CONFIG_NAME} in {start} or its parents: run `klean init` first")


def dotnet() -> str:
    found = shutil.which("dotnet") or str(Path.home() / ".dotnet" / "dotnet")
    if not Path(found).exists():
        raise KleanError("dotnet not found. Install the .NET 10 SDK: "
                         "curl -sSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel 10.0 "
                         "(then add ~/.dotnet to PATH)")
    return found


def venv_python(venv: str) -> Path:
    return Path(venv) / "bin" / "python"


def site_packages(venv: str) -> str:
    out = subprocess.run([str(venv_python(venv)), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def find_python_dll(python: str) -> str:
    """Path of the shared libpython of ``python`` (what pythonnet loads)."""
    code = ("import sysconfig; print(sysconfig.get_config_var('LIBDIR') or ''); "
            "print(sysconfig.get_config_var('LDLIBRARY') or '')")
    libdir, ldlib = (subprocess.run([python, "-c", code], capture_output=True, text=True, check=True)
                     .stdout.strip().splitlines() + ["", ""])[:2]
    names = [ldlib, ldlib.replace(".a", ".so"), "libpython3.11.so", "libpython3.11.so.1.0", "libpython3.11.dylib"]
    for name in names:
        if name and (Path(libdir) / name).exists() and not name.endswith(".a"):
            return str(Path(libdir) / name)
    raise KleanError(f"no shared libpython3.11 next to {python} (looked in {libdir}); "
                     "install a CPython 3.11 built with --enable-shared, e.g. the libpython3.11 package")


def check(ws: Workspace | None) -> list[tuple[str, bool, str]]:
    """(item, ok, detail) for `klean doctor`."""
    rows = []
    try:
        d = dotnet()
        v = subprocess.run([d, "--list-sdks"], capture_output=True, text=True).stdout.strip().splitlines()
        rows.append(("dotnet SDK", any(s.startswith("10.") for s in v), ", ".join(s.split()[0] for s in v) or "none"))
    except KleanError as e:
        rows.append(("dotnet SDK", False, str(e)))
    if ws is None:
        rows.append(("workspace", False, f"no {CONFIG_NAME} (run `klean init`)"))
        return rows
    rows.append(("workspace", True, str(ws.root)))
    launcher = ws.launcher_dir / "QuantConnect.Lean.Launcher.dll"
    rows.append(("LEAN build", launcher.exists(), str(launcher)))
    for name in LEAN_CONFIG_DIRS:
        rows.append((f"data/{name}", (ws.data / name).is_dir(), str(ws.data / name)))
    mhdb = ws.data / "market-hours" / "market-hours-database.json"
    has_krx = mhdb.exists() and "Equity-krx-[*]" in mhdb.read_text(encoding="utf-8")
    rows.append(("Equity-krx market hours", has_krx, "present" if has_krx else "run `klean data install`"))
    n = len(list((ws.data / "equity" / "krx" / "daily").glob("*.zip")))
    rows.append(("KRX daily data", n > 0, f"{n} securities"))
    if ws.python_venv:
        py = venv_python(ws.python_venv)
        ok = py.exists() and subprocess.run([str(py), "-c", "import sys, pandas, numpy; "
                                             "assert sys.version_info[:2] == (3, 11)"]).returncode == 0
        rows.append(("Python 3.11 env (pandas, numpy)", ok, ws.python_venv))
        rows.append(("libpython3.11", bool(ws.python_dll) and Path(ws.python_dll).exists(), ws.python_dll or "not set"))
    else:
        rows.append(("Python env", False, "not set (only needed for Python projects; `klean install-python`)"))
    return rows


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> None:
    print("$", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=cwd, env={**os.environ, **(env or {})})
    if r.returncode:
        raise KleanError(f"command failed ({r.returncode}): {' '.join(cmd)}")

"""`klean backtest`: what `lean backtest` does inside its Docker container, on a LEAN source build.

1. Python: byte-compile the project (syntax check) and install its requirements.txt into the
   Python 3.11 environment. C#: `dotnet build` the project against the LEAN build's DLLs.
2. Run LEAN's launcher with the workspace's data folder and a new results folder
   ``<project>/backtests/<yyyy-MM-dd_HH-mm-ss>/``.
3. Print the main statistics from ``<Algorithm>-summary.json``.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path

from klean import projects
from klean.workspace import KleanError, Workspace, dotnet, run, site_packages, venv_python

SUMMARY_KEYS = ("Total Orders", "Compounding Annual Return", "Drawdown", "Sharpe Ratio", "Net Profit",
                "Alpha", "Beta", "Total Fees", "End Equity")


def launcher_args(ws: Workspace, language: str, location: Path, cls: str, results: Path,
                  parameters: dict[str, str]) -> list[str]:
    args = [dotnet(), "QuantConnect.Lean.Launcher.dll",
            "--algorithm-type-name", cls,
            "--algorithm-language", "Python" if language == "python" else "CSharp",
            "--algorithm-location", str(location),
            "--data-folder", f"{ws.data}/",
            "--results-destination-folder", str(results),
            "--close-automatically", "true"]
    if parameters:
        bad = [k for k, v in parameters.items() if any(c in k + v for c in ",:")]
        if bad:
            raise KleanError(f"parameter names/values can't contain ',' or ':' ({', '.join(bad)})")
        args += ["--parameters", ",".join(f"{k}:{v}" for k, v in parameters.items())]
    return args


def python_env(ws: Workspace) -> dict[str, str]:
    if not ws.python_venv or not ws.python_dll:
        raise KleanError("no Python environment in klean.json: run `klean install-python` "
                         "(or `klean init --python-venv ...`)")
    return {"PYTHONNET_PYDLL": ws.python_dll, "PYTHONPATH": site_packages(ws.python_venv)}


def prepare(ws: Workspace, project: Path, language: str) -> tuple[Path, str, dict[str, str]]:
    """Compile/check the project; return (algorithm location, class name, extra environment)."""
    if language == "python":
        env = python_env(ws)
        py = str(venv_python(ws.python_venv))
        files = [str(p) for p in project.rglob("*.py") if "backtests" not in p.parts]
        run([py, "-m", "py_compile", *files])
        if (project / "requirements.txt").exists():
            run([py, "-m", "pip", "install", "-q", "-r", str(project / "requirements.txt")])
        return project / "main.py", projects.python_algorithm_class(project / "main.py"), env
    csproj = sorted(project.glob("*.csproj"))[0]
    run([dotnet(), "build", str(csproj), "-c", "Release", "-nologo", "-v", "q",
         f"-p:LeanBin={ws.launcher_dir}", "-o", str(project / "bin" / "Release")])
    return project / "bin" / "Release" / f"{csproj.stem}.dll", projects.csharp_algorithm_class(project), {}


def backtest(ws: Workspace, project: Path, parameters: dict[str, str] | None = None) -> dict:
    project = project.resolve()
    if not project.is_dir():
        raise KleanError(f"{project} is not a project folder")
    if not (ws.launcher_dir / "QuantConnect.Lean.Launcher.dll").exists():
        raise KleanError(f"no LEAN build in {ws.launcher_dir}: run `klean install-lean`")
    language = projects.language_of(project)
    location, cls, env = prepare(ws, project, language)
    results = project / "backtests" / dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    results.mkdir(parents=True)
    args = launcher_args(ws, language, location, cls, results, parameters or {})
    print(f"klean: backtesting {cls} ({language}) -> {results}", flush=True)
    with open(results / "console.txt", "w", encoding="utf-8") as log:
        proc = subprocess.run(args, cwd=ws.launcher_dir, env={**os.environ, **env},
                              stdout=log, stderr=subprocess.STDOUT)
    summary = results / f"{cls}-summary.json"
    if not summary.exists():
        tail = (results / "console.txt").read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
        raise KleanError(f"backtest failed (exit {proc.returncode}), no {summary.name}. "
                         f"Last lines of {results / 'console.txt'}:\n" + "\n".join(tail))
    # Python runs can abort at exit after writing results (pythonnet GIL shutdown); the summary is
    # what counts, so a non-zero exit code with a summary is a success.
    stats = json.loads(summary.read_text(encoding="utf-8")).get("statistics", {})
    return {"results": str(results), "exit_code": proc.returncode,
            "statistics": {k: stats[k] for k in SUMMARY_KEYS if k in stats}}

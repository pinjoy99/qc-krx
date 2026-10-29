"""`klean backtest`: what `lean backtest` does inside its Docker container, on a LEAN source build.

1. Python: byte-compile the project (syntax check) and install its requirements.txt into the
   Python 3.11 environment. C#: `dotnet build` the project against the LEAN build's DLLs.
2. Write the run's LEAN config (LEAN's Launcher/config.json + the workspace's and the run's extra
   keys) into the results folder, and run LEAN's launcher with it, the workspace's data folder and
   the results folder (default ``<project>/backtests/<yyyy-MM-dd_HH-mm-ss>[_<name>]/``).
3. Copy the project's source files into ``<results>/code/`` (like the LEAN CLI), write
   ``manifest.json`` (what was run, with which code, engine and data) and print the main
   statistics from ``<Algorithm>-summary.json``.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import platform
import re
import subprocess
from pathlib import Path

from klean import __version__, projects, results
from klean.workspace import (REPO_ROOT, KleanError, Workspace, dotnet, git_commit, run, site_packages,
                             venv_python)

SUMMARY_KEYS = results.MAIN_KEYS


def strip_json_comments(text: str) -> str:
    """LEAN's config.json has // and /* */ comments and trailing commas (Json.NET accepts them)."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def write_run_config(ws: Workspace, results_dir: Path, extra: dict[str, str]) -> Path:
    """LEAN's launcher config with ``extra`` keys on top, as ``<results>/config.json``."""
    base = ws.launcher_dir / "config.json"
    if not base.exists():
        raise KleanError(f"{base} not found: is lean_root a built LEAN clone?")
    cfg = json.loads(strip_json_comments(base.read_text(encoding="utf-8")))
    cfg["parameters"] = {}   # LEAN's sample values (ema-fast, intrinio-…); only --parameter values reach the algorithm
    for k, v in extra.items():
        cfg[k] = _value(v)
    path = results_dir / "config.json"
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return path


def _value(v):
    """'true' -> True, '12' -> 12, '1.5' -> 1.5, JSON objects/lists parsed, else the string."""
    if not isinstance(v, str):
        return v
    try:
        return json.loads(v)
    except ValueError:
        return v


def launcher_args(ws: Workspace, language: str, location: Path, cls: str, results_dir: Path,
                  parameters: dict[str, str], config: Path | None = None, backtest_name: str = "") -> list[str]:
    args = [dotnet(), "QuantConnect.Lean.Launcher.dll"]
    if config:
        args += ["--config", str(config)]
    args += ["--algorithm-type-name", cls,
             "--algorithm-language", "Python" if language == "python" else "CSharp",
             "--algorithm-location", str(location),
             "--data-folder", f"{ws.data}/",
             "--results-destination-folder", str(results_dir),
             "--close-automatically", "true"]
    if backtest_name:
        args += ["--backtest-name", backtest_name]
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


def prepare(ws: Workspace, project: Path, language: str, build_config: str = "Release"
            ) -> tuple[Path, str, dict[str, str]]:
    """Compile/check the project; return (algorithm location, class name, extra environment)."""
    if language == "python":
        env = python_env(ws)
        py = str(venv_python(ws.python_venv))
        files = [str(p) for p in project.rglob("*.py")
                 if p.relative_to(project).parts[0] not in results.OUTPUT_DIRS]
        run([py, "-m", "py_compile", *files])
        if (project / "requirements.txt").exists():
            run([py, "-m", "pip", "install", "-q", "-r", str(project / "requirements.txt")])
        return project / "main.py", projects.python_algorithm_class(project / "main.py"), env
    csproj = sorted(project.glob("*.csproj"))[0]
    out = project / "bin" / build_config
    run([dotnet(), "build", str(csproj), "-c", build_config, "-nologo", "-v", "q",
         f"-p:LeanBin={ws.launcher_dir}", "-o", str(out)])
    return out / f"{csproj.stem}.dll", projects.csharp_algorithm_class(project), {}


def results_folder(project: Path, output: Path | None, name: str) -> Path:
    if output:
        out = output.expanduser().resolve()
        if out.exists() and any(out.iterdir()):
            raise KleanError(f"{out} already exists and isn't empty")
        return out
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") if name else ""
    return project / "backtests" / (f"{stamp}_{safe}" if safe else stamp)


def check_project(ws: Workspace, project: Path) -> tuple[Path, str]:
    project = project.resolve()
    if not project.is_dir():
        raise KleanError(f"{project} is not a project folder")
    if not (ws.launcher_dir / "QuantConnect.Lean.Launcher.dll").exists():
        raise KleanError(f"no LEAN build in {ws.launcher_dir}: run `klean install-lean`")
    return project, projects.language_of(project)


def run_once(ws: Workspace, project: Path, language: str, location: Path, cls: str, env: dict[str, str],
             results_dir: Path, parameters: dict[str, str], lean_config: dict[str, str],
             backtest_name: str = "", build_config: str = "Release", quiet: bool = False,
             code: str = "code/") -> dict:
    """One LEAN run of an already prepared project into ``results_dir`` (with code/, config.json,
    console.txt and manifest.json). ``code`` is where the code snapshot is, relative to the run;
    the default "code/" makes one in the run folder (optimizations share one). Returns {results, exit_code, ok}."""
    results_dir.mkdir(parents=True, exist_ok=True)
    skipped = results.snapshot_code(project, results_dir / "code") if code == "code/" else []
    config = write_run_config(ws, results_dir, lean_config)
    args = launcher_args(ws, language, location, cls, results_dir, parameters, config, backtest_name)
    if not quiet:
        print(f"klean: backtesting {cls} ({language}) -> {results_dir}", flush=True)
    started = dt.datetime.now(dt.timezone.utc)
    with open(results_dir / "console.txt", "w", encoding="utf-8") as log:
        proc = subprocess.run(args, cwd=ws.launcher_dir, env={**os.environ, **env},
                              stdout=log, stderr=subprocess.STDOUT)
    finished = dt.datetime.now(dt.timezone.utc)
    ok = results.summary_file(results_dir, required=False) is not None
    write_manifest(ws, project, results_dir, language=language, algorithm=cls, parameters=parameters,
                   lean_config=lean_config, backtest_name=backtest_name, build_config=build_config,
                   started=started, finished=finished, exit_code=proc.returncode, ok=ok, code=code,
                   **({"code_skipped_large_files": skipped} if skipped else {}))
    # Python runs can abort at exit after writing results (pythonnet GIL shutdown); the summary is
    # what counts, so a non-zero exit code with a summary is a success.
    return {"results": str(results_dir), "exit_code": proc.returncode, "ok": ok}


def backtest(ws: Workspace, project: Path, parameters: dict[str, str] | None = None, *,
             extra_config: dict[str, str] | None = None, output: Path | None = None,
             backtest_name: str = "", build_config: str = "Release") -> dict:
    project, language = check_project(ws, project)
    location, cls, env = prepare(ws, project, language, build_config)
    results_dir = results_folder(project, output, backtest_name)
    r = run_once(ws, project, language, location, cls, env, results_dir, parameters or {},
                 {**ws.lean_config, **(extra_config or {})}, backtest_name, build_config)
    if not r["ok"]:
        tail = (results_dir / "console.txt").read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
        raise KleanError(f"backtest failed (exit {r['exit_code']}), no *-summary.json. "
                         f"Last lines of {results_dir / 'console.txt'}:\n" + "\n".join(tail))
    stats = results.statistics(results_dir)
    return {"results": str(results_dir), "exit_code": r["exit_code"],
            "statistics": {k: stats[k] for k in SUMMARY_KEYS if k in stats}}


def write_manifest(ws: Workspace, project: Path, results_dir: Path, **run_info) -> None:
    """manifest.json: enough to say what produced the results (docs/EXPERT.md §8)."""
    started, finished = run_info.pop("started"), run_info.pop("finished")
    manifest = {
        "klean": __version__,
        "project": project.name,
        **run_info,
        "started_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seconds": round((finished - started).total_seconds(), 1),
        "qc_krx_commit": git_commit(REPO_ROOT),
        "lean_commit": git_commit(Path(ws.lean_root)),
        "data_last_date": results.last_data_date(ws),
        "python": ws.python_venv if run_info.get("language") == "python" else "",
        "host": platform.platform(),
        "files": results.project_files(project),
    }
    (results_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

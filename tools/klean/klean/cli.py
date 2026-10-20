"""klean: `klean <command>` (or `python -m klean <command>`).

    klean install-lean  [--dir ~/Lean]                  clone LEAN (tested commit) and build it
    klean install-python [--dir ~/.klean/py311]         Python 3.11 env with pandas/numpy for LEAN
    klean init [DIR] --lean ~/Lean [--python-venv ...]  workspace: klean.json + data/ (LEAN config files)
    klean data install lean.zip | --root DATA_ROOT      KRX data into data/ + KRX market config
    klean project-create NAME --language python|csharp  project with the KRX models next to it
    klean backtest NAME [--parameter KEY VALUE ...]     run; results in NAME/backtests/<timestamp>/
    klean doctor                                        check the setup
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

from klean import __version__, projects
from klean.backtest import backtest
from klean.workspace import (LEAN_COMMIT, LEAN_CONFIG_DIRS, LEAN_OPTIONAL_FILES, LEAN_REPO, PYTHON_PACKAGES,
                             KleanError, REPO_ROOT, Workspace, check, dotnet, find_python_dll, run, venv_python)


def cmd_install_lean(args) -> None:
    target = Path(args.dir).expanduser().resolve()
    if not (target / ".git").exists():
        target.mkdir(parents=True, exist_ok=True)
        run(["git", "init", "-q", str(target)])
        run(["git", "-C", str(target), "remote", "add", "origin", LEAN_REPO])
    run(["git", "-C", str(target), "fetch", "-q", "--depth", "1", "origin", args.commit])
    run(["git", "-C", str(target), "checkout", "-q", "FETCH_HEAD"])
    run([dotnet(), "build", str(target / "Launcher" / "QuantConnect.Lean.Launcher.csproj"), "-c", "Release",
         "-nologo", "-v", "q"])
    print(f"LEAN {args.commit[:7]} built in {target}. Next: klean init --lean {target}")


def cmd_install_python(args) -> None:
    target = Path(args.dir).expanduser().resolve()
    run([args.python, "-m", "venv", str(target)])
    py = str(venv_python(str(target)))
    run([py, "-m", "pip", "install", "-q", "--upgrade", "pip"])
    run([py, "-m", "pip", "install", "-q", *PYTHON_PACKAGES, *args.package])
    dll = find_python_dll(py)
    print(f"Python env: {target}\nlibpython: {dll}")
    try:
        ws = Workspace.load(Path.cwd())
        ws.python_venv, ws.python_dll = str(target), dll
        ws.save()
        print(f"saved in {ws.root / 'klean.json'}")
    except KleanError:
        print(f"Use it with: klean init --lean <LEAN> --python-venv {target}")


def cmd_init(args) -> None:
    root = Path(args.dir).expanduser().resolve()
    lean = Path(args.lean).expanduser().resolve()
    if not (lean / "Data" / "market-hours").is_dir():
        raise KleanError(f"{lean} doesn't look like a LEAN clone (no Data/market-hours)")
    root.mkdir(parents=True, exist_ok=True)
    ws = Workspace(root=root, lean_root=str(lean))
    if args.python_venv:
        ws.python_venv = str(Path(args.python_venv).expanduser().resolve())
        ws.python_dll = find_python_dll(str(venv_python(ws.python_venv)))
    ws.data.mkdir(exist_ok=True)
    if args.sample_data:
        # LEAN's sample market data (third-party vendors' prices; keep it local, don't redistribute)
        shutil.copytree(lean / "Data", ws.data, dirs_exist_ok=True)
    else:
        for name in LEAN_CONFIG_DIRS:
            shutil.copytree(lean / "Data" / name, ws.data / name, dirs_exist_ok=True)
        for rel in LEAN_OPTIONAL_FILES:
            if (lean / "Data" / rel).exists():
                (ws.data / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(lean / "Data" / rel, ws.data / rel)
    ws.save()
    print(f"workspace {root}: klean.json, data/ ({'LEAN Data incl. sample data' if args.sample_data else 'LEAN config files'})")
    if args.data_zip:
        install_data(ws, zip_path=Path(args.data_zip))
    else:
        print("Next: klean data install lean.zip")


def install_data(ws: Workspace, zip_path: Path | None = None, root: Path | None = None) -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))   # qc_krx from the clone; it needn't be installed
    from qc_krx import lean_install
    if zip_path:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            # lean-package writes data/equity/krx/...; also accept a zip without the data/ prefix
            target = ws.root if any(n.startswith("data/") for n in names) else ws.data
            z.extractall(target)
        print(f"unzipped {len(names)} files from {zip_path} into {ws.data}")
        lean_install.install(ws.root, ws.data, config_only=True)
    else:
        lean_install.install(root, ws.data)


def cmd_data_install(args) -> None:
    ws = Workspace.load(Path.cwd())
    if bool(args.zip) == bool(args.root):
        raise KleanError("give either a lean.zip or --root <qc-krx data root>")
    install_data(ws, zip_path=Path(args.zip) if args.zip else None,
                 root=Path(args.root).expanduser() if args.root else None)


def cmd_project_create(args) -> None:
    ws = Workspace.load(Path.cwd())
    project = projects.create(ws, args.name, args.language)
    print(f"created {project} ({args.language}). Run: klean backtest \"{args.name}\"")


def cmd_backtest(args) -> int:
    project = Path(args.project).expanduser()
    if project.exists():
        ws = Workspace.load(project)       # the workspace the project lives in
    else:
        ws = Workspace.load(Path.cwd())
        project = ws.root / project
    result = backtest(ws, project, dict(args.parameter or []))
    print(f"\nresults: {result['results']}")
    for k, v in result["statistics"].items():
        print(f"  {k:28} {v}")
    return 0


def cmd_doctor(args) -> int:
    try:
        ws = Workspace.load(Path.cwd())
    except KleanError:
        ws = None
    rows = check(ws)
    for item, ok, detail in rows:
        print(f"  {'OK ' if ok else 'NO '} {item:32} {detail}")
    return 0 if all(ok for item, ok, _ in rows if not item.startswith("Python env")) else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="klean", description="Local LEAN workflow for KRX data on a LEAN source "
                                "build: no Docker, no QuantConnect account.",
                                epilog=__doc__.split("\n\n", 1)[1] if __doc__ else None,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"klean {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("install-lean", help="clone LEAN at the tested commit and build it (needs git, .NET 10)")
    s.add_argument("--dir", default="~/Lean")
    s.add_argument("--commit", default=LEAN_COMMIT)
    s.set_defaults(func=cmd_install_lean)

    s = sub.add_parser("install-python", help="create a Python 3.11 environment with pandas/numpy for LEAN")
    s.add_argument("--dir", default="~/.klean/py311")
    s.add_argument("--python", default="python3.11", help="a CPython 3.11 with a shared libpython")
    s.add_argument("--package", action="append", default=[], help="extra pip package (repeatable)")
    s.set_defaults(func=cmd_install_python)

    s = sub.add_parser("init", help="create a workspace (klean.json + data/)")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("--lean", required=True, help="the LEAN clone built with `klean install-lean`")
    s.add_argument("--python-venv", help="Python 3.11 env (from `klean install-python`) for Python projects")
    s.add_argument("--data-zip", help="also install this lean.zip")
    s.add_argument("--sample-data", action="store_true", help="also copy LEAN's sample data (US equities etc.)")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("data", help="KRX data")
    dsub = s.add_subparsers(dest="data_cmd", required=True)
    d = dsub.add_parser("install", help="unzip lean.zip into data/ (or copy from a qc-krx data root) + KRX config")
    d.add_argument("zip", nargs="?")
    d.add_argument("--root", help="qc-krx data root with lean/ (instead of a zip)")
    d.set_defaults(func=cmd_data_install)

    s = sub.add_parser("project-create", help="create a project with the KRX models")
    s.add_argument("name")
    s.add_argument("--language", choices=["python", "csharp"], default="python")
    s.set_defaults(func=cmd_project_create)

    s = sub.add_parser("backtest", help="run a backtest; results in <project>/backtests/<timestamp>/")
    s.add_argument("project")
    s.add_argument("--parameter", nargs=2, action="append", metavar=("KEY", "VALUE"),
                   help="algorithm parameter (get_parameter / GetParameter), repeatable")
    s.set_defaults(func=cmd_backtest)

    s = sub.add_parser("doctor", help="check dotnet, the LEAN build, data and the Python env")
    s.set_defaults(func=cmd_doctor)

    args = p.parse_args(argv)
    try:
        return args.func(args) or 0
    except KleanError as e:
        print(f"klean: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""`klean report`: LEAN's HTML strategy report for a results folder, like `lean report`.

LEAN's ``Report`` project (part of the LEAN clone, built on first use) reads ``<Algorithm>.json``,
replays the orders against the workspace's data for the point-in-time portfolios, and draws the
charts with matplotlib in the workspace's Python 3.11 environment (so a report needs that
environment even for a C# run). The report is written to ``<run>/report.html`` by default.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from klean import results
from klean.backtest import python_env
from klean.workspace import KleanError, Workspace, dotnet, run, venv_python

# The matplotlib version of LEAN's foundation Docker image (DockerfileLeanFoundation).
REPORT_PACKAGES = ["matplotlib==3.8.4"]
BROWSERS = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")


def report_dir(ws: Workspace) -> Path:
    return Path(ws.lean_root) / "Report" / "bin" / "Release"


def build_report(ws: Workspace, force: bool = False, log=print) -> Path:
    """Build LEAN's Report project once (about 30 s); return its output folder."""
    out = report_dir(ws)
    if force or not (out / "QuantConnect.Report.dll").exists():
        csproj = Path(ws.lean_root) / "Report" / "QuantConnect.Report.csproj"
        if not csproj.exists():
            raise KleanError(f"{csproj} not found: is lean_root a LEAN clone?")
        log("klean: building LEAN's Report project (once)")
        run([dotnet(), "build", str(csproj), "-c", "Release", "-nologo", "-v", "q"])
    return out


def ensure_packages(ws: Workspace, log=print) -> None:
    """matplotlib in the workspace's Python environment (installed on first use)."""
    env = python_env(ws)
    py = str(venv_python(ws.python_venv))
    if subprocess.run([py, "-c", "import matplotlib"], capture_output=True).returncode:
        log(f"klean: installing {' '.join(REPORT_PACKAGES)} into {ws.python_venv} (once)")
        run([py, "-m", "pip", "install", "-q", *REPORT_PACKAGES], env=env)


def default_description(run_dir: Path) -> str:
    """One line from the run's manifest: algorithm, parameters, run, data, engine."""
    path = run_dir / "manifest.json"
    if not path.exists():
        return ""
    m = json.loads(path.read_text(encoding="utf-8"))
    parts = [f"{m.get('algorithm', '')} ({m.get('language', '')})"]
    if m.get("parameters"):
        parts.append("parameters " + ", ".join(f"{k}={v}" for k, v in m["parameters"].items()))
    parts.append(f"run {results.label(run_dir)}")
    if m.get("data_last_date"):
        d = m["data_last_date"]
        parts.append(f"KRX data to {d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else f"KRX data to {d}")
    if m.get("lean_commit"):
        parts.append(f"LEAN {m['lean_commit'][:7]}")
    return "; ".join(parts)


def to_pdf(html: Path, pdf: Path) -> None:
    """wkhtmltopdf (what LEAN uses) if installed, otherwise a headless Chromium/Chrome."""
    if shutil.which("wkhtmltopdf"):
        cmd = ["wkhtmltopdf", "-q", str(html), str(pdf)]
        if shutil.which("xvfb-run"):
            cmd = ["xvfb-run", "-a", *cmd]
    else:
        browser = next((shutil.which(b) for b in BROWSERS if shutil.which(b)), None)
        if not browser:
            raise KleanError("--pdf needs wkhtmltopdf or Chromium/Chrome on the PATH; the HTML report was written")
        # LEAN's report pages are 1200 x 1698 px boxes: one PDF page each.
        printable = html.with_name(html.stem + "-print.html")
        printable.write_text(html.read_text(encoding="utf-8").replace(
            "</head>", "<style>@page { size: 1200px 1698px; margin: 0 }</style></head>", 1), encoding="utf-8")
        cmd = [browser, "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
               f"--print-to-pdf={pdf}", printable.resolve().as_uri()]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    finally:
        if not shutil.which("wkhtmltopdf"):
            printable.unlink(missing_ok=True)
    if r.returncode or not pdf.exists():
        raise KleanError(f"PDF conversion failed ({' '.join(cmd[:2])}): {(r.stderr or r.stdout)[-500:]}")


def report(ws: Workspace, run_dir: Path, *, destination: Path | None = None, strategy_name: str = "",
           strategy_version: str = "", strategy_description: str | None = None, overwrite: bool = False,
           css: Path | None = None, html: Path | None = None, pdf: bool = False, log=print) -> dict:
    full = run_dir / results.summary_file(run_dir).name.replace("-summary.json", ".json")
    if not full.exists():
        raise KleanError(f"{full} not found")
    dest = (destination.expanduser() if destination else run_dir / "report.html").resolve()
    if dest.suffix.lower() != ".html":
        raise KleanError("--report-destination must end in .html")
    if dest.exists() and not overwrite:
        raise KleanError(f"{dest} already exists (use --overwrite)")
    for f in (css, html):
        if f and not f.expanduser().is_file():
            raise KleanError(f"{f} not found")
    dest.parent.mkdir(parents=True, exist_ok=True)
    out = build_report(ws, log=log)
    ensure_packages(ws, log=log)
    project = run_dir.parents[2].name if run_dir.parent.parent.name == "optimizations" else run_dir.parent.parent.name
    config = {"data-folder": f"{ws.data}/",
              "backtest-data-source-file": str(full),
              "report-destination": str(dest),
              "strategy-name": strategy_name or project,
              "strategy-version": strategy_version,
              "strategy-description": default_description(run_dir) if strategy_description is None
              else strategy_description,
              "close-automatically": True}
    if css:
        config["report-css-override-file"] = str(css.expanduser().resolve())
    if html:
        config["report-html-custom-file"] = str(html.expanduser().resolve())
    console = dest.with_name(dest.stem + "-console.txt")
    log(f"klean: report for {results.label(run_dir)} -> {dest}")
    if dest.exists():
        dest.unlink()
    # LEAN's Report takes most settings only from ./config.json, and reads template.html, css/ and
    # ReportCharts.py from the current folder: run it in a scratch folder with copies of those.
    with tempfile.TemporaryDirectory(prefix="klean-report-") as tmp, open(console, "w", encoding="utf-8") as f:
        work = Path(tmp)
        shutil.copy(out / "template.html", work)
        shutil.copy(out / "ReportCharts.py", work)
        shutil.copytree(out / "css", work / "css")
        (work / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        code = subprocess.run([dotnet(), str(out / "QuantConnect.Report.dll")], cwd=work,
                              env={**os.environ, **python_env(ws)}, stdout=f, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL).returncode
    if not dest.exists():
        tail = "\n".join(console.read_text(encoding="utf-8", errors="replace").splitlines()[-15:])
        raise KleanError(f"LEAN's Report failed (exit {code}); see {console}\n{tail}")
    res = {"report": str(dest), "console": str(console), "exit_code": code}
    if pdf:
        pdf_path = dest.with_suffix(".pdf")
        to_pdf(dest, pdf_path)
        res["pdf"] = str(pdf_path)
    return res

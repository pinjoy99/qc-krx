"""Backtest results: finding runs, run manifests, `klean compare`, `klean logs`, `klean data status`."""

from __future__ import annotations

import csv
import hashlib
import json
import zipfile
from pathlib import Path

from klean.workspace import KleanError, Workspace

MAIN_KEYS = ("Total Orders", "Compounding Annual Return", "Drawdown", "Sharpe Ratio", "Net Profit",
             "Alpha", "Beta", "Total Fees", "End Equity")


# ---------------------------------------------------------------- runs

def runs(project: Path) -> list[Path]:
    """Results folders of a project, oldest first (folder names start with a timestamp)."""
    d = project / "backtests"
    return sorted(p for p in d.iterdir() if p.is_dir()) if d.is_dir() else []


def resolve_run(ws: Workspace, ref: str) -> Path:
    """A results folder from: a results folder path, a project (its latest run), or
    ``PROJECT/RUN`` / ``PROJECT@RUN`` where RUN is a folder name or a unique prefix."""
    p = Path(ref).expanduser()
    for base in (p, ws.root / ref):
        if base.is_dir() and summary_file(base, required=False):
            return base.resolve()
        if base.is_dir() and (base / "backtests").is_dir():
            found = runs(base)
            if not found:
                raise KleanError(f"{base} has no backtests yet")
            return found[-1].resolve()
    project, _, name = ref.replace("@", "/").rpartition("/")
    if project and name:
        proj = ws.root / project
        matches = [r for r in runs(proj) if r.name == name or r.name.startswith(name)]
        if len(matches) == 1:
            return matches[0].resolve()
        if len(matches) > 1:
            raise KleanError(f"{ref} matches several runs: {', '.join(m.name for m in matches)}")
    raise KleanError(f"no run found for {ref!r} (give a results folder, a project, or PROJECT/RUN)")


def summary_file(run: Path, required: bool = True) -> Path | None:
    found = sorted(run.glob("*-summary.json"))
    if not found and required:
        raise KleanError(f"no *-summary.json in {run}")
    return found[0] if found else None


def statistics(run: Path) -> dict[str, str]:
    return json.loads(summary_file(run).read_text(encoding="utf-8")).get("statistics", {})


def equity_curve(run: Path) -> list[tuple[int, float]]:
    """(unix time, close) of the 'Strategy Equity' chart in <Algorithm>.json."""
    summary = summary_file(run)
    full = run / summary.name.replace("-summary.json", ".json")
    if not full.exists():
        return []
    charts = json.loads(full.read_text(encoding="utf-8")).get("charts", {})
    series = charts.get("Strategy Equity", {}).get("series", {}).get("Equity", {})
    return [(int(v[0]), float(v[4] if len(v) > 4 else v[1])) for v in series.get("values", [])]


# ---------------------------------------------------------------- compare

def compare(run_paths: list[Path], all_keys: bool = False) -> tuple[list[str], list[list[str]], dict]:
    """(header, rows, verdict) comparing the statistics of several runs."""
    stats = [statistics(r) for r in run_paths]
    keys = list(MAIN_KEYS)
    if all_keys:
        keys += sorted({k for s in stats for k in s} - set(MAIN_KEYS))
    rows = []
    differing = []
    for k in keys:
        values = [s.get(k, "") for s in stats]
        same = len(set(values)) == 1
        if not same:
            differing.append(k)
        rows.append([k, *values, "" if same else "≠"])
    curves = [equity_curve(r) for r in run_paths]
    curves_same = all(c == curves[0] for c in curves[1:]) if all(curves) else None
    header = ["statistic", *[label(r) for r in run_paths], ""]
    verdict = {"differing": differing, "equity_curves_identical": curves_same,
               "identical": not differing and curves_same is not False}
    return header, rows, verdict


def label(run: Path) -> str:
    return f"{run.parent.parent.name}/{run.name}"


def format_table(header: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]
    line = lambda r: "  ".join(str(c).ljust(w) for c, w in zip(r, widths)).rstrip()
    return "\n".join([line(header), line(["-" * w for w in widths]), *[line(r) for r in rows]])


# ---------------------------------------------------------------- manifest

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project_files(project: Path) -> dict[str, str]:
    """sha256 of the project's source files (what the run was built from)."""
    out = {}
    for p in sorted(project.rglob("*")):
        rel = p.relative_to(project)
        if p.is_file() and rel.parts[0] not in ("backtests", "bin", "obj", "__pycache__") \
                and p.suffix in (".py", ".cs", ".csproj", ".txt", ".json"):
            out[rel.as_posix()] = sha256(p)
    return out


# ---------------------------------------------------------------- logs

def log_text(run: Path, console: bool = False) -> str:
    if console:
        path = run / "console.txt"
    else:
        found = sorted(run.glob("*-log.txt"))
        path = found[0] if found else run / "console.txt"
    if not path.exists():
        raise KleanError(f"no log in {run}")
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- data status

def data_status(ws: Workspace) -> dict:
    """What KRX data the workspace has."""
    krx = ws.data / "equity" / "krx"
    out: dict = {"folder": str(krx), "securities": len(list((krx / "daily").glob("*.zip")))}
    sec = krx / "securities.csv"
    if sec.exists():
        with open(sec, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        firsts = [r["krx_first_date"] for r in rows if r.get("krx_first_date")]
        lasts = [r["krx_last_date"] for r in rows if r.get("krx_last_date")]
        if lasts:
            last = max(lasts)
            out.update(first_date=min(firsts), last_date=last,
                       active=sum(1 for d in lasts if d == last), delisted_or_suspended=sum(1 for d in lasts if d < last))
            markets: dict[str, int] = {}
            for r in rows:
                if r.get("krx_last_date") == last:
                    markets[r.get("market", "")] = markets.get(r.get("market", ""), 0) + 1
            out["active_by_market"] = markets
    uni = sorted(p.stem for p in (krx / "universe").glob("*.zip"))
    if uni:
        out["universe_files"] = {"count": len(uni), "first": uni[0], "last": uni[-1]}
    out["factor_files"] = len(list((krx / "factor_files").glob("*.csv")))
    indices = {}
    for z in sorted((ws.data / "index" / "krx" / "daily").glob("*.zip")):
        with zipfile.ZipFile(z) as f:
            lines = f.read(f.namelist()[0]).decode().strip().splitlines()
        if lines:
            indices[z.stem] = {"first": lines[0][:8], "last": lines[-1][:8]}
    out["indices"] = indices
    mhdb = ws.data / "market-hours" / "market-hours-database.json"
    if mhdb.exists():
        entry = json.loads(mhdb.read_text(encoding="utf-8"))["entries"].get("Equity-krx-[*]")
        out["market_hours"] = {"installed": entry is not None,
                               "holidays": len(entry["holidays"]) if entry else 0}
    return out


def last_data_date(ws: Workspace) -> str:
    try:
        return data_status(ws).get("last_date", "")
    except Exception:  # noqa: BLE001 - the manifest shouldn't fail on odd data
        return ""

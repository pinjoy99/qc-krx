"""`klean optimize`: grid search over algorithm parameters, like `lean optimize`.

LEAN's own Optimizer.Launcher starts each backtest with a fixed set of options (no --data-folder,
no --config), so its runs would read LEAN's Data folder instead of the workspace's. klean
therefore runs the grid itself: the project is compiled once, then every parameter combination
is an ordinary klean run (config.json, manifest.json, statistics) under
``<project>/optimizations/<timestamp>[_<name>]/<NNN>_<name>=<value>.../``, several at a time.
``optimization.json`` in that folder lists every run, its target value, whether it met the
constraints, and the best run.
"""

from __future__ import annotations

import datetime as dt
import itertools
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation
from pathlib import Path

from klean import results
from klean.backtest import check_project, prepare, run_once
from klean.workspace import KleanError, Workspace

OPERATORS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b,
             ">=": lambda a, b: a >= b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}
MAX_BACKTESTS = 500


def number(text) -> float | None:
    """'22.398%' -> 22.398, '₩13395456.00' -> 13395456.0, '0.547' -> 0.547, '' -> None."""
    s = re.sub(r"[^0-9.\-eE]", "", str(text or ""))
    try:
        return float(s) if s not in ("", "-", ".") else None
    except ValueError:
        return None


def fmt(d: Decimal) -> str:
    """Decimal('15.0') -> '15', Decimal('0.50') -> '0.5'."""
    s = format(d.normalize(), "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def parameter_values(name: str, low: str, high: str, step: str) -> list[str]:
    try:
        lo, hi, st = Decimal(low), Decimal(high), Decimal(step)
    except InvalidOperation:
        raise KleanError(f"parameter {name}: min, max and step must be numbers") from None
    if st <= 0 or hi < lo:
        raise KleanError(f"parameter {name}: need min <= max and step > 0")
    out, v = [], lo
    while v <= hi:
        out.append(fmt(v))
        v += st
    return out


def grid(specs: list[tuple[str, str, str, str]]) -> list[dict[str, str]]:
    names = [s[0] for s in specs]
    if len(set(names)) != len(names):
        raise KleanError("each parameter can be given only once")
    values = [parameter_values(*s) for s in specs]
    return [dict(zip(names, combo)) for combo in itertools.product(*values)]


def parse_constraint(text: str) -> tuple[str, str, float]:
    """'Drawdown < 25' / 'Sharpe Ratio >= 0.5' (values as shown in the statistics, % without the %)."""
    m = re.match(r"^\s*(.+?)\s*(<=|>=|==|!=|<|>)\s*(-?[0-9.]+)\s*%?\s*$", text)
    if not m:
        raise KleanError(f"constraint {text!r}: use 'STATISTIC OP VALUE', e.g. 'Drawdown < 25'")
    return m.group(1), m.group(2), float(m.group(3))


def run_folder_name(i: int, params: dict[str, str]) -> str:
    label = "_".join(f"{k}={v}" for k, v in params.items())
    return f"{i:03d}_" + re.sub(r"[^A-Za-z0-9._=-]+", "-", label)[:120]


def evaluate(run_dir: Path, target: str, constraints: list[tuple[str, str, float]]) -> dict:
    try:
        stats = results.statistics(run_dir)
    except KleanError:
        return {"ok": False, "target_value": None, "passes": False, "failed_constraints": [], "stats": {}}
    failed = []
    for stat, op, value in constraints:
        v = number(stats.get(stat))
        if v is None or not OPERATORS[op](v, value):
            failed.append(f"{stat} {op} {value:g}")
    return {"ok": True, "target_value": number(stats.get(target)), "passes": not failed,
            "failed_constraints": failed,
            "stats": {k: stats.get(k, "") for k in (*results.MAIN_KEYS, target)}}


def best_run(runs: list[dict], direction: str) -> dict | None:
    candidates = [r for r in runs if r["ok"] and r["passes"] and r["target_value"] is not None]
    if not candidates:
        return None
    return (max if direction == "max" else min)(candidates, key=lambda r: r["target_value"])


def optimize(ws: Workspace, project: Path, specs: list[tuple[str, str, str, str]], *, target: str = "Sharpe Ratio",
             direction: str = "max", constraints: list[str] | None = None, max_concurrent: int = 0,
             extra_config: dict[str, str] | None = None, name: str = "", build_config: str = "Release",
             max_backtests: int = MAX_BACKTESTS, estimate: bool = False, log=print) -> dict:
    if not specs:
        raise KleanError("give at least one --parameter NAME MIN MAX STEP")
    if direction not in ("max", "min"):
        raise KleanError("--target-direction is max or min")
    combos = grid(specs)
    parsed = [parse_constraint(c) for c in (constraints or [])]
    workers = max_concurrent or max(1, (os.cpu_count() or 2) // 2)
    if estimate:
        return {"backtests": len(combos), "concurrent": workers}
    if len(combos) > max_backtests:
        raise KleanError(f"{len(combos)} combinations; the limit is {max_backtests} (raise it with --max-backtests)")
    project, language = check_project(ws, project)
    location, cls, env = prepare(ws, project, language, build_config)   # compile once
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") if name else ""
    out = project / "optimizations" / (f"{stamp}_{safe}" if safe else stamp)
    out.mkdir(parents=True)
    lean_config = {**ws.lean_config, **(extra_config or {})}
    log(f"klean: optimizing {cls} ({language}): {len(combos)} backtests, {workers} at a time -> {out}")
    started = time.time()
    runs: list[dict] = []

    def one(i: int, params: dict[str, str]) -> dict:
        run_dir = out / run_folder_name(i, params)
        r = run_once(ws, project, language, location, cls, env, run_dir, params, lean_config,
                     backtest_name=f"{safe or 'opt'}-{i:03d}", build_config=build_config, quiet=True)
        return {"index": i, "folder": run_dir.name, "parameters": params, "exit_code": r["exit_code"],
                **evaluate(run_dir, target, parsed)}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, i, p) for i, p in enumerate(combos, 1)]
        for done, f in enumerate(as_completed(futures), 1):
            r = f.result()
            runs.append(r)
            shown = "failed" if not r["ok"] else f"{target} {r['stats'].get(target) or r['target_value']}" + \
                ("" if r["passes"] else f"  (fails {', '.join(r['failed_constraints'])})")
            log(f"  [{done}/{len(combos)}] {' '.join(f'{k}={v}' for k, v in r['parameters'].items())}: {shown}")
    runs.sort(key=lambda r: r["index"])
    best = best_run(runs, direction)
    summary = {"project": project.name, "algorithm": cls, "language": language, "strategy": "grid",
               "target": target, "direction": direction, "constraints": constraints or [],
               "parameters": [{"name": n, "min": lo, "max": hi, "step": st} for n, lo, hi, st in specs],
               "lean_config": lean_config, "started_utc": dt.datetime.fromtimestamp(started, dt.timezone.utc)
               .strftime("%Y-%m-%dT%H:%M:%SZ"), "seconds": round(time.time() - started, 1),
               "concurrent": workers, "runs": runs, "best": best["folder"] if best else None}
    (out / "optimization.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary["folder"] = str(out)
    return summary


def rank_key(summary: dict, r: dict) -> tuple:
    """Ranking order: by the target (best first); runs failing constraints after; failed runs last."""
    group = 0 if r["ok"] and r["passes"] and r["target_value"] is not None else 1 if r["ok"] else 2
    tv = r["target_value"] if r["target_value"] is not None else 0
    return (group, -tv if summary["direction"] == "max" else tv)


def ranked(summary: dict) -> list[dict]:
    return sorted(summary["runs"], key=lambda r: rank_key(summary, r))


def ranking(summary: dict) -> tuple[list[str], list[list[str]]]:
    """Table rows in ranking order."""
    names = [p["name"] for p in summary["parameters"]]
    header = ["", *names, summary["target"], "CAGR", "Drawdown", "Orders", "End Equity", "constraints"]
    rows = []
    for r in ranked(summary):
        s = r["stats"]
        rows.append(["★" if r["folder"] == summary["best"] else "", *[r["parameters"][n] for n in names],
                     s.get(summary["target"], "") or ("" if r["target_value"] is None else f"{r['target_value']:g}"),
                     s.get("Compounding Annual Return", ""), s.get("Drawdown", ""), s.get("Total Orders", ""),
                     s.get("End Equity", ""),
                     "failed run" if not r["ok"] else "ok" if r["passes"] else "fails: " + ", ".join(r["failed_constraints"])])
    return header, rows

"""Install the built LEAN data into a LEAN ``Data/`` folder.

LEAN already knows the ``krx`` market (id 43) for KOSPI 200 futures and indices, but ships no
equity entries for it. This copies ``lean/equity/krx`` (daily zips, factor files, map files,
universe files, securities.csv) into ``<Data>/equity/krx`` and ``lean/index/krx`` (KOSPI,
KOSPI 200, ... index levels) into ``<Data>/index/krx``, and adds what LEAN needs to trade KRX
equities:

* ``market-hours-database.json``: an ``Equity-krx-[*]`` entry, Asia/Seoul, regular session
  09:00-15:30. Holidays come from LEAN's own ``Index-krx-[*]`` entry when present (maintained by
  QuantConnect, includes future years) plus every weekday without trading in the KRX data.
* ``symbol-properties-database.csv``: ``krx,[*],equity,,KRW,1,1,1`` (KRW quote currency, 1-won
  price step, 1-share lots). Real KRX tick sizes vary with price; model that in the algorithm.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
import logging
import os
import shutil
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)

ENTRY = "Equity-krx-[*]"
SYMBOL_PROPERTIES = "krx,[*],equity,,KRW,1,1,1"


def _session(start: str, end: str, state: str) -> dict:
    return {"start": start, "end": end, "state": state}


def trading_holidays(root: Path) -> list[str]:
    """Weekdays between the first and last KRX trading day with no data in any market (M/d/yyyy)."""
    days: set[str] = set()
    empty: set[str] = set()
    for path in (root / "raw" / "krx").glob("*/*/*.csv.gz"):
        with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
            has_price = any(r.get("TDD_CLSPRC") not in ("", "-", "0", None) for r in csv.DictReader(f))
        (days if has_price else empty).add(path.name[:8])
    if not days:
        return []
    first, last = min(days), max(days)
    d = dt.datetime.strptime(first, "%Y%m%d").date()
    stop = dt.datetime.strptime(last, "%Y%m%d").date()
    out = []
    while d <= stop:
        s = d.strftime("%Y%m%d")
        if d.weekday() < 5 and s not in days:
            out.append(f"{d.month}/{d.day}/{d.year}")
        d += dt.timedelta(days=1)
    return out


def equity_entry(lean_holidays: list[str], data_holidays: list[str]) -> dict:
    holidays = sorted(set(lean_holidays) | set(data_holidays),
                      key=lambda s: dt.datetime.strptime(s, "%m/%d/%Y"))
    week = [_session("08:30:00", "09:00:00", "premarket"), _session("09:00:00", "15:30:00", "market"),
            _session("15:40:00", "18:00:00", "postmarket")]
    return {"dataTimeZone": "Asia/Seoul", "exchangeTimeZone": "Asia/Seoul",
            "sunday": [], "monday": week, "tuesday": week, "wednesday": week, "thursday": week,
            "friday": week, "saturday": [], "holidays": holidays, "earlyCloses": {}}


def package(root: Path, out: Path, market: str = "krx", prefix: str = "data") -> int:
    """Zip the built LEAN data in LEAN's Data-folder layout: ``{prefix}/equity/{market}/...`` and
    ``{prefix}/index/{market}/...``. Unzipped into a `lean init` workspace (prefix "data") it lands
    in the workspace's data folder; then run ``lean-install --config-only`` on that folder for the
    market hours and symbol properties (they live in LEAN's own files, so they aren't in the zip)."""
    lean_root = root / "lean"
    dirs = [d for d in (lean_root / "equity" / market, lean_root / "index" / market) if d.is_dir()]
    if not dirs:
        raise SystemExit(f"{lean_root / 'equity' / market} not found: run `build` first")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    n = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for d in dirs:
            for path in sorted(d.rglob("*")):
                if path.is_file():
                    rel = path.relative_to(lean_root).as_posix()
                    if rel.startswith(f"equity/{market}/minute/"):
                        continue  # minute data was removed from the project (2026-10-11)
                    # Already-compressed LEAN zips are stored, not compressed again.
                    z.write(path, f"{prefix}/{rel}" if prefix else rel,
                            zipfile.ZIP_STORED if path.suffix == ".zip" else zipfile.ZIP_DEFLATED)
                    n += 1
    os.replace(tmp, out)
    log.info("lean-package: %d files -> %s (%s/equity/%s, %s/index/%s)", n, out, prefix, market, prefix, market)
    return n


def install(root: Path, lean_data: Path, market: str = "krx", config_only: bool = False) -> dict:
    """Copy the built LEAN data into ``lean_data`` and add the KRX equity market hours and symbol
    properties. With ``config_only`` the data is assumed to be there already (e.g. unzipped from
    ``lean-package``) and only the two config files are updated."""
    src = root / "lean" / "equity" / market
    if not config_only and not src.is_dir():
        raise SystemExit(f"{src} not found: run `build` first (or use --config-only if the data is already in {lean_data})")
    mhdb_path = lean_data / "market-hours" / "market-hours-database.json"
    spdb_path = lean_data / "symbol-properties" / "symbol-properties-database.csv"
    if not mhdb_path.exists() or not spdb_path.exists():
        raise SystemExit(f"{lean_data} doesn't look like a LEAN Data folder (no market-hours/symbol-properties)")

    dst = lean_data / "equity" / market
    if config_only:
        if not (dst / "daily").is_dir():
            log.warning("lean-install: %s has no daily data yet (unzip lean.zip there first)", dst)
    else:
        shutil.copytree(src, dst, dirs_exist_ok=True)
        index_src = root / "lean" / "index" / market
        if index_src.is_dir():  # LEAN already has Index-<market> hours and symbol properties
            shutil.copytree(index_src, lean_data / "index" / market, dirs_exist_ok=True)
    if (dst / "minute").is_dir():
        # minute files installed before minute data was removed from the project (2026-10-11)
        shutil.rmtree(dst / "minute")
        log.info("lean-install: removed old minute files from %s", dst)

    mhdb = json.loads(mhdb_path.read_text(encoding="utf-8"))
    entries = mhdb["entries"]
    lean_holidays = entries.get(f"Index-{market}-[*]", {}).get("holidays", [])
    data_holidays = trading_holidays(root)
    entries[ENTRY.replace("krx", market)] = equity_entry(lean_holidays, data_holidays)
    mhdb_path.write_text(json.dumps(mhdb, indent=2), encoding="utf-8")

    line = SYMBOL_PROPERTIES.replace("krx", market, 1)
    lines = spdb_path.read_text(encoding="utf-8").splitlines()
    if not any(l.startswith(f"{market},[*],equity,") for l in lines):
        lines.append(line)
        spdb_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    only_data = sorted(set(data_holidays) - set(lean_holidays), key=lambda s: dt.datetime.strptime(s, "%m/%d/%Y"))
    stats = {"securities": len(list((dst / "daily").glob("*.zip"))), "lean_holidays": len(lean_holidays),
             "data_holidays": len(data_holidays), "holidays_only_in_data": only_data}
    log.info("lean-install: %s -> %s (%d securities); holidays: %d from LEAN, %d from data, %d only in data",
             "config only" if config_only else src, dst, stats["securities"], len(lean_holidays), len(data_holidays), len(only_data))
    return stats

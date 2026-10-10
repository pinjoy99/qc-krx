"""Install the built LEAN data into a LEAN ``Data/`` folder.

LEAN already knows the ``krx`` market (id 43) for KOSPI 200 futures and indices, but ships no
equity entries for it. This copies ``lean/equity/krx`` (daily zips, factor files, map files)
into ``<Data>/equity/krx`` and adds what LEAN needs to trade KRX equities:

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
import shutil
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


def install(root: Path, lean_data: Path, market: str = "krx") -> dict:
    src = root / "lean" / "equity" / market
    if not src.is_dir():
        raise SystemExit(f"{src} not found: run `build` first")
    mhdb_path = lean_data / "market-hours" / "market-hours-database.json"
    spdb_path = lean_data / "symbol-properties" / "symbol-properties-database.csv"
    if not mhdb_path.exists() or not spdb_path.exists():
        raise SystemExit(f"{lean_data} doesn't look like a LEAN Data folder (no market-hours/symbol-properties)")

    dst = lean_data / "equity" / market
    shutil.copytree(src, dst, dirs_exist_ok=True)

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
             src, dst, stats["securities"], len(lean_holidays), len(data_holidays), len(only_data))
    return stats

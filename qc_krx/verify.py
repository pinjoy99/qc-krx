"""Cross-check the KRX Open API data (the only source of the LEAN daily files) against the
auxiliary sources: aikstockdata.com and Yahoo Finance.

Neither auxiliary source feeds the LEAN daily files; they exist so differences can be found.
Outputs, under ``reports/``:

* ``verify_summary.csv`` - per source: stock-days compared, matching, differing, and stock-days
  the source has but KRX doesn't.
* ``verify_mismatches.csv`` - one row per differing field: source, code, date, field, krx, other.
"""

from __future__ import annotations

import csv
import io
import logging
import shutil
from pathlib import Path

from qc_krx import build

log = logging.getLogger(__name__)

FIELDS = ("open", "high", "low", "close", "volume")


def _int(v: str) -> int | None:
    v = (v or "").strip()
    if not v or v == "-":
        return None
    return int(round(float(v)))


def load_aik_daily(root: Path) -> dict[str, dict[str, tuple]]:
    """aikstockdata daily archive: code -> date -> (o, h, l, c, v)."""
    out: dict[str, dict[str, tuple]] = {}
    for path in sorted((root / "raw" / "daily").glob("quotes_*.csv")):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                close = _int(r["clpr"])
                if not close:
                    continue
                # 0 open/high/low on days without trades, as in KRX's data; use the close.
                o, h, l = (_int(r[k]) or close for k in ("mkp", "hipr", "lopr"))
                out.setdefault(r["종목코드"], {})[r["basDt"]] = (o, h, l, close, _int(r["trqu"]) or 0)
    return out


def load_aik_history(path: Path) -> dict[str, tuple]:
    """aikstockdata per-stock history: date -> (close, volume); no open/high/low."""
    out = {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            close = _int(r["close"])
            if close:
                out[r["date"]] = (None, None, None, close, _int(r["volume"]) or 0)
    return out


def load_yahoo_daily(path: Path) -> dict[str, tuple]:
    out = {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            close = _int(r["close"])
            if close:
                out[r["date"]] = (_int(r["open"]), _int(r["high"]), _int(r["low"]), close, _int(r["volume"]) or 0)
    return out


def compare(source: str, code: str, krx: dict[str, tuple], other: dict[str, tuple], mismatches: list,
            totals: dict) -> None:
    t = totals.setdefault(source, {"compared": 0, "matching": 0, "differing": 0, "not_in_krx": 0})
    for date, bar in other.items():
        k = krx.get(date)
        if k is None:
            t["not_in_krx"] += 1
            continue
        t["compared"] += 1
        diff = [(f, k[i], bar[i]) for i, f in enumerate(FIELDS) if bar[i] is not None and bar[i] != k[i]]
        if diff:
            t["differing"] += 1
            mismatches.extend((source, code, date, f, a, b) for f, a, b in diff)
        else:
            t["matching"] += 1


def verify(root: Path) -> dict:
    stage = root / ".verify" / "krx_staged"
    meta, _ = build.stage_krx(root, stage)
    if not meta:
        raise SystemExit("no raw/krx data: run `krx` first")
    aik_daily = load_aik_daily(root)
    mismatches: list = []
    totals: dict = {}
    hist_dir, ydaily_dir = root / "raw" / "history", root / "raw" / "yahoo" / "daily"
    for code in sorted(meta):
        staged, _ = build.load_staged(stage / f"{code}.csv")
        krx = {d: b[:5] for d, b in staged.items()}
        if code in aik_daily:
            compare("aikstockdata_daily", code, krx, aik_daily[code], mismatches, totals)
        if (hist_dir / f"{code}.csv").exists():
            compare("aikstockdata_history", code, krx, load_aik_history(hist_dir / f"{code}.csv"), mismatches, totals)
        if (ydaily_dir / f"{code}.csv").exists():
            compare("yahoo_daily", code, krx, load_yahoo_daily(ydaily_dir / f"{code}.csv"), mismatches, totals)
    shutil.rmtree(stage.parent, ignore_errors=True)

    out = root / "reports"
    out.mkdir(parents=True, exist_ok=True)
    (out / "verify_minute.csv").unlink(missing_ok=True)  # from before minute data was removed
    _write(out / "verify_mismatches.csv", ["source", "code", "date", "field", "krx", "other"], mismatches)
    _write(out / "verify_summary.csv", ["source", "compared", "matching", "differing", "not_in_krx"],
           [[s, t["compared"], t["matching"], t["differing"], t["not_in_krx"]] for s, t in sorted(totals.items())])
    for s, t in sorted(totals.items()):
        log.info("verify %s: %d stock-days compared, %d match, %d differ, %d not in KRX",
                 s, t["compared"], t["matching"], t["differing"], t["not_in_krx"])
    return totals


def _write(path: Path, header: list[str], rows: list) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8")

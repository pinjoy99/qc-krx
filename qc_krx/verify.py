"""Cross-check the KRX Open API data (the only source of the LEAN daily files) against the
auxiliary sources: aikstockdata.com and Yahoo Finance.

Neither auxiliary source feeds the LEAN daily files; they exist so differences can be found.
Outputs, under ``reports/``:

* ``verify_summary.csv`` - per source: stock-days compared, matching, differing, and stock-days
  the source has but KRX doesn't.
* ``verify_mismatches.csv`` - one row per differing field: source, code, date, field, krx, other.
* ``verify_minute.csv`` - one row per Yahoo minute day: bar count, first/last bar time, whether
  the first open equals KRX's open, whether all highs/lows lie inside KRX's daily range, minute
  volume / KRX volume, last minute close vs KRX close, prices off the KRX tick grid.
"""

from __future__ import annotations

import csv
import io
import logging
import shutil
from pathlib import Path

from qc_krx import build, yahoo

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


def tick(market: str, price: float) -> int:
    """KRX tick size since the 2023-01-25 reform (Yahoo minute data is always recent)."""
    if market == "ETF":
        return 5
    for limit, t in ((2000, 1), (5000, 5), (20000, 10), (50000, 50), (200000, 100), (500000, 500)):
        if price < limit:
            return t
    return 1000


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


def minute_row(code: str, date: str, market: str, krx_bar: tuple | None, rows: list[dict]) -> list:
    if not rows:
        return [code, date, 0, "", "", "", "", "", "", "", krx_bar[3] if krx_bar else "", ""]
    opens = [float(r["open"]) for r in rows]
    highs = [float(r["high"]) for r in rows]
    lows = [float(r["low"]) for r in rows]
    closes = [float(r["close"]) for r in rows]
    volume = sum(int(r["volume"]) for r in rows)
    off_tick = sum(1 for p in opens + highs + lows + closes if p % tick(market, p))
    if krx_bar is None:
        return [code, date, len(rows), rows[0]["time"], rows[-1]["time"], "", "", "", "", closes[-1], "", off_tick]
    o, h, l, c, v = krx_bar
    return [code, date, len(rows), rows[0]["time"], rows[-1]["time"],
            int(opens[0] == o), int(max(highs) <= h and min(lows) >= l), int(max(highs) == h and min(lows) == l),
            round(volume / v, 3) if v else "", closes[-1], c, off_tick]


def verify(root: Path) -> dict:
    stage = root / ".verify" / "krx_staged"
    meta, _ = build.stage_krx(root, stage)
    if not meta:
        raise SystemExit("no raw/krx data: run `krx` first")
    aik_daily = load_aik_daily(root)
    mismatches: list = []
    totals: dict = {}
    minute_rows: list = []
    hist_dir, ydaily_dir = root / "raw" / "history", root / "raw" / "yahoo" / "daily"
    yminute_dir = root / "raw" / "yahoo" / "minute"
    for code in sorted(meta):
        staged, _ = build.load_staged(stage / f"{code}.csv")
        krx = {d: b[:5] for d, b in staged.items()}
        if code in aik_daily:
            compare("aikstockdata_daily", code, krx, aik_daily[code], mismatches, totals)
        if (hist_dir / f"{code}.csv").exists():
            compare("aikstockdata_history", code, krx, load_aik_history(hist_dir / f"{code}.csv"), mismatches, totals)
        if (ydaily_dir / f"{code}.csv").exists():
            compare("yahoo_daily", code, krx, load_yahoo_daily(ydaily_dir / f"{code}.csv"), mismatches, totals)
        for path in sorted((yminute_dir / code).glob("*.csv.gz")):
            date = path.name[:8]
            minute_rows.append(minute_row(code, date, meta[code][1], krx.get(date), yahoo.read_minute_day(path)))
    shutil.rmtree(stage.parent, ignore_errors=True)

    out = root / "reports"
    out.mkdir(parents=True, exist_ok=True)
    _write(out / "verify_mismatches.csv", ["source", "code", "date", "field", "krx", "other"], mismatches)
    _write(out / "verify_minute.csv",
           ["code", "date", "bars", "first", "last", "open_eq_krx", "inside_krx_range", "range_eq_krx",
            "volume_ratio", "last_close", "krx_close", "off_tick_prices"], minute_rows)
    _write(out / "verify_summary.csv", ["source", "compared", "matching", "differing", "not_in_krx"],
           [[s, t["compared"], t["matching"], t["differing"], t["not_in_krx"]] for s, t in sorted(totals.items())])
    for s, t in sorted(totals.items()):
        log.info("verify %s: %d stock-days compared, %d match, %d differ, %d not in KRX",
                 s, t["compared"], t["matching"], t["differing"], t["not_in_krx"])
    if minute_rows:
        with_krx = [r for r in minute_rows if r[2] and r[10] != ""]
        ratios = sorted(r[8] for r in with_krx if r[8] != "")
        log.info("verify yahoo_minute: %d days (%d with KRX data); open = KRX open on %d, inside KRX range on %d, "
                 "median volume ratio %s", len(minute_rows), len(with_krx), sum(r[5] for r in with_krx),
                 sum(r[6] for r in with_krx), ratios[len(ratios) // 2] if ratios else "-")
    return totals


def _write(path: Path, header: list[str], rows: list) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8")

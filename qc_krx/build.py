"""Merge raw downloads into per-stock OHLCV files and QuantConnect LEAN daily zips.

Sources, highest priority first (the ``source`` column records which one a row came from):

* ``krx``     - KRX Open API full-market files (raw/krx), full OHLCV since 2010
* ``daily``   - aikstockdata daily archive (raw/daily), full OHLCV, last 30 days only
* ``history`` - aikstockdata per-stock history (raw/history), close/volume only, so
                open = high = low = close

Prices are raw KRW closes, NOT split-adjusted. Split/merge dates reported by the
site are kept in ``raw/history_meta.json`` under ``breaks``.
"""

from __future__ import annotations

import csv
import gzip
import io
import logging
import os
import shutil
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)

Bar = tuple[int, int, int, int, int, str]  # open, high, low, close, volume, source


def _int(v: str) -> int | None:
    v = (v or "").strip()
    if not v:
        return None
    return int(float(v))


def load_daily_archive(root: Path) -> dict[str, dict[str, Bar]]:
    """code -> date -> bar, from every raw/daily/quotes_*.csv on disk."""
    out: dict[str, dict[str, Bar]] = {}
    for path in sorted((root / "raw" / "daily").glob("quotes_*.csv")):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                close = _int(r["clpr"])
                if not close:
                    continue
                vol = _int(r["trqu"]) or 0
                # The source reports 0 for open/high/low on days without trades.
                o, h, l = (_int(r[k]) or close for k in ("mkp", "hipr", "lopr"))
                out.setdefault(r["종목코드"], {})[r["basDt"]] = (o, h, l, close, vol, "daily")
    return out


def load_history(path: Path) -> dict[str, Bar]:
    bars: dict[str, Bar] = {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            close = _int(r["close"])
            if not close:
                continue
            bars[r["date"]] = (close, close, close, close, _int(r["volume"]) or 0, "history")
    return bars


def merge(*sources: dict[str, Bar]) -> list[tuple[str, Bar]]:
    """Merge date -> bar maps; later sources win."""
    merged: dict[str, Bar] = {}
    for src in sources:
        merged.update(src)
    return sorted(merged.items())


def _krx_bar(r: dict) -> Bar | None:
    close = _int(r["TDD_CLSPRC"].replace(",", ""))
    if not close:
        return None
    # KRX reports 0 for open/high/low on days without trades.
    o, h, l = (_int(r[k].replace(",", "")) or close for k in ("TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC"))
    return (o, h, l, close, _int(r["ACC_TRDVOL"].replace(",", "")) or 0, "krx")


def stage_krx(root: Path, stage: Path) -> dict[str, list[str]]:
    """Regroup raw/krx day files into one CSV per security under ``stage``, a year at a
    time to bound memory. Returns code -> [name, market, first_date, last_date]."""
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    files: dict[str, list[Path]] = {}
    for path in (root / "raw" / "krx").glob("*/*/*.csv.gz"):
        files.setdefault(path.parent.name, []).append(path)
    meta: dict[str, list[str]] = {}
    for year in sorted(files):
        lines: dict[str, list[str]] = {}
        for path in sorted(files[year], key=lambda p: p.name):
            market = path.parent.parent.name
            with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    bar = _krx_bar(r)
                    if bar is None:
                        continue
                    code, date = r["ISU_CD"], r["BAS_DD"]
                    lines.setdefault(code, []).append(f"{date},{bar[0]},{bar[1]},{bar[2]},{bar[3]},{bar[4]}\n")
                    m = meta.setdefault(code, [r["ISU_NM"], r.get("MKT_NM") or market, date, date])
                    m[2] = min(m[2], date)
                    if date >= m[3]:
                        m[0], m[1], m[3] = r["ISU_NM"], r.get("MKT_NM") or market, date
        for code, ls in lines.items():
            with open(stage / f"{code}.csv", "a", encoding="utf-8") as f:
                f.writelines(ls)
    return meta


def load_staged(path: Path) -> dict[str, Bar]:
    bars: dict[str, Bar] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            d, o, h, l, c, v = line.rstrip("\n").split(",")
            bars[d] = (int(o), int(h), int(l), int(c), int(v), "krx")
    return bars


def write_securities(root: Path, krx_meta: dict[str, list[str]], codes: list[str]) -> None:
    """securities.csv: every code in the output, with its KRX listing span when known
    (last_date before the latest KRX date means delisted or suspended)."""
    names: dict[str, tuple[str, str]] = {}
    uni = root / "raw" / "universe.csv"
    if uni.exists():
        with open(uni, encoding="utf-8", newline="") as f:
            names = {r["code"]: (r["name"], r["market"]) for r in csv.DictReader(f)}
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["code", "name", "market", "krx_first_date", "krx_last_date"])
    for code in codes:
        if code in krx_meta:
            w.writerow([code, *krx_meta[code]])
        else:
            name, market = names.get(code, ("", ""))
            w.writerow([code, name, market, "", ""])
    (root / "securities.csv").write_text(buf.getvalue(), encoding="utf-8")


def write_ohlcv_csv(path: Path, bars: list[tuple[str, Bar]]) -> None:
    buf = io.StringIO()
    buf.write("date,open,high,low,close,volume,source\n")
    for d, (o, h, l, c, v, src) in bars:
        buf.write(f"{d},{o},{h},{l},{c},{v},{src}\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(buf.getvalue(), encoding="utf-8")
    os.replace(tmp, path)


def write_lean_zip(path: Path, code: str, bars: list[tuple[str, Bar]]) -> None:
    """LEAN equity daily format: ``yyyyMMdd 00:00,open,high,low,close,volume``,
    prices scaled by 10,000 (LEAN's "deci-cents" convention)."""
    lines = [f"{d} 00:00,{o * 10000},{h * 10000},{l * 10000},{c * 10000},{v}" for d, (o, h, l, c, v, _) in bars]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{code.lower()}.csv", "\n".join(lines) + "\n")
    os.replace(tmp, path)


def build(root: Path, lean: bool = True, market: str = "krx") -> int:
    daily = load_daily_archive(root)
    stage = root / ".build" / "krx_staged"
    krx_meta = stage_krx(root, stage)
    hist_dir = root / "raw" / "history"
    codes = sorted({p.stem for p in hist_dir.glob("*.csv")} | set(daily) | set(krx_meta))
    n = 0
    for code in codes:
        hpath, kpath = hist_dir / f"{code}.csv", stage / f"{code}.csv"
        history = load_history(hpath) if hpath.exists() else {}
        krx = load_staged(kpath) if kpath.exists() else {}
        bars = merge(history, daily.get(code, {}), krx)
        if not bars:
            continue
        write_ohlcv_csv(root / "ohlcv" / f"{code}.csv", bars)
        if lean:
            write_lean_zip(root / "lean" / "equity" / market / "daily" / f"{code.lower()}.zip", code, bars)
        n += 1
    write_securities(root, krx_meta, codes)
    shutil.rmtree(stage.parent, ignore_errors=True)
    log.info("build: wrote %d securities (%d with KRX data, %d aikstockdata daily file(s))",
             n, len(krx_meta), len(list((root / "raw" / "daily").glob("quotes_*.csv"))))
    return n

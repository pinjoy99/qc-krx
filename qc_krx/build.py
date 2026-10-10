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
import re
import shutil
import zipfile
from pathlib import Path

from qc_krx import factors
from qc_krx.dividends import build_dividends
from qc_krx.rights import build_corporate_actions

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


def stage_krx(root: Path, stage: Path) -> tuple[dict[str, list[str]], list[str]]:
    """Regroup raw/krx day files into one CSV per security under ``stage``, a year at a
    time to bound memory; each line also keeps KRX's base price (close - change) for the
    factor files. Returns (code -> [name, market, first_date, last_date], trading dates)."""
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    files: dict[str, list[Path]] = {}
    for path in (root / "raw" / "krx").glob("*/*/*.csv.gz"):
        files.setdefault(path.parent.name, []).append(path)
    meta: dict[str, list[str]] = {}
    calendar: set[str] = set()
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
                    raw_change = r.get("CMPPREVDD_PRC", "").replace(",", "").strip()
                    base = bar[3] - int(float(raw_change)) if raw_change not in ("", "-") else ""
                    lines.setdefault(code, []).append(f"{date},{bar[0]},{bar[1]},{bar[2]},{bar[3]},{bar[4]},{base}\n")
                    calendar.add(date)
                    m = meta.setdefault(code, [r["ISU_NM"], r.get("MKT_NM") or market, date, date])
                    m[2] = min(m[2], date)
                    if date >= m[3]:
                        m[0], m[1], m[3] = r["ISU_NM"], r.get("MKT_NM") or market, date
        for code, ls in lines.items():
            with open(stage / f"{code}.csv", "a", encoding="utf-8") as f:
                f.writelines(ls)
    return meta, sorted(calendar)


def load_staged(path: Path) -> tuple[dict[str, Bar], dict[str, int]]:
    """(date -> bar, date -> KRX base price) for one staged security."""
    bars: dict[str, Bar] = {}
    bases: dict[str, int] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            d, o, h, l, c, v, base = line.rstrip("\n").split(",")
            bars[d] = (int(o), int(h), int(l), int(c), int(v), "krx")
            if base:
                bases[d] = int(base)
    return bars, bases


# KRX security-master fields copied into securities.csv: output column -> API field.
INFO_FIELDS = {
    "isin": "ISU_CD", "name_en": "ISU_ENG_NM", "listing_date": "LIST_DD",
    "security_group": "SECUGRP_NM", "share_class": "KIND_STKCERT_TP_NM", "par_value": "PARVAL",
}


def load_latest_info(root: Path) -> dict[str, dict]:
    """code -> row from the newest raw/krx_info snapshot of each market."""
    info: dict[str, dict] = {}
    for market_dir in sorted((root / "raw" / "krx_info").glob("*")):
        snapshots = sorted(market_dir.glob("*.csv.gz"))
        if snapshots:
            with gzip.open(snapshots[-1], "rt", encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    info[r["ISU_SRT_CD"]] = r
    return info


def write_securities(root: Path, krx_meta: dict[str, list[str]], codes: list[str]) -> None:
    """securities.csv: every code in the output, with its KRX listing span when known
    (last_date before the latest KRX date means delisted or suspended), plus security
    master fields from the latest `krx-info` snapshot (blank for codes not in it)."""
    info = load_latest_info(root)
    names: dict[str, tuple[str, str]] = {}
    uni = root / "raw" / "universe.csv"
    if uni.exists():
        with open(uni, encoding="utf-8", newline="") as f:
            names = {r["code"]: (r["name"], r["market"]) for r in csv.DictReader(f)}
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["code", "name", "market", "krx_first_date", "krx_last_date", *INFO_FIELDS])
    for code in codes:
        extra = [info.get(code, {}).get(k, "") for k in INFO_FIELDS.values()]
        if code in krx_meta:
            w.writerow([code, *krx_meta[code], *extra])
        else:
            name, market = names.get(code, ("", ""))
            w.writerow([code, name, market, "", "", *extra])
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


# Short file names for the main indices; others become {SERIES}_{name}.
INDEX_ALIASES = {"코스피": "KOSPI", "코스피 200": "KOSPI200", "코스닥": "KOSDAQ",
                 "코스닥 150": "KOSDAQ150", "KRX 300": "KRX300"}


def index_file_name(series: str, name: str) -> str:
    if name in INDEX_ALIASES:
        return INDEX_ALIASES[name]
    return f"{series}_" + re.sub(r"[^0-9A-Za-z가-힣]+", "_", name).strip("_")


def build_indices(root: Path) -> int:
    """data/index/{name}.csv per index (date,open,high,low,close,volume,value,market_cap)
    and data/indices.csv listing them. Index levels are kept exactly as KRX reports them."""
    series_rows: dict[tuple[str, str], list[str]] = {}
    for path in sorted((root / "raw" / "krx_index").glob("*/*/*.csv.gz"), key=lambda p: p.name):
        series = path.parent.parent.name
        with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                c = r["CLSPRC_IDX"]
                if not c or c == "-":
                    continue
                o, h, l = (r[k] if r[k] and r[k] != "-" else c for k in ("OPNPRC_IDX", "HGPRC_IDX", "LWPRC_IDX"))
                series_rows.setdefault((series, r["IDX_NM"]), []).append(
                    f"{r['BAS_DD']},{o},{h},{l},{c},{r['ACC_TRDVOL']},{r['ACC_TRDVAL']},{r['MKTCAP']}\n")
    if not series_rows:
        return 0
    out = root / "index"
    out.mkdir(parents=True, exist_ok=True)
    catalog = io.StringIO()
    w = csv.writer(catalog, lineterminator="\n")
    w.writerow(["file", "series", "name", "first_date", "last_date"])
    for (series, name), lines in sorted(series_rows.items()):
        lines.sort()
        fname = index_file_name(series, name)
        (out / f"{fname}.csv").write_text("date,open,high,low,close,volume,value,market_cap\n" + "".join(lines),
                                          encoding="utf-8")
        w.writerow([f"index/{fname}.csv", series, name, lines[0][:8], lines[-1][:8]])
    (root / "indices.csv").write_text(catalog.getvalue(), encoding="utf-8")
    return len(series_rows)


def build(root: Path, lean: bool = True, market: str = "krx") -> int:
    daily = load_daily_archive(root)
    stage = root / ".build" / "krx_staged"
    krx_meta, calendar = stage_krx(root, stage)
    n_div = build_dividends(root)  # before the loop: factor files read dividends.csv
    cash_dividends = factors.load_cash_dividends(root)
    hist_dir = root / "raw" / "history"
    codes = sorted({p.stem for p in hist_dir.glob("*.csv")} | set(daily) | set(krx_meta))
    lean_dir = root / "lean" / "equity" / market
    audit = io.StringIO()
    audit.write("code,type,date,cum_date,ratio,amount\n")
    n = n_factor = 0
    for code in codes:
        hpath, kpath = hist_dir / f"{code}.csv", stage / f"{code}.csv"
        history = load_history(hpath) if hpath.exists() else {}
        krx, bases = load_staged(kpath) if kpath.exists() else ({}, {})
        bars = merge(history, daily.get(code, {}), krx)
        if not bars:
            continue
        write_ohlcv_csv(root / "ohlcv" / f"{code}.csv", bars)
        if lean:
            write_lean_zip(lean_dir / "daily" / f"{code.lower()}.zip", code, bars)
            # Factor and map files need KRX's base prices and listing span, so KRX data only.
            if krx:
                closes = sorted((d, b[3]) for d, b in krx.items())
                rows, used = factors.factor_rows(closes, bases, cash_dividends.get(code, []), calendar)
                if rows:
                    factors.write_rows(lean_dir / "factor_files" / f"{code.lower()}.csv", rows)
                    n_factor += 1
                for e in used:
                    audit.write(f"{code},{e['type']},{e['date']},{e['cum_date']},{e['ratio']:.10g},{e.get('amount', '')}\n")
                factors.write_rows(lean_dir / "map_files" / f"{code.lower()}.csv",
                                   factors.map_rows(code, closes[0][0], closes[-1][0], calendar[-1]))
        n += 1
    if lean and krx_meta:
        (root / "factor_events.csv").write_text(audit.getvalue(), encoding="utf-8")
    write_securities(root, krx_meta, codes)
    shutil.rmtree(stage.parent, ignore_errors=True)
    n_idx = build_indices(root)
    if n_idx:
        log.info("build: wrote %d indices", n_idx)
    if n_div:
        log.info("build: wrote %d dividend records", n_div)
    if n_factor:
        log.info("build: wrote %d factor files", n_factor)
    n_ca = build_corporate_actions(root)
    if n_ca:
        log.info("build: wrote %d corporate actions", n_ca)
    log.info("build: wrote %d securities (%d with KRX data, %d aikstockdata daily file(s))",
             n, len(krx_meta), len(list((root / "raw" / "daily").glob("quotes_*.csv"))))
    return n

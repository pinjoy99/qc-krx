"""Merge raw downloads into per-stock OHLCV files and QuantConnect LEAN daily zips.

For each date the full OHLCV row from a daily archive file is used when one exists;
otherwise the close/volume history row is used with open = high = low = close
(the history endpoint has no open/high/low). The ``source`` column records which.

Prices are raw KRW closes, NOT split-adjusted. Split/merge dates reported by the
site are kept in ``raw/history_meta.json`` under ``breaks``.
"""

from __future__ import annotations

import csv
import io
import logging
import os
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


def merge(history: dict[str, Bar], daily: dict[str, Bar]) -> list[tuple[str, Bar]]:
    merged = dict(history)
    merged.update(daily)
    return sorted(merged.items())


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
    hist_dir = root / "raw" / "history"
    codes = sorted({p.stem for p in hist_dir.glob("*.csv")} | set(daily))
    n = 0
    for code in codes:
        hpath = hist_dir / f"{code}.csv"
        history = load_history(hpath) if hpath.exists() else {}
        bars = merge(history, daily.get(code, {}))
        if not bars:
            continue
        write_ohlcv_csv(root / "ohlcv" / f"{code}.csv", bars)
        if lean:
            write_lean_zip(root / "lean" / "equity" / market / "daily" / f"{code.lower()}.zip", code, bars)
        n += 1
    log.info("build: wrote %d stocks (%d daily archive file(s) merged)",
             n, len(list((root / "raw" / "daily").glob("quotes_*.csv"))))
    return n

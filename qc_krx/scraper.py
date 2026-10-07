"""Download raw data files from aikstockdata.com into a local directory.

Layout under ``root`` (default ``data/``)::

    raw/universe.csv                 code,name,market for every listed stock
    raw/history/{code}.csv           date,close,volume (since 2020, not split-adjusted)
    raw/history_meta.json            per-code etag / as_of / split "breaks"
    raw/daily/quotes_YYYYMMDD.csv    full-market OHLCV for one trading day (as published)

The site only keeps the last ~30 trading days of daily OHLCV files, so run
``daily`` regularly (e.g. every trading day after 18:30 KST) to accumulate them.
"""

from __future__ import annotations

import csv
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from qc_krx.client import Client, NotModified

log = logging.getLogger(__name__)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="")
    os.replace(tmp, path)


def fetch_universe(client: Client, root: Path) -> list[tuple[str, str, str]]:
    """Fetch the stock list (KOSPI/KOSDAQ/KONEX; ETFs are not covered by the site)."""
    data = client.get_json("search_index_rows.json")
    cols = data["columns"]
    ic, iname, imkt = cols.index("c"), cols.index("n"), cols.index("m")
    rows = [(r[ic], r[iname], r[imkt]) for r in data["rows"]]
    lines = ["code,name,market"] + [",".join(_csv_cell(v) for v in r) for r in rows]
    _atomic_write(root / "raw" / "universe.csv", "\n".join(lines) + "\n")
    log.info("universe: %d stocks (as of %s)", len(rows), data.get("as_of_iso"))
    return rows


def load_universe(root: Path) -> list[tuple[str, str, str]]:
    with open(root / "raw" / "universe.csv", encoding="utf-8", newline="") as f:
        return [(r["code"], r["name"], r["market"]) for r in csv.DictReader(f)]


def _csv_cell(v: str) -> str:
    v = str(v)
    return '"' + v.replace('"', '""') + '"' if any(c in v for c in ',"\n') else v


def _load_meta(root: Path) -> dict:
    p = root / "raw" / "history_meta.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def fetch_history(client: Client, code: str, root: Path, etag: str | None = None) -> dict | None:
    """Download one stock's close/volume history. Returns its meta, or None if unchanged."""
    try:
        resp = client.get(f"s/{code}_history.json", etag=etag)
    except NotModified:
        return None
    data = resp.json()
    cols = data["columns"]
    idate, iclose, ivol = cols.index("date"), cols.index("close"), cols.index("volume")
    lines = ["date,close,volume"]
    for r in data["rows"]:
        close, vol = r[iclose], r[ivol]
        lines.append(f"{r[idate]},{'' if close is None else close},{'' if vol is None else vol}")
    _atomic_write(root / "raw" / "history" / f"{code}.csv", "\n".join(lines) + "\n")
    return {
        "etag": resp.headers.get("ETag"),
        "as_of": data.get("as_of"),
        "count": data.get("count"),
        "breaks": data.get("breaks", []),
    }


def scrape_histories(client: Client, codes: list[str], root: Path, workers: int = 4) -> dict:
    """Download histories for ``codes``, skipping files unchanged since the last run."""
    meta = _load_meta(root)
    have_file = lambda c: (root / "raw" / "history" / f"{c}.csv").exists()  # noqa: E731
    stats = {"updated": 0, "unchanged": 0, "missing": 0, "failed": 0}

    def job(code: str):
        etag = meta.get(code, {}).get("etag") if have_file(code) else None
        return code, fetch_history(client, code, root, etag)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(job, c) for c in codes]
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                code, m = fut.result()
            except Exception as e:  # keep going; report at the end
                status = getattr(getattr(e, "response", None), "status_code", None)
                stats["missing" if status == 404 else "failed"] += 1
                log.warning("history failed: %s", e)
                continue
            if m is None:
                stats["unchanged"] += 1
            else:
                meta[code] = m
                stats["updated"] += 1
            if i % 200 == 0:
                log.info("history: %d/%d", i, len(codes))
                _atomic_write(root / "raw" / "history_meta.json", json.dumps(meta, ensure_ascii=False, indent=1))
    _atomic_write(root / "raw" / "history_meta.json", json.dumps(meta, ensure_ascii=False, indent=1))
    log.info("history: %s", stats)
    return stats


def scrape_daily(client: Client, root: Path, force: bool = False) -> list[str]:
    """Download every daily OHLCV CSV the site still holds that isn't on disk yet."""
    catalog = client.get_json("index.json")
    archive = catalog["daily_archive"]
    dates = archive.get("quotes_available_dates") or archive["available_dates"]
    pattern = archive["quotes_csv_pattern"]
    out_dir = root / "raw" / "daily"
    fetched = []
    for d in dates:
        path = out_dir / f"quotes_{d}.csv"
        if path.exists() and not force:
            continue
        text = client.get_text(pattern.replace("{YYYYMMDD}", d))
        _atomic_write(path, text)
        fetched.append(d)
    log.info("daily: fetched %d new file(s), %d available on site", len(fetched), len(dates))
    return fetched

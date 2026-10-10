"""Stock dividend history from the FSC open API on data.go.kr (금융위원회_주식배당정보).

Needs a data.go.kr service key ("Decoding" key) in ``DATA_GO_KR_KEY``. The API returns the
whole table — every dividend since the 1980s for listed companies, about 72k rows — as one
snapshot, so each run downloads it all (8 calls) and keeps only the newest snapshot as
``raw/dividends/{basDt}.csv.gz`` with every API field as-is.

``build_dividends`` turns it into ``dividends.csv``. Caveats found in the data:

* ``stckParPrc`` is the *current* par value, so amount = rate x par is wrong for records
  from before a split. Only the reported amount (``stckGenrDvdnAmt``) is used as
  ``cash_per_share``; it is blank when the API gives only a rate (about 10-15% of cash
  dividends each year). The rate and par are kept in their own columns.
* Records whose amount hasn't been announced yet (e.g. a future record date) have amount 0
  and are written with a blank ``cash_per_share``.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import time
from pathlib import Path

import requests

from qc_krx.client import USER_AGENT
from qc_krx.krx_api import read_day, write_day

log = logging.getLogger(__name__)

API_URL = "https://apis.data.go.kr/1160100/GetStocDiviInfoService_V2/getDiviInfo_V2"
PAGE_SIZE = 10000

DIVIDEND_TYPES = {"01": "stock", "02": "cash", "03": "cash_and_stock", "04": "none"}


class DividendApiError(Exception):
    pass


def recent_snapshot(out_dir: Path, max_age_days: float) -> Path | None:
    """The newest snapshot in ``out_dir`` if it was saved less than ``max_age_days`` ago."""
    snaps = sorted(out_dir.glob("*.csv.gz"))
    if snaps and max_age_days > 0 and time.time() - snaps[-1].stat().st_mtime < max_age_days * 86400:
        return snaps[-1]
    return None


def key_from_env() -> str:
    key = os.environ.get("DATA_GO_KR_KEY", "").strip()
    if not key:
        raise SystemExit("DATA_GO_KR_KEY is not set (data.go.kr service key, the 'Decoding' one)")
    return key


def fetch_page(session: requests.Session, key: str, page: int, attempts: int = 8) -> dict:
    """One page of the table. The data.go.kr gateway often resets connections, so retry."""
    for attempt in range(attempts):
        try:
            resp = session.get(API_URL, params={"serviceKey": key, "resultType": "json",
                                                "numOfRows": PAGE_SIZE, "pageNo": page}, timeout=120)
            data = resp.json()
        except (requests.ConnectionError, requests.Timeout, ValueError) as e:
            if attempt == attempts - 1:
                raise DividendApiError(f"page {page}: {type(e).__name__}: {e}") from e
            log.warning("dividends page %d: %s, retrying", page, type(e).__name__)
            time.sleep(3 * (attempt + 1))
            continue
        if "response" not in data:  # gateway error, e.g. an unregistered key
            hdr = data.get("OpenAPI_ServiceResponse", {}).get("cmmMsgHeader", {})
            raise DividendApiError(f"{hdr.get('errMsg')} {hdr.get('returnAuthMsg')}".strip() or str(data)[:200])
        header = data["response"]["header"]
        if header.get("resultCode") != "00":
            raise DividendApiError(f"{header.get('resultCode')} {header.get('resultMsg')}")
        return data["response"]["body"]
    raise AssertionError("unreachable")


def fetch_all(key: str) -> list[dict]:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    rows: list[dict] = []
    page = 1
    while True:
        body = fetch_page(session, key, page)
        items = body["items"]["item"] if body.get("items") else []
        if isinstance(items, dict):  # a single-row page comes back as an object
            items = [items]
        rows += items
        total = int(body["totalCount"])
        log.info("dividends: page %d, %d/%d rows", page, len(rows), total)
        if not items or len(rows) >= total:
            return rows
        page += 1


def scrape_dividends(key: str, root: Path, max_age_days: float = 1) -> Path:
    """Download the full table and keep it as the only snapshot under raw/dividends/.
    Skipped when the saved snapshot is younger than ``max_age_days`` (0 = always download)."""
    fresh = recent_snapshot(root / "raw" / "dividends", max_age_days)
    if fresh:
        log.info("dividends: %s is less than %g day(s) old, skipping (use --force to refresh)", fresh.name, max_age_days)
        return fresh
    rows = fetch_all(key)
    if not rows:
        raise DividendApiError("empty dividend table")
    bas_dt = max(r["basDt"] for r in rows)
    out_dir = root / "raw" / "dividends"
    path = out_dir / f"{bas_dt}.csv.gz"
    write_day(path, rows)
    for old in out_dir.glob("*.csv.gz"):
        if old != path:
            old.unlink()
    log.info("dividends: %d records (basDt %s) -> %s", len(rows), bas_dt, path)
    return path


def _num(v: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _fmt(v: float) -> str:
    return str(int(v)) if v == int(v) else str(v)


def build_dividends(root: Path) -> int:
    """dividends.csv from the newest raw snapshot: one row per security per dividend event
    (no-dividend records are left out). Returns the number of rows written."""
    snapshots = sorted((root / "raw" / "dividends").glob("*.csv.gz"))
    if not snapshots:
        return 0
    out = []
    for r in read_day(snapshots[-1]):
        kind = DIVIDEND_TYPES.get(r["stckDvdnRcd"], r["stckDvdnRcdNm"])
        if kind == "none" or not r["dvdnBasDt"]:
            continue
        isin = r["isinCd"]
        amount = _num(r["stckGenrDvdnAmt"])
        diff = _num(r["stckGrdnDvdnAmt"])
        out.append([
            isin[3:9] if isin.startswith(("KR7", "KR8")) else "",
            isin, r["isinCdNm"], r["scrsItmsKcdNm"], r["stckStacMd"],
            r["dvdnBasDt"], r["cashDvdnPayDt"], r["stckHndvDt"], kind,
            _fmt(amount) if amount else "", _fmt(diff) if diff else "",
            r["stckGenrCashDvdnRt"], r["stckGenrDvdnRt"], r["stckParPrc"],
        ])
    out.sort(key=lambda row: (row[5], row[0], row[1]))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["code", "isin", "name", "share_class", "fiscal_month", "record_date", "pay_date",
                "stock_delivery_date", "type", "cash_per_share", "differential_cash_per_share",
                "cash_rate_pct", "stock_dividend_rate_pct", "par_value_current"])
    w.writerows(out)
    (root / "dividends.csv").write_text(buf.getvalue(), encoding="utf-8")
    return len(out)

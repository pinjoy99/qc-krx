"""Corporate-action schedules from the FSC open API on data.go.kr (금융위원회_주식권리일정정보).

Same ``DATA_GO_KR_KEY`` as the dividend API. One row per date of each corporate action
(record date, ex-rights date, listing date, ...) since 2010 — splits, reverse splits, bonus
and rights issues, capital reductions, mergers, name changes, dividends, shareholder
meetings — about 1.26M rows. The API ignores date-range filters, so each run downloads the
whole table (~126 pages); pages are written to ``raw/rights/.partial/`` as they arrive so an
interrupted run resumes, then combined into ``raw/rights/{YYYYMMDD}.csv.gz`` (all API fields).

The API has no stock code or ISIN, only the company registration number (``crno``);
``build_corporate_actions`` maps it to the common share's code through the dividend table,
which lists ``crno`` with every ISIN. It also gives no ratios: the split/issue ratio has to
come from the change in listed shares in the KRX daily data on the ex-date.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import logging
import os
import shutil
import time
from pathlib import Path

import requests

from qc_krx.client import USER_AGENT
from qc_krx.dividends import DividendApiError as RightsApiError  # same gateway, same errors
from qc_krx.dividends import recent_snapshot
from qc_krx.krx_api import KST, read_day, write_day

log = logging.getLogger(__name__)

API_URL = "https://apis.data.go.kr/1160100/GetStocRighScheService_V2/getRighExerReasSche_V2"
PAGE_SIZE = 10000

# stckIssuRcdNm -> English event type
EVENT_TYPES = {
    "액면분할": "split", "액면병합": "reverse_split", "무상증자": "bonus_issue", "유상증자": "rights_issue",
    "자본감소": "capital_reduction", "합병": "merger", "분할합병": "split_merger", "회사분할": "spin_off",
    "주식전환": "share_conversion", "주식이전": "share_transfer", "상호변경": "name_change",
    "배당/분배": "dividend", "정기총회": "agm", "임시총회": "egm", "종류총회": "class_meeting",
    "매수청구": "appraisal_right", "공개매수": "tender_offer", "사무인수": "registrar_change", "기타": "other",
}
# rgtExertRcdNm -> output column (the event's first date of that kind)
DATE_COLUMNS = {
    "기준일": "record_date", "권리락일": "ex_date", "상장일": "listing_date",
    "주식발행일": "issue_date", "교부/유통일": "delivery_date", "납입일": "payment_date",
    "배당금지급일(1차)": "dividend_pay_date", "총회개최일": "meeting_date",
}


def fetch_page(session: requests.Session, key: str, page: int, attempts: int = 10) -> dict:
    for attempt in range(attempts):
        try:
            resp = session.get(API_URL, params={"serviceKey": key, "resultType": "json",
                                                "numOfRows": PAGE_SIZE, "pageNo": page}, timeout=180)
            data = resp.json()
        except (requests.ConnectionError, requests.Timeout, ValueError) as e:
            if attempt == attempts - 1:
                raise RightsApiError(f"page {page}: {type(e).__name__}: {e}") from e
            log.warning("rights page %d: %s, retrying", page, type(e).__name__)
            time.sleep(4 * (attempt + 1))
            continue
        if "response" not in data:
            hdr = data.get("OpenAPI_ServiceResponse", {}).get("cmmMsgHeader", {})
            raise RightsApiError(f"{hdr.get('errMsg')} {hdr.get('returnAuthMsg')}".strip() or str(data)[:200])
        header = data["response"]["header"]
        if header.get("resultCode") != "00":
            raise RightsApiError(f"{header.get('resultCode')} {header.get('resultMsg')}")
        return data["response"]["body"]
    raise AssertionError("unreachable")


def _items(body: dict) -> list[dict]:
    items = body["items"]["item"] if body.get("items") else []
    return [items] if isinstance(items, dict) else items


def scrape_rights(key: str, root: Path, max_age_days: float = 7) -> Path:
    """Skipped when the saved snapshot is younger than ``max_age_days`` (0 = always download):
    the full table takes ~126 calls and changes slowly."""
    out_dir = root / "raw" / "rights"
    fresh = recent_snapshot(out_dir, max_age_days)
    if fresh and not (out_dir / ".partial").exists():
        log.info("rights: %s is less than %g day(s) old, skipping (use --force to refresh)", fresh.name, max_age_days)
        return fresh
    partial = out_dir / ".partial"
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    first = fetch_page(session, key, 1)
    total = int(first["totalCount"])
    pages = -(-total // PAGE_SIZE)
    marker = partial / "total.txt"
    # Resume only a run against the same table; otherwise page boundaries have moved.
    if not (marker.exists() and marker.read_text() == str(total)):
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)
        marker.write_text(str(total))
    write_day(partial / "page_00001.csv.gz", _items(first))
    for page in range(2, pages + 1):
        path = partial / f"page_{page:05d}.csv.gz"
        if path.exists():
            continue
        write_day(path, _items(fetch_page(session, key, page)))
        log.info("rights: page %d/%d", page, pages)

    today = dt.datetime.now(KST).strftime("%Y%m%d")
    final = out_dir / f"{today}.csv.gz"
    tmp = final.with_suffix(".tmp")
    n = 0
    with gzip.open(tmp, "wt", encoding="utf-8", newline="") as f:
        w = None
        for path in sorted(partial.glob("page_*.csv.gz")):
            for r in read_day(path):
                if w is None:
                    w = csv.DictWriter(f, fieldnames=list(r), lineterminator="\n", extrasaction="ignore")
                    w.writeheader()
                w.writerow(r)
                n += 1
    os.replace(tmp, final)
    for old in out_dir.glob("*.csv.gz"):
        if old != final:
            old.unlink()
    shutil.rmtree(partial, ignore_errors=True)
    log.info("rights: %d rows (API total %d) -> %s", n, total, final)
    return final


def crno_to_code(root: Path) -> dict[str, str]:
    """crno -> 6-digit code of the company's common share, from the dividend snapshot."""
    snaps = sorted((root / "raw" / "dividends").glob("*.csv.gz"))
    if not snaps:
        return {}
    best: dict[str, tuple[int, str]] = {}
    for r in read_day(snaps[-1]):
        isin = r["isinCd"]
        if not isin.startswith(("KR7", "KR8")):
            continue
        rank = 0 if r["scrsItmsKcdNm"] == "보통주" else 1
        if r["crno"] not in best or rank < best[r["crno"]][0]:
            best[r["crno"]] = (rank, isin[3:9])
    return {crno: code for crno, (_, code) in best.items()}


def build_corporate_actions(root: Path) -> int:
    """corporate_actions.csv: one row per event (company, type, base date) with its key dates
    pivoted into columns. Returns the number of events written."""
    snaps = sorted((root / "raw" / "rights").glob("*.csv.gz"))
    if not snaps:
        return 0
    codes = crno_to_code(root)
    events: dict[tuple[str, str, str], dict] = {}
    with gzip.open(snaps[-1], "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            k = (r["crno"] or r["issuCmpyKsdCustNo"], r["stckIssuRcd"], r["basDt"])
            ev = events.get(k)
            if ev is None:
                ev = events[k] = {
                    "code": codes.get(r["crno"], ""), "crno": r["crno"], "company": r["stckIssuCmpyNm"],
                    "type": EVENT_TYPES.get(r["stckIssuRcdNm"], r["stckIssuRcdNm"]),
                    "type_ko": r["stckIssuRcdNm"], "base_date": r["basDt"], "par_value_current": r["stckParPrc"],
                }
            col = DATE_COLUMNS.get(r["rgtExertRcdNm"])
            if col and r["rgtExertSttgDt"] and (not ev.get(col) or r["rgtExertSttgDt"] < ev[col]):
                ev[col] = r["rgtExertSttgDt"]
    cols = ["code", "crno", "company", "type", "type_ko", "base_date", *DATE_COLUMNS.values(), "par_value_current"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n", restval="")
    w.writeheader()
    for ev in sorted(events.values(), key=lambda e: (e["base_date"], e["code"], e["type"])):
        w.writerow(ev)
    (root / "corporate_actions.csv").write_text(buf.getvalue(), encoding="utf-8")
    return len(events)

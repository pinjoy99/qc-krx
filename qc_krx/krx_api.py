"""Download full-market daily OHLCV from the official KRX Open API (openapi.krx.co.kr).

Needs an API key (free; apply for each service on the site) in the ``KRX_API_KEY``
environment variable. Each call returns every security of one market for one date,
including ones that later delisted, so a backfill is free of survivorship bias.
History is available from 2010-01-04 (KONEX from 2013-07-01).

Raw responses are stored losslessly (all API fields, as strings) as
``raw/krx/{MARKET}/{YYYY}/{YYYYMMDD}.csv.gz``. A non-trading day is stored as an
empty file so it isn't requested again.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import logging
import os
from pathlib import Path

from qc_krx.client import Client

log = logging.getLogger(__name__)

API_URL = "https://data-dbg.krx.co.kr/svc/apis"
# KRX's documentation publishes this key for its sample endpoint, which returns only
# the first 10 rows of a response. Used by --sample to exercise the pipeline without a key.
SAMPLE_URL = "https://data-dbg.krx.co.kr/svc/sample/apis"
SAMPLE_AUTH_KEY = "74D1B99DFBF345BBA3FB4476510A4BED4C78D13A"

ENDPOINTS = {
    "KOSPI": "sto/stk_bydd_trd",
    "KOSDAQ": "sto/ksq_bydd_trd",
    "KONEX": "sto/knx_bydd_trd",
    "ETF": "etp/etf_bydd_trd",
}
FIRST_DATE = {"KOSPI": "20100104", "KOSDAQ": "20100104", "KONEX": "20130701", "ETF": "20100104"}

KST = dt.timezone(dt.timedelta(hours=9))
# Data for a date can appear late; don't cache an empty answer for recent dates.
RECENT_DAYS = 7


class KrxApiError(Exception):
    pass


class KrxClient(Client):
    def __init__(self, auth_key: str, sample: bool = False, min_interval: float = 0.2):
        super().__init__(base_url=SAMPLE_URL if sample else API_URL, min_interval=min_interval)
        self.session.headers["AUTH_KEY"] = auth_key

    def get_day(self, market: str, date: str) -> list[dict]:
        self._throttle()
        resp = self.session.get(f"{self.base_url}/{ENDPOINTS[market]}", params={"basDd": date}, timeout=self.timeout)
        try:
            data = resp.json()
        except ValueError:
            resp.raise_for_status()
            raise KrxApiError(f"{market} {date}: non-JSON response (HTTP {resp.status_code})")
        if "OutBlock_1" not in data:
            raise KrxApiError(f"{market} {date}: {data.get('respCode')} {data.get('respMsg')}")
        return data["OutBlock_1"]


def client_from_env(sample: bool = False, min_interval: float = 0.2) -> KrxClient:
    if sample:
        return KrxClient(SAMPLE_AUTH_KEY, sample=True, min_interval=min_interval)
    key = os.environ.get("KRX_API_KEY")
    if not key:
        raise SystemExit("KRX_API_KEY is not set (get a key at https://openapi.krx.co.kr/)")
    return KrxClient(key, min_interval=min_interval)


def day_path(root: Path, market: str, date: str) -> Path:
    return root / "raw" / "krx" / market / date[:4] / f"{date}.csv.gz"


def write_day(path: Path, rows: list[dict]) -> None:
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())
    os.replace(tmp, path)


def read_day(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def weekdays(start: str, end: str):
    d = dt.datetime.strptime(start, "%Y%m%d").date()
    stop = dt.datetime.strptime(end, "%Y%m%d").date()
    while d <= stop:
        if d.weekday() < 5:
            yield d.strftime("%Y%m%d")
        d += dt.timedelta(days=1)


def scrape_krx(client: KrxClient, root: Path, start: str | None = None, end: str | None = None,
               markets: list[str] | None = None, force: bool = False) -> dict:
    """Fetch every (market, weekday) in [start, end] not already on disk.

    Stops at the first API error (e.g. an exhausted daily quota or an unapproved
    service) so a re-run resumes where it left off.
    """
    today = dt.datetime.now(KST).date()
    end = end or today.strftime("%Y%m%d")
    recent = (today - dt.timedelta(days=RECENT_DAYS)).strftime("%Y%m%d")
    stats = {"fetched": 0, "empty": 0, "skipped": 0, "rows": 0}
    for market in markets or list(ENDPOINTS):
        first = max(start or FIRST_DATE[market], FIRST_DATE[market])
        for date in weekdays(first, end):
            path = day_path(root, market, date)
            if path.exists() and not force:
                stats["skipped"] += 1
                continue
            rows = client.get_day(market, date)
            if rows or date < recent:
                write_day(path, rows)
            stats["fetched"] += 1
            stats["rows"] += len(rows)
            if not rows:
                stats["empty"] += 1
            if stats["fetched"] % 100 == 0:
                log.info("krx: %s %s (%s)", market, date, stats)
    log.info("krx: %s", stats)
    return stats

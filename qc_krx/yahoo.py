"""Yahoo Finance (via the ``yfinance`` package): the only source of minute bars, and a
cross-check for the KRX daily data.

Role in the project (see docs/AUDIT.md):

* **Minute bars** for LEAN code and strategy testing. Nothing else in the pipeline provides
  intraday data. To keep storage small, minute data is limited to a few codes (default
  DEFAULT_MINUTE_CODES, at most MAX_MINUTE_CODES) and to the last MINUTE_KEEP_DAYS days, which
  is also about all Yahoo keeps (1-minute bars for ~28 days); older files are deleted.
* **Daily bars** are downloaded only to verify the KRX Open API data (``verify`` command);
  they never go into the LEAN daily files.

What Yahoo's KRX minute bars are (measured 2026-10, see docs/AUDIT.md §3):

* 09:00-14:59 only: the last 30 minutes of the session (15:00-15:20 continuous trading and the
  15:20-15:30 closing auction) are missing, so the minute volume is ~70-85% of the day's volume
  and the last minute close is not the official close.
* Some prices are not on the KRX tick grid, so they are not all trade prices.

Yahoo has no official API. ``yfinance`` (>= 0.2.54) gets past Yahoo's bot protection by
impersonating a browser (curl_cffi); Yahoo still answers bursts with HTTP 429. So this module
sends one request at a time with a minimum interval plus random jitter, backs off on 429,
stops the run after repeated 429s or a request budget (progress is kept; re-run to resume),
and never re-requests a day already on disk.

Raw files: ``raw/yahoo/minute/{code}/{yyyyMMdd}.csv.gz`` (``time,open,high,low,close,volume``,
time = bar start HH:MM KST; an empty file marks a day Yahoo has no bars for),
``raw/yahoo/daily/{code}.csv`` and ``raw/yahoo/fetch_log.csv`` (every request, for the audit).
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import logging
import os
import random
import time
import zipfile
from pathlib import Path
from typing import Callable, Iterable

log = logging.getLogger(__name__)

KST = dt.timezone(dt.timedelta(hours=9))
# Yahoo serves 1-minute bars for the last ~30 days, at most 8 days per request (both
# measured 2026-10: 28 days back worked, 29 did not; 8-day spans worked, 9 did not).
MINUTE_LOOKBACK_DAYS = 28
MINUTE_CHUNK_DAYS = 7
# Regular session; Yahoo's bars are kept only inside it.
SESSION_START, SESSION_END = dt.time(9, 0), dt.time(15, 30)
# Minute data is kept small on purpose (storage): a few codes and a limited date range.
DEFAULT_MINUTE_CODES = ("005930", "000660", "069500")  # Samsung Electronics, SK hynix, KODEX 200
MAX_MINUTE_CODES = 20
# Days of minute files kept (raw and LEAN); older ones are deleted. Same as Yahoo's window by default.
MINUTE_KEEP_DAYS = MINUTE_LOOKBACK_DAYS
# KRX markets in the project's current scope. KOSPI stocks and ETFs both trade as .KS on Yahoo.
SUFFIX = {"KOSPI": ".KS", "ETF": ".KS"}

Bar = tuple  # (datetime KST, open, high, low, close, volume)


class YahooError(Exception):
    pass


class RateLimited(YahooError):
    """Yahoo answered 429 (too many requests)."""


class Stopped(YahooError):
    """The run stopped early (repeated rate limits or the request budget); re-run to resume."""


class Pacer:
    """One request at a time: a minimum interval with random jitter between requests,
    increasing waits after a rate limit, and a per-run request budget."""

    def __init__(self, min_interval: float = 2.0, jitter: float = 1.0, max_requests: int = 600,
                 backoff: tuple[float, ...] = (60, 180, 600), sleep: Callable[[float], None] = time.sleep):
        self.min_interval, self.jitter, self.max_requests = min_interval, jitter, max_requests
        self.backoff, self.sleep = backoff, sleep
        self.requests = 0
        self._last = 0.0

    def call(self, fn: Callable[[], object]) -> object:
        for attempt in range(len(self.backoff) + 1):
            if self.requests >= self.max_requests:
                raise Stopped(f"request budget of {self.max_requests} used up")
            wait = self._last + self.min_interval + random.uniform(0, self.jitter) - time.monotonic()
            if wait > 0:
                self.sleep(wait)
            self._last = time.monotonic()
            self.requests += 1
            try:
                return fn()
            except RateLimited:
                if attempt == len(self.backoff):
                    break
                log.warning("yahoo: rate limited; waiting %ds", self.backoff[attempt])
                self.sleep(self.backoff[attempt])
                self._last = time.monotonic()
        raise Stopped(f"rate limited {len(self.backoff) + 1} times in a row")


def yfinance_fetch(symbol: str, start: dt.date, end: dt.date, interval: str) -> list[Bar]:
    """Bars from yfinance for [start, end), unadjusted, as (datetime KST, o, h, l, c, v).
    Returns [] when Yahoo has no data; raises RateLimited on HTTP 429."""
    import yfinance as yf  # optional dependency, imported only when used

    try:  # yfinance >= 1.0 raises instead of printing when asked to
        yf.config.debug.hide_exceptions = False
        kwargs = {}
    except AttributeError:
        kwargs = {"raise_errors": True}
    try:
        df = yf.Ticker(symbol).history(start=start.isoformat(), end=end.isoformat(), interval=interval,
                                       auto_adjust=False, actions=False, prepost=False, **kwargs)
    except Exception as e:  # noqa: BLE001 - map yfinance's exception types without importing them up front
        name = type(e).__name__
        if name == "YFRateLimitError" or "Too Many Requests" in str(e):
            raise RateLimited(str(e)) from e
        if name in ("YFPricesMissingError", "YFTickerMissingError"):
            return []
        raise YahooError(f"{symbol} {interval} {start}..{end}: {name}: {e}") from e
    out = []
    for ts, r in df.iterrows():
        t = ts.to_pydatetime().astimezone(KST)
        out.append((t, r["Open"], r["High"], r["Low"], r["Close"], int(r["Volume"])))
    return out


def _num(x: float) -> str:
    """Price as written by Yahoo, without a trailing .0 for whole numbers."""
    x = round(float(x), 4)
    return str(int(x)) if x == int(x) else repr(x)


def _log_fetch(root: Path, symbol: str, interval: str, start: dt.date, end: dt.date, status: str, rows: int) -> None:
    path = root / "raw" / "yahoo" / "fetch_log.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    try:
        from importlib.metadata import version
        yf_version = version("yfinance")
    except Exception:  # noqa: BLE001
        yf_version = ""
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        if new:
            w.writerow(["fetched_at_utc", "symbol", "interval", "start", "end_exclusive", "status", "rows", "yfinance"])
        w.writerow([dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), symbol, interval,
                    start.isoformat(), end.isoformat(), status, rows, yf_version])


def minute_path(root: Path, code: str, date: str) -> Path:
    return root / "raw" / "yahoo" / "minute" / code / f"{date}.csv.gz"


def write_minute_day(path: Path, bars: list[Bar]) -> None:
    buf = io.StringIO()
    buf.write("time,open,high,low,close,volume\n")
    for t, o, h, l, c, v in bars:
        buf.write(f"{t:%H:%M},{_num(o)},{_num(h)},{_num(l)},{_num(c)},{v}\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue() if bars else "")
    os.replace(tmp, path)


def read_minute_day(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def symbol_for(code: str, market: str = "KOSPI") -> str:
    if market not in SUFFIX:
        raise YahooError(f"{code}: market {market!r} is out of scope (only {', '.join(SUFFIX)})")
    return code + SUFFIX[market]


def missing_days(root: Path, code: str, first: dt.date, last: dt.date) -> list[dt.date]:
    """Weekdays in [first, last] with no file on disk yet (holidays are learned from Yahoo
    and stored as empty files, so they are requested once)."""
    out, d = [], first
    while d <= last:
        if d.weekday() < 5 and not minute_path(root, code, d.strftime("%Y%m%d")).exists():
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def scrape_minute(root: Path, codes: Iterable[str], markets: dict[str, str] | None = None,
                  pacer: Pacer | None = None, fetch: Callable = yfinance_fetch,
                  today: dt.date | None = None) -> dict:
    """Download the 1-minute bars Yahoo still has for each code and every finished day not on
    disk. Raises Stopped (after saving what it got) when Yahoo keeps rate limiting or the
    request budget is used up."""
    codes = list(codes)
    if len(codes) > MAX_MINUTE_CODES:
        raise YahooError(f"{len(codes)} codes: minute data is limited to {MAX_MINUTE_CODES} codes")
    pacer = pacer or Pacer()
    markets = markets or {}
    today = today or dt.datetime.now(KST).date()
    first, last = today - dt.timedelta(days=MINUTE_LOOKBACK_DAYS - 1), today - dt.timedelta(days=1)
    stats = {"codes": 0, "requests": 0, "days": 0, "empty_days": 0, "failed": 0}
    for code in codes:
        stats["codes"] += 1
        symbol = symbol_for(code, markets.get(code, "KOSPI"))
        todo = missing_days(root, code, first, last)
        while todo:
            start = todo[0]
            end = min(start + dt.timedelta(days=MINUTE_CHUNK_DAYS), last + dt.timedelta(days=1))
            chunk = [d for d in todo if d < end]
            todo = [d for d in todo if d >= end]
            try:
                bars = pacer.call(lambda: fetch(symbol, start, end, "1m"))
            except YahooError as e:
                if isinstance(e, Stopped):
                    log.warning("yahoo: stopping after %d requests (%s); re-run later to resume", pacer.requests, e)
                    raise
                log.error("yahoo: %s", e)
                _log_fetch(root, symbol, "1m", start, end, "error", 0)
                stats["failed"] += 1
                continue
            stats["requests"] += 1
            _log_fetch(root, symbol, "1m", start, end, "ok", len(bars))
            by_day: dict[dt.date, list[Bar]] = {}
            for b in bars:
                if SESSION_START <= b[0].time() < SESSION_END:
                    by_day.setdefault(b[0].date(), []).append(b)
            latest = max(by_day, default=None)
            for d in chunk:
                if d in by_day:
                    write_minute_day(minute_path(root, code, d.strftime("%Y%m%d")), sorted(by_day[d]))
                    stats["days"] += 1
                elif latest is not None and d < latest:
                    # Yahoo has later bars but none for this day: a holiday or a trading halt.
                    write_minute_day(minute_path(root, code, d.strftime("%Y%m%d")), [])
                    stats["empty_days"] += 1
    log.info("yahoo minute: %(codes)d codes, %(requests)d requests, %(days)d days saved, "
             "%(empty_days)d days without bars, %(failed)d failed requests", stats)
    return stats


def prune_minute(root: Path, keep_days: int = MINUTE_KEEP_DAYS, today: dt.date | None = None) -> int:
    """Delete raw minute files older than ``keep_days`` (0 keeps everything); LEAN minute files
    follow the raw ones at the next build."""
    if keep_days <= 0:
        return 0
    today = today or dt.datetime.now(KST).date()
    cutoff = (today - dt.timedelta(days=keep_days)).strftime("%Y%m%d")
    n = 0
    for path in (root / "raw" / "yahoo" / "minute").glob("*/*.csv.gz"):
        if path.name[:8] < cutoff:
            path.unlink()
            n += 1
    if n:
        log.info("yahoo minute: deleted %d day files older than %d days", n, keep_days)
    return n


def scrape_daily(root: Path, codes: Iterable[str], start: dt.date, markets: dict[str, str] | None = None,
                 pacer: Pacer | None = None, fetch: Callable = yfinance_fetch,
                 today: dt.date | None = None) -> int:
    """Daily bars from ``start`` for verification only (raw/yahoo/daily/{code}.csv).
    Note: Yahoo's daily Open/High/Low/Close are split-adjusted even with auto_adjust=False."""
    pacer = pacer or Pacer()
    markets = markets or {}
    end = (today or dt.datetime.now(KST).date())  # exclusive: today's bar may be unfinished
    n = 0
    out_dir = root / "raw" / "yahoo" / "daily"
    out_dir.mkdir(parents=True, exist_ok=True)
    for code in codes:
        symbol = symbol_for(code, markets.get(code, "KOSPI"))
        try:
            bars = pacer.call(lambda: fetch(symbol, start, end, "1d"))
        except Stopped:
            raise
        except YahooError as e:
            log.error("yahoo: %s", e)
            _log_fetch(root, symbol, "1d", start, end, "error", 0)
            continue
        _log_fetch(root, symbol, "1d", start, end, "ok", len(bars))
        lines = ["date,open,high,low,close,volume\n"]
        lines += [f"{t:%Y%m%d},{_num(o)},{_num(h)},{_num(l)},{_num(c)},{v}\n" for t, o, h, l, c, v in bars]
        (out_dir / f"{code}.csv").write_text("".join(lines), encoding="utf-8")
        n += 1
    return n


def top_codes(root: Path, n: int, market: str = "KOSPI") -> list[str]:
    """The ``n`` largest securities by market cap in the newest raw/krx/{market} file."""
    files = sorted((root / "raw" / "krx" / market).glob("*/*.csv.gz"), key=lambda p: p.name)
    for path in reversed(files):
        with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
            rows = [r for r in csv.DictReader(f) if r.get("MKTCAP", "").replace(",", "").isdigit()]
        if rows:
            rows.sort(key=lambda r: -int(r["MKTCAP"].replace(",", "")))
            return [r["ISU_CD"] for r in rows[:n]]
    raise YahooError(f"no raw/krx/{market} data: run `krx` first or pass codes explicitly")


def known_markets(root: Path) -> dict[str, str]:
    """code -> KRX market (KOSPI/ETF/...) from the newest raw/krx file of each market."""
    out: dict[str, str] = {}
    for market_dir in (root / "raw" / "krx").glob("*"):
        files = sorted(market_dir.glob("*/*.csv.gz"), key=lambda p: p.name)
        for path in reversed(files[-10:]):
            with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
                codes = [r["ISU_CD"] for r in csv.DictReader(f)]
            if codes:
                out.update({c: market_dir.name for c in codes})
                break
    return out


def build_lean_minute(root: Path, market: str = "krx") -> int:
    """LEAN minute trade files from raw/yahoo/minute:
    ``lean/equity/{market}/minute/{code}/{yyyyMMdd}_trade.zip`` holding
    ``{yyyyMMdd}_{code}_minute_trade.csv`` with ``ms since midnight,o,h,l,c,v`` (prices x 10,000,
    times in the data time zone Asia/Seoul, bar start). Only new or changed days are rewritten;
    files whose raw day is gone (see prune_minute) are deleted."""
    src_root = root / "raw" / "yahoo" / "minute"
    lean_root = root / "lean" / "equity" / market / "minute"
    for out in lean_root.glob("*/*_trade.zip"):
        if not (src_root / out.parent.name / f"{out.name[:8]}.csv.gz").exists():
            out.unlink()
    n = 0
    for path in src_root.glob("*/*.csv.gz"):
        code, date = path.parent.name, path.name[:8]
        out = root / "lean" / "equity" / market / "minute" / code.lower() / f"{date}_trade.zip"
        if out.exists() and out.stat().st_mtime >= path.stat().st_mtime:
            continue
        rows = read_minute_day(path)
        if not rows:
            continue
        lines = []
        for r in rows:
            hh, mm = r["time"].split(":")
            ms = (int(hh) * 60 + int(mm)) * 60_000
            o, h, l, c = (round(float(r[k]) * 10000) for k in ("open", "high", "low", "close"))
            lines.append(f"{ms},{o},{h},{l},{c},{r['volume']}")
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{date}_{code.lower()}_minute_trade.csv", "\n".join(lines) + "\n")
        os.replace(tmp, out)
        n += 1
    if n:
        log.info("build: wrote %d LEAN minute files", n)
    return n

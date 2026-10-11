"""Yahoo Finance (via the ``yfinance`` package): daily bars used only to cross-check the KRX
daily data (``yahoo-daily`` then ``verify``). They never go into the LEAN files.

Minute bars were removed from the project on 2026-10-11 until a better source is available
(Yahoo's KRX minute bars stop at 14:59, have volume spikes and off-tick prices, and only cover
~28 days; see docs/AUDIT.md).

Yahoo has no official API. ``yfinance`` (>= 0.2.54) gets past Yahoo's bot protection by
impersonating a browser (curl_cffi); Yahoo still answers bursts with HTTP 429. So this module
sends one request at a time with a minimum interval plus random jitter, backs off on 429, and
stops the run after repeated 429s or a request budget.

Raw files: ``raw/yahoo/daily/{code}.csv`` and ``raw/yahoo/fetch_log.csv`` (every request, for
the audit). Note: Yahoo's daily open/high/low/close are split-adjusted even with
``auto_adjust=False``.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import logging
import random
import time
from pathlib import Path
from typing import Callable, Iterable

log = logging.getLogger(__name__)

KST = dt.timezone(dt.timedelta(hours=9))
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


def symbol_for(code: str, market: str = "KOSPI") -> str:
    if market not in SUFFIX:
        raise YahooError(f"{code}: market {market!r} is out of scope (only {', '.join(SUFFIX)})")
    return code + SUFFIX[market]


def scrape_daily(root: Path, codes: Iterable[str], start: dt.date, markets: dict[str, str] | None = None,
                 pacer: Pacer | None = None, fetch: Callable = yfinance_fetch,
                 today: dt.date | None = None) -> int:
    """Daily bars from ``start`` for verification only (raw/yahoo/daily/{code}.csv)."""
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

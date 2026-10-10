"""QuantConnect LEAN factor files and map files for KRX securities.

Factor file rows are ``yyyyMMdd,price_factor,split_factor,reference_price``. A row's factors
apply to prices on or before its date (back to the previous row); each event's row is dated
the last trading day before the event, with that day's close as the reference price, and the
file ends with ``20501231,1,1,0``.

* **Split factor** — KRX's own adjustments. KRX publishes each day's change against a base
  price that is normally the previous close; on the day of a split, reverse split, bonus or
  rights issue, capital reduction, spin-off etc. it is the *adjusted* previous close. So
  ``base / previous close`` is the exchange's adjustment ratio (e.g. Samsung's 50:1 split on
  2018-05-04: 53,000 / 2,650,000 = 0.02). Rights issues are therefore adjusted like splits.
* **Price factor** — cash dividends from ``dividends.csv``: ``1 - dividend / close`` on the
  last trading day before the ex-dividend date. KRX doesn't adjust the base price for cash
  dividends, so nothing is counted twice; a dividend whose ex-date falls on a KRX adjustment
  day is skipped to be safe. With T+2 settlement the ex-date is the trading day before the
  record date (or before the last trading day on/before it, when the record date is a holiday).

Map files are ``yyyyMMdd,ticker`` rows: the first trading date, then 20501231 — or the last
trading date for a security that stopped trading, which LEAN treats as its delisting.
KRX codes don't change with company renames, so there are no rename rows.
"""

from __future__ import annotations

import bisect
import csv
from pathlib import Path

FAR_FUTURE = "20501231"


def load_cash_dividends(root: Path) -> dict[str, list[tuple[str, float]]]:
    """code -> [(record_date, cash per share)] from dividends.csv (reported amounts only)."""
    path = root / "dividends.csv"
    out: dict[str, list[tuple[str, float]]] = {}
    if not path.exists():
        return out
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["code"] and r["cash_per_share"] and r["type"] in ("cash", "cash_and_stock"):
                out.setdefault(r["code"], []).append((r["record_date"], float(r["cash_per_share"])))
    return out


def ex_dividend_date(record_date: str, calendar: list[str]) -> str | None:
    """Trading day before the last trading day on or before the record date (T+2)."""
    i = bisect.bisect_right(calendar, record_date) - 1  # last trading day <= record date
    return calendar[i - 1] if i >= 1 else None


def _fmt(x: float) -> str:
    s = f"{x:.10f}".rstrip("0").rstrip(".")
    return s or "0"


def factor_rows(closes: list[tuple[str, int]], bases: dict[str, int],
                dividends: list[tuple[str, float]], calendar: list[str]) -> tuple[list[list[str]], list[dict]]:
    """Factor file rows for one security, plus the events used (for auditing).

    ``closes`` is [(date, raw close)] sorted by date, ``bases`` the KRX base price per date.
    """
    if not closes:
        return [], []
    index = {d: i for i, (d, _) in enumerate(closes)}
    events: dict[str, dict] = {}  # cum date -> {"split": x, "price": y, "ref": close}
    used = []
    split_days = set()
    for i in range(1, len(closes)):
        d, _ = closes[i]
        prev_d, prev_c = closes[i - 1]
        base = bases.get(d)
        if base and prev_c and base != prev_c:
            ratio = base / prev_c
            ev = events.setdefault(prev_d, {"split": 1.0, "price": 1.0, "ref": prev_c})
            ev["split"] *= ratio
            split_days.add(d)
            used.append({"type": "adjustment", "date": d, "cum_date": prev_d, "ratio": ratio})
    for record_date, amount in dividends:
        ex = ex_dividend_date(record_date, calendar)
        i = index.get(ex)
        if not i or ex in split_days:  # not traded that day, first day, or already adjusted
            continue
        prev_d, prev_c = closes[i - 1]
        if not (0 < amount < prev_c):
            continue
        factor = (prev_c - amount) / prev_c
        ev = events.setdefault(prev_d, {"split": 1.0, "price": 1.0, "ref": prev_c})
        ev["price"] *= factor
        used.append({"type": "dividend", "date": ex, "cum_date": prev_d, "ratio": factor, "amount": amount})
    if not events:
        return [], used

    rows = []
    price = split = 1.0
    for d in sorted(events, reverse=True):
        price *= events[d]["price"]
        split *= events[d]["split"]
        rows.append([d, _fmt(price), _fmt(split), str(events[d]["ref"])])
    rows.reverse()
    first = closes[0][0]
    if rows[0][0] > first:
        rows.insert(0, [first, rows[0][1], rows[0][2], "0"])
    rows.append([FAR_FUTURE, "1", "1", "0"])
    return rows, used


def map_rows(code: str, first_date: str, last_date: str, latest_date: str) -> list[list[str]]:
    ticker = code.lower()
    end = FAR_FUTURE if last_date >= latest_date else last_date
    return [[first_date, ticker], [end, ticker]]


def write_rows(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(",".join(r) + "\n" for r in rows), encoding="utf-8")

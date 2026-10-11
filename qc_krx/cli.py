"""Command line entry point: ``python -m qc_krx <command>``."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
from pathlib import Path

from qc_krx import build, dividends, krx_api, lean_install, rights, scraper, verify, yahoo
from qc_krx.client import Client


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="qc_krx", description="KRX data for QuantConnect LEAN: KOSPI stocks and ETFs from the KRX Open API "
                                "(daily) and data.go.kr, with aikstockdata.com and Yahoo Finance as cross-checks")
    p.add_argument("--root", type=Path, default=Path("data"), help="output directory (default: data)")
    p.add_argument("--interval", type=float, default=0.1, help="min seconds between requests (default: 0.1)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("universe", help="aikstockdata (check only): download the stock list")

    h = sub.add_parser("history", help="aikstockdata (check only): per-stock close/volume history (since 2020)")
    h.add_argument("codes", nargs="*", help="6-digit codes (default: whole universe)")
    h.add_argument("--workers", type=int, default=4)

    d = sub.add_parser("daily", help="aikstockdata (check only): the daily full-market OHLCV files still on the site")
    d.add_argument("--force", action="store_true", help="re-download files already on disk")

    k = sub.add_parser("krx", help="download full-market daily OHLCV from the KRX Open API (needs KRX_API_KEY)")
    k.add_argument("--start", help="first date YYYYMMDD (default: 20100104, or 20130701 for KONEX)")
    k.add_argument("--end", help="last date YYYYMMDD (default: today KST)")
    k.add_argument("--markets", default=",".join(krx_api.IN_SCOPE),
                   help=f"comma-separated, default %(default)s (in scope); also {', '.join(krx_api.ENDPOINTS)}")
    k.add_argument("--force", action="store_true", help="re-download dates already on disk")
    k.add_argument("--sample", action="store_true",
                   help="use KRX's public sample endpoint (10 rows per call, no key needed) to test the pipeline")

    x = sub.add_parser("krx-index", help="download daily index levels from the KRX Open API (needs KRX_API_KEY)")
    x.add_argument("--start", help="first date YYYYMMDD (default: 20100104)")
    x.add_argument("--end", help="last date YYYYMMDD (default: today KST)")
    x.add_argument("--series", default="KOSPI",
                   help=f"comma-separated, default %(default)s (in scope); also {', '.join(krx_api.INDEX_ENDPOINTS)}")
    x.add_argument("--force", action="store_true", help="re-download dates already on disk")

    i = sub.add_parser("krx-info", help="save a KRX security-master snapshot (ISIN, listing date, share class, par value)")
    i.add_argument("--date", help="YYYYMMDD (default: most recent date with data)")
    i.add_argument("--markets", default="KOSPI",
                   help=f"comma-separated, default %(default)s (in scope); also {', '.join(krx_api.INFO_ENDPOINTS)}")

    dv = sub.add_parser("dividends", help="download dividend history from data.go.kr (needs DATA_GO_KR_KEY)")
    dv.add_argument("--max-age-days", type=float, default=1, help="skip if the saved copy is newer (default: 1)")
    dv.add_argument("--force", action="store_true", help="download even if the saved copy is recent")
    rg = sub.add_parser("rights", help="download corporate-action schedules from data.go.kr (needs DATA_GO_KR_KEY)")
    rg.add_argument("--max-age-days", type=float, default=7, help="skip if the saved copy is newer (default: 7)")
    rg.add_argument("--force", action="store_true", help="download even if the saved copy is recent")

    y = sub.add_parser("yahoo-daily", help="daily bars from Yahoo, only to check the KRX data (`verify`)")
    y.add_argument("codes", nargs="*", help="6-digit KOSPI stock or ETF codes")
    y.add_argument("--top", type=int, default=0, help="add the N largest KOSPI stocks by market cap (needs raw/krx)")
    y.add_argument("--start", default="2020-01-01", help="first date YYYY-MM-DD (default: 2020-01-01)")
    y.add_argument("--min-interval", type=float, default=2.0, help="seconds between Yahoo requests (default: 2, plus up to 1 s jitter)")
    y.add_argument("--max-requests", type=int, default=600, help="stop after this many requests (default: 600); re-run to resume")

    sub.add_parser("verify", help="compare KRX daily data with aikstockdata / Yahoo files on disk; writes reports/")

    b = sub.add_parser("build", help="merge raw files into data/ohlcv and LEAN zips")
    b.add_argument("--no-lean", action="store_true", help="skip LEAN zip output")
    b.add_argument("--market", default="krx", help="LEAN market folder name (default: krx)")

    li = sub.add_parser("lean-install", help="copy lean/equity/krx into a LEAN Data folder and add KRX equity config")
    li.add_argument("lean_data", type=Path, help="path to LEAN's Data folder")
    li.add_argument("--market", default="krx")

    a = sub.add_parser("all", help="krx (KOSPI, ETF) + krx-index (KOSPI) + build; needs KRX_API_KEY")
    a.add_argument("--no-lean", action="store_true")
    a.add_argument("--market", default="krx")

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    client = Client(min_interval=args.interval)
    root: Path = args.root

    if args.cmd == "universe":
        scraper.fetch_universe(client, root)
    elif args.cmd == "history":
        codes = args.codes or [c for c, _, _ in _universe(client, root)]
        stats = scraper.scrape_histories(client, codes, root, workers=args.workers)
        return 1 if stats["failed"] else 0
    elif args.cmd == "daily":
        scraper.scrape_daily(client, root, force=args.force)
    elif args.cmd == "krx":
        markets = [m.strip().upper() for m in args.markets.split(",") if m.strip()]
        unknown = set(markets) - set(krx_api.ENDPOINTS)
        if unknown:
            p.error(f"unknown market(s): {', '.join(sorted(unknown))}")
        kc = krx_api.client_from_env(sample=args.sample, min_interval=max(args.interval, 0.2))
        try:
            krx_api.scrape_krx(kc, root, start=args.start, end=args.end, markets=markets, force=args.force)
        except krx_api.KrxApiError as e:
            logging.error("KRX API error, stopping (re-run to resume): %s", e)
            return 1
    elif args.cmd == "krx-index":
        series = [m.strip().upper() for m in args.series.split(",") if m.strip()]
        unknown = set(series) - set(krx_api.INDEX_ENDPOINTS)
        if unknown:
            p.error(f"unknown series: {', '.join(sorted(unknown))}")
        kc = krx_api.client_from_env(min_interval=max(args.interval, 0.2))
        try:
            krx_api.scrape_krx(kc, root, start=args.start, end=args.end, markets=series,
                               force=args.force, dataset="index")
        except krx_api.KrxApiError as e:
            logging.error("KRX API error, stopping (re-run to resume): %s", e)
            return 1
    elif args.cmd == "krx-info":
        markets = [m.strip().upper() for m in args.markets.split(",") if m.strip()]
        unknown = set(markets) - set(krx_api.INFO_ENDPOINTS)
        if unknown:
            p.error(f"unknown market(s): {', '.join(sorted(unknown))}")
        kc = krx_api.client_from_env(min_interval=max(args.interval, 0.2))
        try:
            krx_api.scrape_krx_info(kc, root, date=args.date, markets=markets)
        except krx_api.KrxApiError as e:
            logging.error("KRX API error: %s", e)
            return 1
    elif args.cmd == "dividends":
        try:
            dividends.scrape_dividends(dividends.key_from_env(), root, 0 if args.force else args.max_age_days)
        except dividends.DividendApiError as e:
            logging.error("dividend API error: %s", e)
            return 1
    elif args.cmd == "rights":
        try:
            rights.scrape_rights(dividends.key_from_env(), root, 0 if args.force else args.max_age_days)
        except rights.RightsApiError as e:
            logging.error("rights API error (re-run to resume): %s", e)
            return 1
    elif args.cmd == "build":
        build.build(root, lean=not args.no_lean, market=args.market)
    elif args.cmd == "lean-install":
        lean_install.install(root, args.lean_data, market=args.market)
    elif args.cmd == "yahoo-daily":
        codes = list(dict.fromkeys(args.codes + (yahoo.top_codes(root, args.top) if args.top else [])))
        if not codes:
            p.error("give codes and/or --top N")
        markets = yahoo.known_markets(root)
        out_of_scope = [c for c in codes if markets.get(c, "KOSPI") not in yahoo.SUFFIX]
        if out_of_scope:
            p.error(f"out of scope (only KOSPI stocks and ETFs): {', '.join(out_of_scope)}")
        pacer = yahoo.Pacer(min_interval=args.min_interval, max_requests=args.max_requests)
        try:
            yahoo.scrape_daily(root, codes, dt.date.fromisoformat(args.start), markets, pacer)
        except yahoo.Stopped:
            return 1
    elif args.cmd == "verify":
        verify.verify(root)
    elif args.cmd == "all":
        failed = False
        try:
            krx_api.scrape_krx(krx_api.client_from_env(), root, markets=list(krx_api.IN_SCOPE))
            krx_api.scrape_krx(krx_api.client_from_env(), root, markets=["KOSPI"], dataset="index")
        except krx_api.KrxApiError as e:
            logging.error("KRX API error, stopping (re-run to resume): %s", e)
            failed = True
        build.build(root, lean=not args.no_lean, market=args.market)
        return 1 if failed else 0
    return 0


def _universe(client: Client, root: Path):
    if (root / "raw" / "universe.csv").exists():
        return scraper.load_universe(root)
    return scraper.fetch_universe(client, root)

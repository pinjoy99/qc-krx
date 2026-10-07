"""Command line entry point: ``python -m qc_krx <command>``."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from qc_krx import build, krx_api, scraper
from qc_krx.client import Client


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="qc_krx", description="Scrape KRX daily data (aikstockdata.com and the KRX Open API)")
    p.add_argument("--root", type=Path, default=Path("data"), help="output directory (default: data)")
    p.add_argument("--interval", type=float, default=0.1, help="min seconds between requests (default: 0.1)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("universe", help="download the stock list")

    h = sub.add_parser("history", help="download per-stock close/volume history (since 2020)")
    h.add_argument("codes", nargs="*", help="6-digit codes (default: whole universe)")
    h.add_argument("--workers", type=int, default=4)

    d = sub.add_parser("daily", help="download the daily full-market OHLCV files still on the site")
    d.add_argument("--force", action="store_true", help="re-download files already on disk")

    k = sub.add_parser("krx", help="download full-market daily OHLCV from the KRX Open API (needs KRX_API_KEY)")
    k.add_argument("--start", help="first date YYYYMMDD (default: 20100104, or 20130701 for KONEX)")
    k.add_argument("--end", help="last date YYYYMMDD (default: today KST)")
    k.add_argument("--markets", default=",".join(krx_api.ENDPOINTS),
                   help="comma-separated subset of %(default)s")
    k.add_argument("--force", action="store_true", help="re-download dates already on disk")
    k.add_argument("--sample", action="store_true",
                   help="use KRX's public sample endpoint (10 rows per call, no key needed) to test the pipeline")

    b = sub.add_parser("build", help="merge raw files into data/ohlcv and LEAN zips")
    b.add_argument("--no-lean", action="store_true", help="skip LEAN zip output")
    b.add_argument("--market", default="krx", help="LEAN market folder name (default: krx)")

    a = sub.add_parser("all", help="universe + history + daily (+ krx if KRX_API_KEY is set) + build")
    a.add_argument("--workers", type=int, default=4)
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
    elif args.cmd == "build":
        build.build(root, lean=not args.no_lean, market=args.market)
    elif args.cmd == "all":
        codes = [c for c, _, _ in scraper.fetch_universe(client, root)]
        stats = scraper.scrape_histories(client, codes, root, workers=args.workers)
        scraper.scrape_daily(client, root)
        failed = bool(stats["failed"])
        if os.environ.get("KRX_API_KEY"):
            try:
                krx_api.scrape_krx(krx_api.client_from_env(), root)
            except krx_api.KrxApiError as e:
                logging.error("KRX API error, stopping (re-run to resume): %s", e)
                failed = True
        else:
            logging.info("KRX_API_KEY not set; skipping the KRX Open API source")
        build.build(root, lean=not args.no_lean, market=args.market)
        return 1 if failed else 0
    return 0


def _universe(client: Client, root: Path):
    if (root / "raw" / "universe.csv").exists():
        return scraper.load_universe(root)
    return scraper.fetch_universe(client, root)

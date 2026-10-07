"""Command line entry point: ``python -m qc_krx <command>``."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from qc_krx import build, scraper
from qc_krx.client import Client


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="qc_krx", description="Scrape KRX data from aikstockdata.com")
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

    b = sub.add_parser("build", help="merge raw files into data/ohlcv and LEAN zips")
    b.add_argument("--no-lean", action="store_true", help="skip LEAN zip output")
    b.add_argument("--market", default="krx", help="LEAN market folder name (default: krx)")

    a = sub.add_parser("all", help="universe + history + daily + build")
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
    elif args.cmd == "build":
        build.build(root, lean=not args.no_lean, market=args.market)
    elif args.cmd == "all":
        codes = [c for c, _, _ in scraper.fetch_universe(client, root)]
        stats = scraper.scrape_histories(client, codes, root, workers=args.workers)
        scraper.scrape_daily(client, root)
        build.build(root, lean=not args.no_lean, market=args.market)
        return 1 if stats["failed"] else 0
    return 0


def _universe(client: Client, root: Path):
    if (root / "raw" / "universe.csv").exists():
        return scraper.load_universe(root)
    return scraper.fetch_universe(client, root)

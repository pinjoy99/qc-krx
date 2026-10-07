# qc-krx

Collects Korean daily price data (KOSPI / KOSDAQ / KONEX stocks and ETFs) and converts it
to per-security OHLCV CSVs and QuantConnect LEAN daily zips. Two sources:

1. **KRX Open API** ([openapi.krx.co.kr](https://openapi.krx.co.kr/)) — official, full-market
   OHLCV for every date since 2010-01-04, including ETFs and stocks that later delisted.
   Needs a free API key. **This is the main source once you have a key.**
2. **[aikstockdata.com](https://aikstockdata.com/)** — no key needed; static JSON/CSV files
   (catalog at `https://aikstockdata.com/data/public/index.json`). Close/volume since 2020,
   full OHLCV only for the last 30 trading days. No ETFs, no delisted stocks.

## KRX Open API

| Endpoint (`https://data-dbg.krx.co.kr/svc/apis/...`) | Market | Data from |
|---|---|---|
| `sto/stk_bydd_trd` | KOSPI | 2010-01-04 |
| `sto/ksq_bydd_trd` | KOSDAQ | 2010-01-04 |
| `sto/knx_bydd_trd` | KONEX | 2013-07-01 |
| `etp/etf_bydd_trd` | ETF | 2010-01-04 |

One call returns every security in that market for one date (`basDd=YYYYMMDD`, key in the
`AUTH_KEY` header). Setup:

1. Sign up at openapi.krx.co.kr, request an API key (마이페이지 → API 인증키 신청), then apply
   for each of the four services above (서비스 이용 → 주식 / 증권상품 → API 이용신청). Approval
   can take a day.
2. Put the key in the `KRX_API_KEY` environment variable (for Claude Code cloud sessions, add it
   in the environment's settings; don't commit it).
3. Backfill, then run daily:

```bash
python -m qc_krx krx                                 # everything since 2010 (~16k calls)
python -m qc_krx krx --start 20200101 --markets KOSPI,KOSDAQ
python -m qc_krx krx --sample --start 20261001       # test without a key (10 rows per call)
```

Two more KRX datasets (each needs its own service approval):

```bash
python -m qc_krx krx-index --series KOSPI     # index levels: KRX, KOSPI, KOSDAQ series (since 2010)
python -m qc_krx krx-info --markets KOSPI     # security master snapshot: ISIN, listing date,
                                              # share class (common/preferred), par value, REIT etc.
```

Files are stored as `data/raw/krx/{MARKET}/{YYYY}/{YYYYMMDD}.csv.gz` with every API field kept
as-is. Dates already on disk are skipped; non-trading days are stored as empty files (except
in the last 7 days, which are retried). The run stops at the first API error — e.g. a daily
quota or a service you haven't been approved for yet — and a re-run resumes where it stopped.

## aikstockdata.com

| File | Contents | Depth |
|---|---|---|
| `search_index_rows.json` | code, name, market for ~2,800 stocks | current |
| `s/{code}_history.json` | date, **close, volume** per stock | since 2020-01-02 |
| `daily/quotes_YYYYMMDD.csv` | full-market **OHLCV**, change, value, shares, market cap | **last 30 trading days only** |

Prices are T+1 confirmed closes (published each trading day around 18:30 KST), raw KRW,
**not split-adjusted**. ETFs are not included (the upstream source doesn't provide them).

## Usage

```bash
pip install -r requirements.txt
python -m qc_krx all          # aikstockdata + KRX (if KRX_API_KEY is set) + build
```

Individual steps:

```bash
python -m qc_krx universe                 # data/raw/universe.csv
python -m qc_krx history 005930 000660    # specific stocks (default: whole universe)
python -m qc_krx daily                    # new daily OHLCV files not yet on disk
python -m qc_krx krx                      # KRX Open API (see above)
python -m qc_krx build [--no-lean]        # data/ohlcv/*.csv, data/lean/..., data/securities.csv
```

Re-runs are incremental: unchanged histories are skipped via ETag, and daily files already on
disk aren't re-downloaded. Without a KRX key, **run `daily` every trading day** (after ~18:30
KST): the site only keeps 30 days of OHLCV files, so that's the only way to keep real
open/high/low history from it.

## Output

```
data/raw/universe.csv
data/raw/history/{code}.csv          date,close,volume
data/raw/history_meta.json           per-code etag, as_of and split/merge "breaks"
data/raw/daily/quotes_YYYYMMDD.csv   as published
data/raw/krx/{MARKET}/{YYYY}/{YYYYMMDD}.csv.gz   KRX Open API, one market-day per file
data/ohlcv/{code}.csv                date,open,high,low,close,volume,source
data/lean/equity/krx/daily/{code}.zip
data/raw/krx_index/{SERIES}/{YYYY}/{YYYYMMDD}.csv.gz
data/raw/krx_info/{MARKET}/{YYYYMMDD}.csv.gz
data/securities.csv                  code,name,market,krx_first_date,krx_last_date,
                                     isin,name_en,listing_date,security_group,share_class,par_value
data/index/{name}.csv                date,open,high,low,close,volume,value,market_cap
data/indices.csv                     file,series,name,first_date,last_date
```

Main indices get short file names (`KOSPI`, `KOSPI200`, `KOSDAQ`, `KOSDAQ150`, `KRX300`); the
rest are `{SERIES}_{Korean name}`. The security-master columns in `securities.csv` come from the
latest `krx-info` snapshot and are blank for codes not in it (e.g. delisted ones). A change in
`par_value` between snapshots marks a stock split or reverse split.

For each date `data/ohlcv` takes the row from the best source available: `krx`, then `daily`
(both real OHLCV), then `history` (close only, so open = high = low = close). On no-trade days
both OHLCV sources report open/high/low as 0; these are replaced by the close.

In `securities.csv`, a `krx_last_date` earlier than the latest KRX date means the security
delisted (or was suspended) — use it to keep backtests free of survivorship bias.

The LEAN zips use LEAN's equity daily format (`yyyyMMdd 00:00,o,h,l,c,v`, prices × 10,000).
Map and factor files are **not** generated, and `krx` is not a built-in LEAN market, so
register the market (`Market.add("krx", <id>)`) or load the CSVs as custom data.

## Google Colab → Google Drive

`notebooks/qc_krx_colab.ipynb` runs the scraper in Colab and keeps the data in your Google Drive
(`MyDrive/qc-krx-data/`): raw downloads accumulate there between runs, and each run writes
`securities.csv`, `index/`, zipped per-security outputs and one combined CSV per year
(`combined/prices_YYYY.csv`, handy for Gemini). It needs two Colab secrets, `GITHUB_TOKEN`
(read-only access to this repo) and `KRX_API_KEY`; the steps are in the notebook.

## License of the data

The site permits non-commercial use with attribution and forbids commercial redistribution
(`https://aikstockdata.com/licenses/aiksd-public-1.1.txt`; prices also follow KOGL Type 4).
`data/` is git-ignored for this reason. Attribution:
자료: 한국주식데이터(aikstockdata.com) — 원천: 금융위원회 공공데이터포털.

## Tests

```bash
python -m unittest discover tests
```

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

## Dividends (data.go.kr)

The FSC dividend API ([금융위원회_주식배당정보](https://www.data.go.kr/data/15043284/openapi.do),
`apis.data.go.kr/1160100/GetStocDiviInfoService_V2/getDiviInfo_V2`) returns every dividend of
listed companies since the 1980s (~72k records) as one table. Put your data.go.kr service key
(the **Decoding** one) in `DATA_GO_KR_KEY`, then:

```bash
python -m qc_krx dividends     # full table, 8 calls -> data/raw/dividends/{basDt}.csv.gz
                               # (skipped if the saved copy is <1 day old; --force to refresh)
python -m qc_krx build         # also writes data/dividends.csv
```

`dividends.csv` has one row per security per dividend (`type` = cash, stock or cash_and_stock;
no-dividend records are dropped) with `record_date`, `pay_date` and `cash_per_share`.
`cash_per_share` is the reported amount only: the API's par value is today's par, so rate x par is
wrong for records before a split, and about 10-15% of cash dividends each year come with a rate
but no amount (blank here; `cash_rate_pct` and `par_value_current` are kept for reference).
Announced dividends whose amount isn't set yet also have a blank amount.

## Corporate actions (data.go.kr)

The FSC rights-schedule API ([금융위원회_주식권리일정정보](https://www.data.go.kr/data/15059609/openapi.do),
`apis.data.go.kr/1160100/GetStocRighScheService_V2/getRighExerReasSche_V2`, same `DATA_GO_KR_KEY`)
has one row per date of every corporate action since 2010 (~1.26M rows): splits, reverse splits,
bonus/rights issues, capital reductions, mergers, spin-offs, name changes, dividends, meetings.

```bash
python -m qc_krx rights        # whole table, ~126 calls (15-25 min); an interrupted run resumes
                               # (skipped if the saved copy is <7 days old; --force to refresh)
python -m qc_krx build         # also writes data/corporate_actions.csv
```

The API ignores date-range filters, so a refresh fetches the full table; that's why it's only
refreshed weekly by default. Factor files don't need it (they use KRX base prices and dividends). It has no stock code,
only the company registration number (`crno`), which is mapped to the common share's code
through the dividend table (run `dividends` first); events of companies missing from it (mostly
delisted ones) have a blank `code`. It gives dates but no ratios: get the split/issue ratio from
the change in listed shares (`LIST_SHRS`) in the KRX daily data. For splits and reverse splits the
price changes on `listing_date` (the new shares' first trading day), not `ex_date` — e.g. Samsung's
50:1 split: record date 2018-05-02, listing date 2018-05-04, when the close went 2,650,000 → 51,900
and listed shares 128,386,494 → 6,419,324,700. `corporate_actions.csv` has one row per event with `type`, `base_date`, `record_date`,
`ex_date`, `listing_date`, `issue_date`, `delivery_date`, `payment_date`, `dividend_pay_date`,
`meeting_date`.

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
data/raw/dividends/{basDt}.csv.gz    latest dividend table snapshot (all API fields)
data/dividends.csv                   code,isin,name,share_class,...,record_date,pay_date,type,cash_per_share,...
data/raw/rights/{YYYYMMDD}.csv.gz    latest corporate-action schedule snapshot (all API fields)
data/corporate_actions.csv           code,crno,company,type,type_ko,base_date,record_date,ex_date,...
data/lean/equity/krx/factor_files/{code}.csv   date,price_factor,split_factor,reference_price
data/lean/equity/krx/map_files/{code}.csv      date,ticker (first date; 20501231 or delisting date)
data/factor_events.csv               code,type,date,cum_date,ratio,amount (audit trail)
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

The LEAN zips use LEAN's equity daily format (`yyyyMMdd 00:00,o,h,l,c,v`, prices × 10,000, raw
unadjusted). `krx` is not a built-in LEAN market, so register it (`Market.add("krx", <id>)`).

### Factor and map files

`build` also writes `lean/equity/krx/factor_files/{code}.csv` and `map_files/{code}.csv` for every
security with KRX Open API data, so LEAN can adjust prices (`DataNormalizationMode.ADJUSTED`) and
knows when a security delisted. Factor rows are `date,price_factor,split_factor,reference_price`,
dated the last trading day before each event and ending with `20501231,1,1,0`.

- **Split factor**: KRX's own adjustment ratio. KRX reports each day's change against a base
  price that equals the previous close except on adjustment days (splits, reverse splits,
  bonus/rights issues, capital reductions, spin-offs), when it's the adjusted previous close, so
  `base / previous close` is the exchange's ratio — rights issues are adjusted like splits.
- **Price factor**: cash dividends from `dividends.csv`, `1 - dividend / close` before the
  ex-date (the trading day before the record date, T+2). KRX doesn't adjust for cash dividends,
  so nothing is counted twice. Run `dividends` before `build`, or the price factors stay 1.
- **Map files**: first trading date, then `20501231` — or the last trading date for a security
  that stopped trading (LEAN's delisting signal). KRX codes don't change on renames.

`factor_events.csv` lists every adjustment and dividend used, for auditing. Check on the 2010–2026
KOSPI/ETF data: on the 22k event days, moves beyond ±30% (Korea's daily limit) drop from 634 in
raw prices to 7 in adjusted prices (limit-down days, and a fund's final liquidation payout).

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

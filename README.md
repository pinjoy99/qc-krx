# qc-krx

**Documentation:** [step-by-step guide](docs/GUIDE.md) (install → data → LEAN backtest) ·
[audit record](docs/AUDIT.md) (sources, rules, verification, decisions) · [to-do list](TODO.md) ·
[project structure](docs/COMPONENTS.md) (qc-krx-data / qc-krx-market / qc-krx-broker, 한국어)

Collects Korean price data and converts it to per-security OHLCV CSVs and QuantConnect LEAN
data (daily, and minute bars for a few codes).

**Scope (current stage): KOSPI stocks and ETFs.** KOSDAQ, KONEX and the NXT alternative exchange
are not covered for now. The code for the KOSDAQ/KONEX endpoints is kept, but they are not
downloaded by default, not verified, and the defaults and checks assume KOSPI/ETF.

| Source | Role | What |
|---|---|---|
| **KRX Open API** ([openapi.krx.co.kr](https://openapi.krx.co.kr/)) | **the only source of daily bars** | official full-market OHLCV since 2010-01-04, incl. delisted securities; free key |
| **data.go.kr** (FSC) | dividends, corporate actions | factor files, `dividends.csv`, `corporate_actions.csv` |
| **Yahoo Finance** (`yfinance`) | **the only source of minute bars**; daily bars as a cross-check | 1-minute bars for the last ~4 weeks, a few codes only (storage) |
| **[aikstockdata.com](https://aikstockdata.com/)** | cross-check only | close/volume since 2020, OHLCV for the last 30 days; no key |

aikstockdata and Yahoo daily bars never go into the output; `python -m qc_krx verify` compares
them with the KRX data (see [Verification](#verification-aikstockdata-and-yahoo)).

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
   for the KOSPI and ETF services above (KOSDAQ/KONEX are out of scope for now) (서비스 이용 → 주식 / 증권상품 → API 이용신청). Approval
   can take a day.
2. Put the key in the `KRX_API_KEY` environment variable (for Claude Code cloud sessions, add it
   in the environment's settings; don't commit it).
3. Backfill, then run daily:

```bash
python -m qc_krx krx                                 # KOSPI + ETF since 2010 (~8k calls)
python -m qc_krx krx --start 20200101 --markets KOSPI
python -m qc_krx krx --sample --start 20261001       # test without a key (10 rows per call)
```

Two more KRX datasets (each needs its own service approval):

```bash
python -m qc_krx krx-index --series KOSPI     # index levels of the KOSPI series (KOSPI, KOSPI 200, ...) since 2010
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

## Minute bars (Yahoo Finance)

Yahoo is the only source of minute bars, for LEAN code and strategy tests. To keep storage
small, minute data is limited to **a few codes** (default 005930 Samsung Electronics, 000660 SK
hynix, 069500 KODEX 200; at most 20) and **the last 28 days**, which is also about all Yahoo
keeps; older files are deleted. About 5 KB per code-day, so 20 codes stay under ~3 MB.

```bash
python -m qc_krx yahoo-minute                     # default codes
python -m qc_krx yahoo-minute 005930 069500 --keep-days 28
python -m qc_krx build                            # also writes lean/equity/krx/minute/...
```

What the bars are (measured October 2026; details in `docs/AUDIT.md` §3):

- **09:00–14:59 only** (360 bars a day). The last 30 minutes (15:00–15:20 trading and the
  15:20–15:30 closing auction) are missing, so the minute volume is ~70–85% of the day's and the
  last minute close isn't the official close. Use the KRX daily bars for closes.
- Some prices are off the KRX tick grid (e.g. 264,250 for Samsung, whose tick is 500), so not
  every price is a trade price. All highs/lows lay inside KRX's daily range.
- Volume has spikes: on some days one minute bar holds 20–90% of the day's KRX volume, so the
  minute volumes can add up to more than the day's. Don't use them for volume-based logic.
- Yahoo's 5-minute and 60-minute bars also stop before 15:00, and minute data older than ~28
  days can't be fetched later. Running `yahoo-minute` weekly keeps the 28-day window gap-free;
  to build a longer history you would also need `--keep-days 0` (more storage), and it would
  still lack 15:00–15:30.
- Raw (unadjusted) prices in KST, bar start times; LEAN applies the same factor files as daily.

Yahoo has no official API and blocks bots and bursts (HTTP 429). `yfinance` >= 0.2.54 passes
the bot check by impersonating a browser; on top of that this project sends one request at a
time, 2 s apart plus up to 1 s of random jitter (`--min-interval`), waits 60/180/600 s after a
429, stops after a fourth 429 in a row or `--max-requests` (default 600), and never requests a
day already on disk. Each request is logged in `raw/yahoo/fetch_log.csv`. A stopped run keeps
what it got; run it again later.

## Verification (aikstockdata and Yahoo)

```bash
python -m qc_krx daily                            # aikstockdata: last 30 days of OHLCV
python -m qc_krx history 005930 000660            # aikstockdata: close/volume since 2020
python -m qc_krx yahoo-daily 005930 069500 --start 2020-01-01
python -m qc_krx verify                           # -> data/reports/verify_*.csv
```

`verify` compares every stock-day the other source has with KRX (`verify_summary.csv`,
`verify_mismatches.csv`) and checks each Yahoo minute day against the KRX daily bar
(`verify_minute.csv`: bars, first/last time, open = KRX open, inside KRX's range, volume ratio,
off-tick prices). Note that Yahoo's daily open/high/low/close are split-adjusted (and adjusted
for some capital changes) even with `auto_adjust=False`, so they differ from KRX's raw prices
before such events.

## aikstockdata.com (cross-check only)

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
python -m qc_krx all          # KRX (KOSPI, ETF, KOSPI indices; needs KRX_API_KEY) + build
```

Individual steps:

```bash
python -m qc_krx krx                      # KRX Open API (see above)
python -m qc_krx yahoo-minute             # minute bars (see above)
python -m qc_krx verify                   # cross-checks (see above)
python -m qc_krx build [--no-lean]        # data/ohlcv/*.csv, data/lean/..., data/securities.csv
python -m qc_krx lean-install PATH        # copy into a LEAN Data folder (see "Using the data in LEAN")
```

Re-runs are incremental: dates already on disk aren't downloaded again.

## Output

```
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
data/raw/yahoo/minute/{code}/{YYYYMMDD}.csv.gz   time,open,high,low,close,volume (empty = no bars)
data/raw/yahoo/daily/{code}.csv      Yahoo daily bars (cross-check only)
data/raw/yahoo/fetch_log.csv         every Yahoo request: time, symbol, range, status, rows
data/lean/equity/krx/minute/{code}/{YYYYMMDD}_trade.zip   LEAN minute bars
data/reports/verify_*.csv            cross-check results
data/raw/universe.csv, history/, daily/   aikstockdata files (cross-check only)
```

Main indices get short file names (`KOSPI`, `KOSPI200`, `KOSDAQ`, `KOSDAQ150`, `KRX300`); the
rest are `{SERIES}_{Korean name}`. The security-master columns in `securities.csv` come from the
latest `krx-info` snapshot and are blank for codes not in it (e.g. delisted ones). A change in
`par_value` between snapshots marks a stock split or reverse split.

`data/ohlcv` and the LEAN daily files come from the KRX Open API only (`source` = `krx`). On
no-trade days KRX reports open/high/low as 0; these are replaced by the close. Files of codes
without KRX data (left by older builds that merged aikstockdata) are deleted by `build`.

In `securities.csv`, a `krx_last_date` earlier than the latest KRX date means the security
delisted (or was suspended) — use it to keep backtests free of survivorship bias.

The LEAN zips use LEAN's equity daily format (`yyyyMMdd 00:00,o,h,l,c,v`, prices × 10,000, raw
unadjusted). Minute files use LEAN's minute trade format (`{date}_trade.zip` holding
`{date}_{code}_minute_trade.csv`, lines `ms since midnight,o,h,l,c,v`, prices × 10,000, KST).

### Using the data in LEAN

LEAN already has a `krx` market (`Market.KRX`, id 43) for KOSPI 200 futures/indices, but no
equity config for it. `lean-install` copies `lean/equity/krx` into a LEAN `Data/` folder and adds
an `Equity-krx-[*]` market-hours entry (Asia/Seoul, 09:00-15:30; holidays from LEAN's own
`Index-krx-[*]` list plus every no-trade weekday in the data) and the symbol-properties line
`krx,[*],equity,,KRW,1,1,1`. Re-running it is safe.

```bash
python -m qc_krx lean-install /path/to/Lean/Data
```

In the algorithm: `SetTimeZone("Asia/Seoul")`, `SetAccountCurrency("KRW")`,
`AddEquity("005930", Resolution.Daily, Market.KRX)`, and the KRX models from
[`examples/KrxModels.cs`](examples/KrxModels.cs): `KrxFeeModel` (commission + sell-side tax by
settlement date and market — LEAN's default fee model throws `unexpected equity Market krx`),
`KrxPriceVariationModel` (tick sizes), `KrxUniverseData` (daily market-cap universe) and
`KrxIndex.Benchmark("kospi200")`. [`examples/KrxTopMarketCapAlgorithm.cs`](examples/KrxTopMarketCapAlgorithm.cs)
is a full strategy backtest (KOSPI top 20 by market cap, 2011–2026); see `docs/GUIDE.md` 5.4.
[`examples/KrxMinuteSmokeTest.cs`](examples/KrxMinuteSmokeTest.cs) runs on the minute data
(`AddEquity(..., Resolution.Minute, Market.KRX, fillForward: false)`); see `docs/GUIDE.md` 5.5.

Tested with LEAN built from source (.NET 10, no Docker) on the 2010-2026 KOSPI/ETF data:
`examples/KrxSmokeTest.cs` sees Samsung's 50:1 split as a `SplitOccurred` event on 2018-05-04
(raw close 2,650,000 -> 51,900; adjusted 43,071 -> 42,177, the real -2.1% move), its quarterly
354-won dividends, and Woori Bank (000030) delisting on 2019-02-12 with the position closed.
LEAN's KRX holiday list contained all 248 no-trade weekdays in the data. This works with LEAN on
your own machine (source build or `lean` CLI); QuantConnect's cloud can't read a custom data
folder.

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

Yahoo Finance data is for personal, non-commercial use under Yahoo's terms; `yfinance` is not
affiliated with Yahoo. aikstockdata permits non-commercial use with attribution and forbids commercial redistribution
(`https://aikstockdata.com/licenses/aiksd-public-1.1.txt`; prices also follow KOGL Type 4).
`data/` is git-ignored for this reason. Attribution:
자료: 한국주식데이터(aikstockdata.com) — 원천: 금융위원회 공공데이터포털.

## Tests

```bash
python -m unittest discover tests
```

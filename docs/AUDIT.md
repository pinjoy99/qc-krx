# qc-krx: audit record

What was built, from which sources, with which rules, and how it was verified. Dates are when the
work was done (October 2026). Commit hashes refer to `pinjoy99/qc-krx`.

## 1. Data sources

| Source | Endpoint | Coverage | Access | Terms |
|---|---|---|---|---|
| KRX Open API — daily trading | `https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd` (KOSPI), `ksq_bydd_trd` (KOSDAQ), `knx_bydd_trd` (KONEX), `etp/etf_bydd_trd` (ETF) | Every listed security, one market per call, per date. KOSPI/KOSDAQ/ETF from 2010-01-04, KONEX from 2013-07-01 (per KRX's service catalog) | Free key, per-service approval; key in `AUTH_KEY` header; `basDd=YYYYMMDD` | KRX Open API terms (openapi.krx.co.kr → 이용약관) |
| KRX Open API — indices | `idx/krx_dd_trd`, `idx/kospi_dd_trd`, `idx/kosdaq_dd_trd` | Every index in the family, per date, from 2010-01-04 | same | same |
| KRX Open API — security master | `sto/stk_isu_base_info`, `ksq_isu_base_info`, `knx_isu_base_info` | Listed securities on a date: ISIN, listing date, share class, par value | same | same |
| data.go.kr — 금융위원회_주식배당정보 (dataset 15043284) | `https://apis.data.go.kr/1160100/GetStocDiviInfoService_V2/getDiviInfo_V2` | ~72k dividend records since 1985; one table, no date filter | Free service key (Decoding) | 공공누리 terms on the dataset page |
| data.go.kr — 금융위원회_주식권리일정정보 (dataset 15059609) | `https://apis.data.go.kr/1160100/GetStocRighScheService_V2/getRighExerReasSche_V2` | ~1.26M rows, every corporate-action date since 2010; source 한국예탁결제원; date-range filters are ignored (only exact `basDt` works) | same key | 공공누리 type 2 per the dataset page (commercial use needs a separate contract) |
| aikstockdata.com (optional) | `https://aikstockdata.com/data/public/…` (static JSON/CSV, catalog `index.json`) | ~2,800 listed stocks, close/volume since 2020, full OHLCV for the last 30 trading days; no ETFs, no delisted stocks | No key | Non-commercial with attribution, no commercial redistribution (`licenses/aiksd-public-1.1.txt`; prices also KOGL type 4) |

Sources considered and **not used**: an Apify actor (`gochujang/krx-korean-stocks`) — a paid
wrapper ($0.0003/record) around the same KRX Open API, needing your own KRX key anyway.

## 2. Pipeline and rules

All code is in `qc_krx/`. Raw downloads are stored losslessly; every output is rebuilt from raw.

### 2.1 Downloads (`krx_api.py`, `dividends.py`, `rights.py`, `scraper.py`)

- **KRX daily files**: one call per (market, weekday) → `raw/krx/{MARKET}/{YYYY}/{YYYYMMDD}.csv.gz`
  with every API field as returned (strings). Index files go to `raw/krx_index/…`, security master
  snapshots to `raw/krx_info/{MARKET}/{YYYYMMDD}.csv.gz`.
- **Skip rule**: a date already on disk is never requested again. A non-trading day is stored as
  an empty file, **except** within the last 7 days, where empty answers are not cached (KRX
  publishes a day's data the next day: 2026-10-07 was missing at 01:23 KST on 10-08 and present
  at 13:58 KST).
- **Errors**: the run stops at the first API error (bad key, unapproved service, quota) so a
  re-run resumes. HTTP 200 responses that aren't JSON (KRX error pages, seen once on 2025-09-18
  and fine on retry) are retried 3 times with backoff (commit `3d00ac5`). Keys are stripped of
  whitespace (a Colab secret carried a trailing CRLF; commit `f34202b`).
- **Rate**: at least 0.2 s between KRX calls. ~13,000 calls in one afternoon hit no quota.
- **data.go.kr**: both datasets are fetched as whole tables (10,000 rows per page). The gateway
  resets connections often (up to 4 in a row observed), so each page is retried up to 8–10 times.
  The rights table is written page by page to `raw/rights/.partial/` so an interrupted run resumes.
  Only the newest snapshot is kept. Refreshed at most daily (dividends) / weekly (rights) unless
  `--force` (commit `2e8b21a`).

### 2.2 Build (`build.py`, `factors.py`, `dividends.py`, `rights.py`)

- **OHLCV merge**, per date, best source first: KRX Open API → aikstockdata daily archive →
  aikstockdata close-only history (open = high = low = close). The `source` column records which.
  Where both KRX and aikstockdata had the same stock-day, values matched exactly (87/87 sample
  overlaps, and Samsung 2018-05-04 OHLCV identical).
- **No-trade days**: KRX reports open/high/low as 0 → replaced by the close. Rows without a close
  (e.g. ETF rows on holidays) are dropped.
- **LEAN daily zips**: `yyyyMMdd 00:00,open,high,low,close,volume`, prices × 10,000, raw.
- **Split factor** = product of KRX's own adjustment ratios. KRX reports the daily change
  (`CMPPREVDD_PRC`) against a base price; base = close − change. Base equals the previous close
  except on adjustment days (splits, reverse splits, bonus/rights issues, capital reductions,
  spin-offs), so `base / previous close` is the exchange's ratio. Rights issues are therefore
  adjusted like splits (same convention as KRX's adjusted prices).
- **Price factor** = product over cash dividends of `(close − dividend) / close`, with the close of
  the last trading day before the ex-date. **Ex-date rule (T+2)**: the trading day before the last
  trading day on or before the record date. A dividend whose ex-date is a KRX adjustment day is
  skipped (avoid double counting). KRX does not adjust the base price for cash dividends.
- **Dividend amounts**: only the reported amount (`stckGenrDvdnAmt`) is used. The API's par value
  is **today's** par, so `rate × par` is wrong before splits (e.g. 유한양행 2000: reported 750 won,
  rate 15% × today's par 1,000 = 150). Records with only a rate are left blank and not used.
- **Factor file rows**: dated the last trading day before each event (reference price = that
  close), cumulative factors, plus a first row at the first trading date and `20501231,1,1,0`.
- **Map files**: first trading date, then `20501231` — or the last trading date if the security
  stopped trading before the latest date in the data (LEAN's delisting signal).
- **Corporate actions**: rows grouped into events by (company registration number `crno`, event
  type, `basDt`); dates pivoted into columns. `crno` → stock code via the dividend table (the
  common share's ISIN), so events of companies absent from the dividend table have no code.
- **LEAN install** (`lean_install.py`): copies `equity/krx`; adds `Equity-krx-[*]` (Asia/Seoul,
  pre 08:30–09:00, market 09:00–15:30, post 15:40–18:00; holidays = LEAN's `Index-krx-[*]` list ∪
  no-trade weekdays in the data) and `krx,[*],equity,,KRW,1,1,1`.

## 3. Verification performed

| Check | Result |
|---|---|
| Unit tests (`python -m unittest discover tests`) | 21 tests pass |
| aikstockdata vs KRX overlap | identical close/volume on every overlapping stock-day checked (87/87; 90/90 history vs daily) |
| Full KRX backfill 2010-01-04 → 2026-10-06/08 | KOSPI 4,371 days (~3.8M rows), ETF 4,372 days, KOSPI index family 4,371 days (53 indices); no errors after the retry fix |
| Colab copy on Drive vs independent download here | raw files for 2026-10-01/02/05/06 byte-size identical for KOSPI and ETF |
| Samsung 50:1 split | KRX: 2018-05-04 close 2,650,000 → 51,900, listed shares 128,386,494 → 6,419,324,700 (exactly 50×); base 53,000 / 2,650,000 = 0.02 |
| Base-price adjustments vs corporate actions (KOSPI) | 1,599 adjustments; 1,064 match a nearby corporate action (rights 368, bonus 236, split 163, capital reduction 151, reverse split 72, spin-off 63…); unmatched ones are mostly preferred shares (mapping points to the common share), delisted companies and investment funds |
| Factor files, whole market | On 22,207 event days (12,530 adjustments, 9,677 dividends), moves beyond ±30% (the daily limit): **634 raw → 7 adjusted**. The 7: four limit-down days (−30%), two ~+32%, and 168490 (a resource fund paying 101 won on a 103 won price before delisting — economically correct) |
| Holidays | All 248 no-trade weekdays in the data are in LEAN's own KRX holiday list (399 dates through 2027) |
| LEAN backtest (`examples/KrxSmokeTest.cs`, LEAN built from source, commit `80e7843`, .NET SDK 10.0.401) | Split event 2018-05-04 factor 0.02; adjusted close 43,070.87 → 42,176.95 (−2.1%, the real move); raw history 2,650,000 → 51,900; Samsung dividends 354 won/quarter, Woori 650 won; Woori Bank (000030) delisted 2019-02-12 and position closed; account in KRW |

## 4. Decisions and their reasons

| Decision | Reason |
|---|---|
| Use the static JSON/CSV files of aikstockdata instead of scraping HTML | The site publishes them for reuse; robots.txt allows `/data/public/` |
| KRX Open API as the main source | Official, full OHLCV since 2010, includes ETFs and delisted securities; the plan (§9.1) names KRX as the golden source |
| Keep raw responses losslessly; rebuild everything from raw | Auditable and reproducible; fixing a rule never needs a re-download |
| Split factors from KRX base prices, not from corporate-action dates and share counts | Covers every security incl. delisted ones, uses the exchange's own ratio, no code-mapping gaps |
| Don't derive dividend amounts from rate × par | Par value in the API is today's, wrong for pre-split records |
| Refresh rights weekly, dividends daily | Both APIs only return whole tables; rights is ~126 calls (15–25 min) and not needed for factor files |
| Colab + Drive for storage | No local setup; Drive keeps data between runs; credentials stay in Colab secrets |
| Build LEAN from source for testing | The `lean` CLI's Docker image is ~40 GB; the source build is ~1–2 GB |
| Data not committed to git | Third-party data (non-commercial / 공공누리 terms); repo stays small. Data lives in Drive |

## 5. Known limitations

- KOSDAQ and KONEX prices, KOSDAQ/KONEX security info and other index families are supported by
  the code but were not downloaded (services not yet approved).
- About 13% of cash dividends since 2010 (3,358 of 25,789) have a rate but no amount; they are not
  in the price factors, so adjusted prices are slightly off around those ex-dates.
- Rights issues are adjusted like splits (KRX convention); LEAN reports them as split events.
- Corporate actions without a code: ~33% of all events, ~39% of splits (companies missing from the
  dividend table, mostly delisted). This doesn't affect factor files.
- Symbol properties use a fixed 1-won price step; real KRX tick sizes depend on price.
- LEAN's default fee model rejects KRX equities; the sample uses zero fees.
- Only a C# algorithm was tested in LEAN; Python algorithms were not.
- Colab runs take ~5 minutes, mostly reading ~13,000 small raw files over Drive.
- Data use: aikstockdata and KOGL-licensed data are non-commercial; check the terms before any
  commercial use or redistribution.

## 6. Environment used for development and tests

- Python 3.13 (works on 3.10+), only dependency `requests`.
- LEAN `QuantConnect/Lean` at commit `80e7843f645673bcbeaab963049f76f20f6785e1`, built with
  .NET SDK 10.0.401 (`dotnet build Launcher/QuantConnect.Lean.Launcher.csproj -c Release`).
- Google Colab (Python 3.13) with Google Drive for the scheduled data pipeline.

## 7. Change history

| Commit | Date | Change |
|---|---|---|
| `3c0e42b` | 2026-10-07 | aikstockdata scraper, OHLCV merge, LEAN zips |
| `613783a` | 2026-10-07 | KRX Open API price source |
| `27971db` | 2026-10-07 | KRX index levels and security master |
| `0041e1d` | 2026-10-07 | Colab notebook storing data in Google Drive |
| `3d00ac5` | 2026-10-07 | Retry non-JSON KRX responses |
| `5e7de80` | 2026-10-07 | Notebook shows command logs |
| `f34202b` | 2026-10-07 | Strip whitespace from API keys |
| `bd1057d` | 2026-10-10 | Dividend history (data.go.kr) |
| `f5d07e2` | 2026-10-10 | Corporate-action schedules (data.go.kr) |
| `3ca39cc` | 2026-10-10 | Documented split price-change date |
| `8fe4d26` | 2026-10-10 | LEAN factor and map files |
| `2e8b21a` | 2026-10-10 | Skip recent dividend/rights downloads; step timings |
| `08162f7` | 2026-10-10 | Rewrite only the current year's combined file |
| `70af60e` | 2026-10-10 | `lean-install` and tested LEAN sample algorithm |

## 8. Security note

During development the KRX key and the data.go.kr key were pasted into a chat session. They are not
in the repository or in any committed file, but they should be reissued (see `TODO.md`).

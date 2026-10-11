# qc-krx: audit record

What was built, from which sources, with which rules, and how it was verified. Dates are when the
work was done (October 2026). Commit hashes refer to `pinjoy99/qc-krx`.

## 0. Scope and source roles (decided 2026-10-11)

- **Markets: KOSPI stocks and ETFs only.** KOSDAQ, KONEX and NXT (the alternative exchange,
  since 2025-03) are **out of scope at this stage**. The KOSDAQ/KONEX endpoints and model branches
  stay in the code, but the defaults (`krx`, `krx-index`, `krx-info`, `all`, the notebook) fetch
  KOSPI/ETF only, `yahoo-*` refuses other markets, `build` warns if other markets are on disk, and
  nothing outside KOSPI/ETF is verified. NXT data is not available from any source used here.
- **Daily bars: KRX Open API only.** aikstockdata.com and Yahoo daily bars are kept as
  **cross-checks** (`verify` command), never merged into the outputs.
- **Minute bars: Yahoo Finance only**, for LEAN code and strategy testing, limited to **a few
  codes** (default 3, at most 20) and **the last 28 days** for storage. Not for research needing
  long intraday history.
- **Yahoo access** respects its bot protection and rate limits (§2.1).

## 1. Data sources

| Source | Endpoint | Coverage | Access | Terms |
|---|---|---|---|---|
| KRX Open API — daily trading | `https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd` (KOSPI), `ksq_bydd_trd` (KOSDAQ), `knx_bydd_trd` (KONEX), `etp/etf_bydd_trd` (ETF) | Every listed security, one market per call, per date. KOSPI/KOSDAQ/ETF from 2010-01-04, KONEX from 2013-07-01 (per KRX's service catalog) | Free key, per-service approval; key in `AUTH_KEY` header; `basDd=YYYYMMDD` | KRX Open API terms (openapi.krx.co.kr → 이용약관) |
| KRX Open API — indices | `idx/krx_dd_trd`, `idx/kospi_dd_trd`, `idx/kosdaq_dd_trd` | Every index in the family, per date, from 2010-01-04 | same | same |
| KRX Open API — security master | `sto/stk_isu_base_info`, `ksq_isu_base_info`, `knx_isu_base_info` | Listed securities on a date: ISIN, listing date, share class, par value | same | same |
| data.go.kr — 금융위원회_주식배당정보 (dataset 15043284) | `https://apis.data.go.kr/1160100/GetStocDiviInfoService_V2/getDiviInfo_V2` | ~72k dividend records since 1985; one table, no date filter | Free service key (Decoding) | 공공누리 terms on the dataset page |
| data.go.kr — 금융위원회_주식권리일정정보 (dataset 15059609) | `https://apis.data.go.kr/1160100/GetStocRighScheService_V2/getRighExerReasSche_V2` | ~1.26M rows, every corporate-action date since 2010; source 한국예탁결제원; date-range filters are ignored (only exact `basDt` works) | same key | 공공누리 type 2 per the dataset page (commercial use needs a separate contract) |
| Yahoo Finance via `yfinance` (minute bars; daily cross-check) | `query1/2.finance.yahoo.com/v8/finance/chart/{code}.KS` (through yfinance ≥ 0.2.54, tested 1.7.0) | 1-minute bars for the last ~28 days, at most 8 days per request; daily bars for years. KOSPI and ETFs as `.KS` | No key; unofficial; HTTP 429 on bursts | Yahoo terms: personal, non-commercial use |
| aikstockdata.com (cross-check only) | `https://aikstockdata.com/data/public/…` (static JSON/CSV, catalog `index.json`) | ~2,800 listed stocks, close/volume since 2020, full OHLCV for the last 30 trading days; no ETFs, no delisted stocks | No key | Non-commercial with attribution, no commercial redistribution (`licenses/aiksd-public-1.1.txt`; prices also KOGL type 4) |

Sources considered and **not used**: an Apify actor (`gochujang/krx-korean-stocks`) — a paid
wrapper ($0.0003/record) around the same KRX Open API, needing your own KRX key anyway.

## 2. Pipeline and rules

All code is in `qc_krx/`. Raw downloads are stored losslessly; every output is rebuilt from raw.

### 2.1 Downloads (`krx_api.py`, `dividends.py`, `rights.py`, `yahoo.py`, `scraper.py`)

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
- **Yahoo** (`yahoo.py`): one request at a time, at least 2 s apart plus 0–1 s random jitter;
  after HTTP 429 it waits 60, 180, then 600 s, and a fourth 429 in a row stops the run; a run also
  stops at `--max-requests` (600). yfinance ≥ 0.2.54 impersonates a browser TLS fingerprint
  (curl_cffi), which Yahoo requires (a plain `curl` got 429 at once). Minute bars: per code, the
  weekdays of the last 28 days not on disk, in chunks of ≤ 7 days (8 is Yahoo's maximum), only
  finished days (before today KST), only 09:00–15:30 bars. A weekday without bars before the last
  day Yahoo returned is stored as an empty file (holiday/halt) and not requested again. Raw files:
  `raw/yahoo/minute/{code}/{YYYYMMDD}.csv.gz`; every request is appended to
  `raw/yahoo/fetch_log.csv` (UTC time, symbol, interval, range, status, rows, yfinance version).
  Minute files older than `--keep-days` (28) are deleted; LEAN minute files follow at the next
  build. A full 28-day fill costs 4 requests per code; a weekly run 1–2.

### 2.2 Build (`build.py`, `factors.py`, `dividends.py`, `rights.py`)

- **OHLCV**: from the KRX Open API only (`source` = `krx`). Until 2026-10-11 aikstockdata rows
  filled dates/codes KRX didn't have; since then aikstockdata is a cross-check only, and `build`
  deletes `ohlcv/` and LEAN daily/factor/map files of codes without KRX data.
- **No-trade days**: KRX reports open/high/low as 0 → replaced by the close. Rows without a close
  (e.g. ETF rows on holidays) are dropped.
- **LEAN daily zips**: `yyyyMMdd 00:00,open,high,low,close,volume`, prices × 10,000, raw.
- **LEAN minute zips** (`yahoo.build_lean_minute`): `minute/{code}/{yyyyMMdd}_trade.zip` with
  `{yyyyMMdd}_{code}_minute_trade.csv`, lines `ms since midnight,o,h,l,c,v`, prices × 10,000,
  bar start time in KST (the `Equity-krx` data time zone), raw. Only new/changed days rewritten.
- **Cross-checks** (`verify.py`): every stock-day in aikstockdata (daily archive, history) and
  Yahoo daily files is compared field by field with KRX; every Yahoo minute day is compared with
  the KRX daily bar (open, high/low range, volume, last close, tick grid). → `reports/verify_*.csv`.
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

### 2.3 KRX reality models (`examples/KrxModels.cs`)

**Sell-side tax** (`KrxFeeModel`), by **settlement date** (T+2; the basis the law uses — e.g. the
2025 cut applied to trades from 2024-12-27, settling 2025-01-02). Totals include 농어촌특별세 0.15%
on KOSPI; KOSDAQ/KONEX have no 농특세; ETFs are exempt.

| From (settlement) | KOSPI (거래세 + 농특세) | KOSDAQ | KONEX |
|---|---|---|---|
| before 2019-06-03 | 0.15% + 0.15% = 0.30% | 0.30% | 0.30% |
| 2019-06-03 | 0.10% + 0.15% = 0.25% | 0.25% | 0.10% |
| 2021-01-01 | 0.08% + 0.15% = 0.23% | 0.23% | 0.10% |
| 2023-01-01 | 0.05% + 0.15% = 0.20% | 0.20% | 0.10% |
| 2024-01-01 | 0.03% + 0.15% = 0.18% | 0.18% | 0.10% |
| 2025-01-01 | 0.00% + 0.15% = 0.15% | 0.15% | 0.10% |
| 2026-01-01 | 0.05% + 0.15% = 0.20% | 0.20% | 0.10% |

Sources (news and broker notices, cross-checked): 2019 cut — 시사저널e / 서울신문 / 이투데이
(2019-05); 2021 — 한국세정신문 ("코스피 0.08%, 코스닥 0.23%"); 2023–2025 — 헤럴드경제, 대신증권 /
KB증권 notices; 2026 — 머니투데이, 한국세정신문 (2025-12). Commission: 0.015% per side by default
(account-specific, a constructor argument). Fees and taxes are truncated to whole won.

**Tick sizes** (`KrxPriceVariationModel`). From 2023-01-25, one table for KOSPI/KOSDAQ/KONEX:
<2,000 → 1; <5,000 → 5; <20,000 → 10; <50,000 → 50; <200,000 → 100; <500,000 → 500; else 1,000.
Before (introduced October 2010), KOSPI: <1,000 → 1; <5,000 → 5; <10,000 → 10; <50,000 → 50;
<100,000 → 100; <500,000 → 500; else 1,000 (verified from news/dictionary sources). KOSDAQ/KONEX
before 2023: same up to 50,000, then 100 — **not verified from a primary source**. ETFs: 5 won
(unchanged in 2023 per the exchange notice). The table used for January–October 2010 is the
post-October-2010 one — **not verified for that period**.

**Universe** (`KrxUniverseData`, `lean/equity/krx/universe/yyyyMMdd.zip`): every security with
a close that day, with KRX's own market cap (`MKTCAP`), trading value and listed shares.

**Benchmark** (`KrxIndex`): LEAN subscribes a security benchmark at hourly resolution; with daily
index data that benchmark was empty (first run: alpha 0, beta 0, tracking error = volatility).
`KrxIndex.Benchmark` passes the daily KOSPI 200 close as a benchmark function instead.

## 3. Verification performed

| Check | Result |
|---|---|
| Unit tests (`python -m unittest discover tests`) | 29 tests pass |
| aikstockdata vs KRX overlap | identical close/volume on every overlapping stock-day checked (87/87; 90/90 history vs daily). `verify` 2026-10-11, daily archive 2026-08-27 → 2026-10-07: **21,972 of 21,972 KOSPI stock-days identical** in all five fields (5,212 rows not in KRX: KOSDAQ, out of scope) |
| Yahoo daily vs KRX (`verify`, 12 codes, 2026-09-01 → 2026-10-07) | 281 of 288 stock-days identical. 6 differ: 207940 before an adjustment event, Yahoo prices × 0.99326 and volume × 1.00678 (Yahoo back-adjusts; KRX is raw). 1: 069500 volume 26.5M vs 28.2M on 2026-09-15 |
| Yahoo minute bars vs KRX (`verify`, 12 codes, 168 code-days with KRX data, 2026-09-15 → 2026-10-07) | 357–360 bars a day, **always 09:00–14:59** (no 15:00–15:30, no closing auction); first open = KRX open on 141/168; all highs/lows inside KRX's range on 168/168 (equal on 145); last minute close = KRX close on 17/168; minute volume / KRX volume median 0.80 (10%–90%: 0.67–0.88, but 0.15–2.41 overall, 8 days > 1). The days above 1 come from **single-bar volume spikes**: 8 code-days have one minute bar holding 20–90% of the day's KRX volume (340–610× the median bar), e.g. 069500 2026-09-23 (90%), 009150 2026-09-22 (89%) — `max_bar_volume_ratio` in `verify_minute.csv`; 5.6% of prices off the KRX tick grid (Samsung 26%: e.g. 264,250 with a 500 tick) |
| LEAN minute test (`examples/KrxMinuteSmokeTest.cs`, 005930 + 069500, 2026-09-15 → 2026-10-08) | 15 days × 360 bars 09:00–14:59 with `fillForward: false` (with fill-forward LEAN shows 390, repeating 14:59 until 15:29); 60 orders filled at 09:30/14:30; sell fee on 179 × 247,500 = ₩95,250 (0.015% + 0.20% tax), ETF sell commission only |
| Full KRX backfill 2010-01-04 → 2026-10-06/08 | KOSPI 4,371 days (~3.8M rows), ETF 4,372 days, KOSPI index family 4,371 days (53 indices); no errors after the retry fix |
| Colab copy on Drive vs independent download here | raw files for 2026-10-01/02/05/06 byte-size identical for KOSPI and ETF |
| Samsung 50:1 split | KRX: 2018-05-04 close 2,650,000 → 51,900, listed shares 128,386,494 → 6,419,324,700 (exactly 50×); base 53,000 / 2,650,000 = 0.02 |
| Base-price adjustments vs corporate actions (KOSPI) | 1,599 adjustments; 1,064 match a nearby corporate action (rights 368, bonus 236, split 163, capital reduction 151, reverse split 72, spin-off 63…); unmatched ones are mostly preferred shares (mapping points to the common share), delisted companies and investment funds |
| Factor files, whole market | On 22,207 event days (12,530 adjustments, 9,677 dividends), moves beyond ±30% (the daily limit): **634 raw → 7 adjusted**. The 7: four limit-down days (−30%), two ~+32%, and 168490 (a resource fund paying 101 won on a 103 won price before delisting — economically correct) |
| Holidays | All 248 no-trade weekdays in the data are in LEAN's own KRX holiday list (399 dates through 2027) |
| Model self-checks (logged by `KrxTopMarketCapAlgorithm`) | tax KOSPI 2018-06-01 0.30%, 2019-06-03 0.25%, 2025-01-02 0.15%, 2026-01-02 0.20%, KONEX 2020 0.10%, ETF 0; tick 150,000 won: 500 (2022 KOSPI) → 100 (2023), 100 (2022 KOSDAQ); 1,500 won 2023: 1; ETF 5 |
| Strategy backtest (`examples/KrxTopMarketCapAlgorithm.cs`: KOSPI top 20 by market cap, equal weight, monthly, 2011-01-01 → 2026-09-30, ₩1B, KRX fees/taxes) | CAGR 5.89%, net profit 146.6%, max drawdown 40.8%, Sharpe 0.197, beta 0.821 / alpha −0.016 / information ratio −0.339 / tracking error 0.079 vs KOSPI 200, 2,437 orders, fees ₩44.7M; runtime ~34 s |
| Independent replication of that strategy in Python (`replicate` script in the session; same selection, adjusted close-to-close monthly returns incl. dividends, no fees, fully invested) | CAGR 6.36%, month-end max drawdown 37.8% — consistent with LEAN after fees, the 1% cash buffer and next-day execution. KOSPI 200 price index over the same period: 273.81 → 1,081.82, CAGR 9.09% (excluding dividends) |
| LEAN backtest (`examples/KrxSmokeTest.cs`, LEAN built from source, commit `80e7843`, .NET SDK 10.0.401) | Split event 2018-05-04 factor 0.02; adjusted close 43,070.87 → 42,176.95 (−2.1%, the real move); raw history 2,650,000 → 51,900; Samsung dividends 354 won/quarter, Woori 650 won; Woori Bank (000030) delisted 2019-02-12 and position closed; account in KRW |

## 4. Decisions and their reasons

| Decision | Reason |
|---|---|
| Use the static JSON/CSV files of aikstockdata instead of scraping HTML | The site publishes them for reuse; robots.txt allows `/data/public/` |
| Scope KOSPI + ETF; KOSDAQ, KONEX, NXT later (2026-10-11) | Focus; KOSDAQ/KONEX KRX services not approved; no NXT source |
| KRX the only daily source; aikstockdata and Yahoo only cross-check it (2026-10-11) | One official, auditable source; aikstockdata has no ETFs/delisted stocks and only close before the last 30 days; Yahoo back-adjusts prices and drops delisted stocks |
| Yahoo the only minute source, few codes, 28 days (2026-10-11) | No free official KRX minute data; storage; Yahoo only keeps ~28 days anyway |
| Minute bars from 14:59 are not padded or synthesized | No real data for 15:00–15:30; fabricating bars (e.g. from the KRX close) would hide the gap |
| KRX Open API as the main source | Official, full OHLCV since 2010, includes ETFs and delisted securities; the plan (§9.1) names KRX as the golden source |
| Keep raw responses losslessly; rebuild everything from raw | Auditable and reproducible; fixing a rule never needs a re-download |
| Split factors from KRX base prices, not from corporate-action dates and share counts | Covers every security incl. delisted ones, uses the exchange's own ratio, no code-mapping gaps |
| Don't derive dividend amounts from rate × par | Par value in the API is today's, wrong for pre-split records |
| Refresh rights weekly, dividends daily | Both APIs only return whole tables; rights is ~126 calls (15–25 min) and not needed for factor files |
| Colab + Drive for storage | No local setup; Drive keeps data between runs; credentials stay in Colab secrets |
| Build LEAN from source for testing | The `lean` CLI's Docker image is ~40 GB; the source build is ~1–2 GB |
| Data not committed to git | Third-party data (non-commercial / 공공누리 terms); repo stays small. Data lives in Drive |

## 5. Known limitations

- Out of scope for now: KOSDAQ, KONEX and NXT. KOSDAQ/KONEX prices, security info and other
  index families are supported by the code but not downloaded or verified.
- Minute bars (Yahoo): 09:00–14:59 only — the last 20 minutes of continuous trading (15:00–15:20)
  and the closing auction (15:20–15:30) are missing, so the 14:59 close is neither the official
  close nor the pre-auction price. Yahoo's 5-minute (~90 days) and 60-minute (~3 years) bars stop
  before 15:00 too (last bars 14:55 / 14:00, checked 2026-10-11), so a coarser interval doesn't
  help. Volume not reliable (median 80% of KRX's; single-bar spikes up to 90% of the day's
  volume), some prices off the tick grid (cause unknown), only the last 28 days and a few codes. Fine for testing LEAN code and intraday logic, not for research on
  closes, volume or long histories.
- About 13% of cash dividends since 2010 (3,358 of 25,789) have a rate but no amount; they are not
  in the price factors, so adjusted prices are slightly off around those ex-dates.
- Rights issues are adjusted like splits (KRX convention); LEAN reports them as split events.
- Corporate actions without a code: ~33% of all events, ~39% of splits (companies missing from the
  dividend table, mostly delisted). This doesn't affect factor files.
- Symbol properties use a fixed 1-won price step; real KRX tick sizes depend on price.
- LEAN's default fee model rejects KRX equities; use `KrxFeeModel` (the smoke test uses zero fees).
- LEAN's "Estimated Strategy Capacity" shows ₩0 for KRX backtests (not investigated).
- The strategy example treats codes ending in "0" as common shares (KRX convention) and has no
  slippage model; universe selection uses the previous trading day's data.
- Only a C# algorithm was tested in LEAN; Python algorithms were not.
- Colab runs take ~5 minutes, mostly reading ~13,000 small raw files over Drive.
- Data use: aikstockdata and KOGL-licensed data are non-commercial; check the terms before any
  commercial use or redistribution.

## 6. Environment used for development and tests

- Python 3.13 (works on 3.10+), dependencies `requests` and `yfinance` (tested 1.7.0, curl_cffi 0.16.3).
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
| `9d2337c` | 2026-10-10 | Step-by-step guide, audit record, to-do list |
| `58f9804` | 2026-10-11 | KRX fee/tax and tick models, KOSPI 200 benchmark, daily universe files, first strategy backtest |
| `ced8ab5` | 2026-10-11 | Three-part project structure (`docs/COMPONENTS.md`) |
| `baafa70` | 2026-10-11 | Scope KOSPI + ETF; KRX-only daily data; Yahoo minute bars (few codes, 28 days, rate limiting); `verify` cross-checks with aikstockdata and Yahoo; LEAN minute smoke test |

## 8. Security note

During development the KRX key and the data.go.kr key were pasted into a chat session. They are not
in the repository or in any committed file, but they should be reissued (see `TODO.md`).

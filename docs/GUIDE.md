# qc-krx: step-by-step guide

This guide takes you from nothing to a working QuantConnect LEAN backtest on Korean stock data.
It assumes no prior setup. Every command can be copied as-is; replace anything in `<angle brackets>`.

There are two ways to run the data pipeline:

- **Path A — Google Colab + Google Drive** (no installation on your computer; data lives in Drive).
- **Path B — your own computer** (Linux, macOS or Windows with Python).

Backtesting (Part 5) always runs on your own computer, because QuantConnect's cloud cannot read a
custom data folder.

---

## Part 1 — What you are building

```
 KRX Open API ──────┐   daily prices of every KOSPI / KOSDAQ / KONEX stock and ETF since 2010,
                    │   index levels, security master
 data.go.kr ────────┤   dividend history (since 1980s), corporate-action schedules (since 2010)
                    │
 aikstockdata.com ──┘   optional backup source, no key needed
          │
          ▼  python -m qc_krx <download commands>      → data/raw/   (kept forever, the source of truth)
          ▼  python -m qc_krx build                    → data/ohlcv, data/lean, CSV summaries
          ▼  python -m qc_krx lean-install <Lean/Data> → LEAN can backtest KRX stocks
```

What you get at the end:

| Output | What it is |
|---|---|
| `data/lean/equity/krx/daily/*.zip` | Daily prices in LEAN's format (raw, unadjusted) |
| `data/lean/equity/krx/factor_files/*.csv` | Split and dividend adjustment factors for LEAN |
| `data/lean/equity/krx/map_files/*.csv` | First trading day and delisting day for LEAN |
| `data/ohlcv/*.csv` | Plain daily open/high/low/close/volume, one file per security |
| `data/securities.csv` | Every security, its listing span, ISIN, share class, par value |
| `data/index/*.csv`, `data/indices.csv` | Index levels (KOSPI, KOSPI 200, sector indices…) |
| `data/dividends.csv` | One row per dividend |
| `data/corporate_actions.csv` | One row per corporate action (splits, rights issues, mergers…) |
| `data/factor_events.csv` | Audit trail: every adjustment used in the factor files |

---

## Part 2 — Accounts and API keys (one-time, 1–2 days because of approvals)

You need three things. None of them costs money.

### 2.1 KRX Open API key (required)

1. Go to <https://openapi.krx.co.kr/> and click **회원가입** (sign up). Create an account.
2. Log in. Go to **마이페이지 → API 인증키 신청** and request an API key.
   The key is a 40-character string of letters and digits.
3. Apply for each service you want. Go to **서비스 이용**, open the category, open the service,
   click **API 이용신청**, choose the period **12M** (so it doesn't expire mid-backfill).

   | Category | Service (Korean name) | What it gives | Used by command |
   |---|---|---|---|
   | 주식 | 유가증권 일별매매정보 | KOSPI daily prices | `krx --markets KOSPI` |
   | 주식 | 코스닥 일별매매정보 | KOSDAQ daily prices | `krx --markets KOSDAQ` |
   | 주식 | 코넥스 일별매매정보 | KONEX daily prices | `krx --markets KONEX` |
   | 증권상품 | ETF 일별매매정보 | ETF daily prices | `krx --markets ETF` |
   | 지수 | KOSPI 시리즈 일별시세정보 | KOSPI index family | `krx-index --series KOSPI` |
   | 지수 | KOSDAQ 시리즈 / KRX 시리즈 일별시세정보 | other index families | `krx-index --series KOSDAQ,KRX` |
   | 주식 | 유가증권 / 코스닥 / 코넥스 종목기본정보 | ISIN, listing date, share class, par value | `krx-info` |

4. Approval usually takes up to a day. Check under **마이페이지 → 이용현황**.

How to tell what's wrong if a call fails:
- `401 Unauthorized Key` — the key itself is wrong (typo, extra space).
- `401 Unauthorized API Call` — the key is fine but that service isn't approved yet.

### 2.2 data.go.kr service key (needed for dividends and adjustment of dividends)

1. Go to <https://www.data.go.kr/> and sign up / log in.
2. Open each dataset page and click **활용신청** (apply). Approval is usually automatic.
   - 금융위원회_주식배당정보 (dividends): <https://www.data.go.kr/data/15043284/openapi.do>
   - 금융위원회_주식권리일정정보 (corporate-action schedules): <https://www.data.go.kr/data/15059609/openapi.do>
3. Go to **마이페이지 → 데이터활용 → Open API → 활용신청 현황**, open the dataset, and copy the
   **일반 인증키 (Decoding)** key. One key works for both datasets.
   A new key can take about an hour before it starts working.

### 2.3 GitHub access token (only for Path A, Colab)

The code lives in the private repository `pinjoy99/qc-krx`. Colab needs a token to download it.

1. On github.com go to **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. Repository access: **Only select repositories** → `pinjoy99/qc-krx`.
3. Permissions: **Contents: Read-only**. Nothing else.
4. Copy the token (starts with `github_pat_`).

### 2.4 Keeping keys safe

- Never paste keys into code, notebooks, commit messages or chat. Use the secret stores below.
- If a key has been exposed, reissue it on the site where you got it (see the to-do list).

---

## Part 3A — Run the pipeline in Google Colab (recommended)

1. **Open the notebook.** In Colab: **File → Open notebook → GitHub** tab, tick
   **Include private repos**, choose `pinjoy99/qc-krx`, open `notebooks/qc_krx_colab.ipynb`.
   (Then **File → Save a copy in Drive** if you want your own copy.)
2. **Add secrets.** Click the key icon (🔑 *Secrets*) in the left sidebar and add:

   | Name | Value |
   |---|---|
   | `GITHUB_TOKEN` | the token from 2.3 |
   | `KRX_API_KEY` | the key from 2.1 |
   | `DATA_GO_KR_KEY` | the Decoding key from 2.2 (optional, but needed for dividends) |

   Turn on **Notebook access** for each one. Type or paste only the key itself — no spaces or
   line breaks (the code strips them anyway).
3. **Check the settings cell (step 1 of the notebook).** List only services that are approved:
   ```python
   KRX_MARKETS = ["KOSPI", "ETF"]      # add "KOSDAQ", "KONEX" once approved
   KRX_INDEX_SERIES = ["KOSPI"]
   KRX_INFO_MARKETS = ["KOSPI"]
   KRX_START = None                    # None = from 2010-01-04
   ```
4. **Run it:** **Runtime → Run all**. Allow Drive access when asked.
5. **Expect:**
   - First run: about 1 hour per market (one KRX call per trading day since 2010), plus
     15–25 minutes for corporate actions. If anything stops it, run the notebook again — it
     resumes where it stopped.
   - Later runs: about 5 minutes. Only new days are downloaded; dividends are refreshed at most
     daily and corporate actions at most weekly.
   - Each step prints its duration, e.g. `(11s)`.
6. **Results** appear in **My Drive → qc-krx-data/**:
   `raw/` (the downloads — don't delete), `securities.csv`, `indices.csv`, `index/`,
   `dividends.csv`, `corporate_actions.csv`, `factor_events.csv`, `combined/prices_YYYY.csv`
   (all securities, one file per year — good for Gemini or spreadsheets), `ohlcv.zip`, `lean.zip`.
7. **Daily updates:** run the notebook again to add new trading days. KRX publishes a day's data
   the next day (observed: not yet available just after midnight KST, available by early
   afternoon KST), so run it in the afternoon. Empty answers for the past week are rechecked
   automatically, so an early run is harmless.
8. **After adding a market** (e.g. KOSDAQ approved later): add it to `KRX_MARKETS`, set
   `REWRITE_ALL_YEARS = True` for one run so the combined yearly files include it.

---

## Part 3B — Run the pipeline on your own computer

1. **Install Python 3.10 or newer** (<https://www.python.org/downloads/>) and **git**
   (<https://git-scm.com/downloads>).
2. **Get the code** (you need access to the private repository):
   ```bash
   git clone https://github.com/pinjoy99/qc-krx.git
   cd qc-krx
   pip install -r requirements.txt          # only "requests"
   python -m unittest discover tests        # should print "OK"
   ```
3. **Set your keys for this terminal session**
   (macOS/Linux; on Windows PowerShell use `$env:KRX_API_KEY="<key>"`):
   ```bash
   export KRX_API_KEY=<your KRX key>
   export DATA_GO_KR_KEY=<your data.go.kr Decoding key>
   ```
4. **Download.** Each command is safe to re-run; it skips what is already on disk.
   ```bash
   python -m qc_krx krx --markets KOSPI,ETF        # prices, ~1 hour per market the first time
   python -m qc_krx krx-index --series KOSPI       # index levels
   python -m qc_krx krx-info --markets KOSPI       # security master snapshot
   python -m qc_krx dividends                      # dividends (needed for dividend adjustment)
   python -m qc_krx rights                         # corporate actions (15-25 min, weekly)
   ```
   Test without a KRX key (10 rows per call from KRX's public sample service):
   `python -m qc_krx krx --sample --start 20261001`.
5. **Build all outputs** (about 2 minutes for 16 years of KOSPI + ETF):
   ```bash
   python -m qc_krx build
   ```
6. Everything is written under `data/` (change with `--root <folder>` before the command name,
   e.g. `python -m qc_krx --root /mnt/big/krx build`).
7. **Daily updates:** re-run steps 4 and 5. A scheduler (cron, Task Scheduler) can do it every
   weekday morning.

---

## Part 4 — Check the data before using it

Quick sanity checks (all of these were done during development; see `docs/AUDIT.md`):

1. `python -m unittest discover tests` prints `OK`.
2. `data/securities.csv`: the number of securities and the last date look right
   (`krx_last_date` of active stocks = the latest trading day).
3. Samsung Electronics, `data/ohlcv/005930.csv`: the close on 2018-05-03 is 2,650,000 and on
   2018-05-04 is 51,900 (the 50:1 split).
4. `data/lean/equity/krx/factor_files/005930.csv` has a row `20180503,…,0.02,2650000`.
5. `data/factor_events.csv`: scan for unusual ratios (very small or very large) and check them.

---

## Part 5 — Backtest with LEAN on your own computer

LEAN is QuantConnect's open-source engine. You can install it with Docker (the `lean` CLI, a
~40 GB image) or build it from source with .NET (~1–2 GB). The source build is described here;
it is what was tested.

### 5.1 Install .NET and build LEAN (once, ~10 minutes)

1. Install the **.NET 10 SDK**: <https://dotnet.microsoft.com/download> (or on Linux/macOS:
   `curl -sSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel 10.0` and add
   `~/.dotnet` to your `PATH`). Check: `dotnet --list-sdks` shows `10.0.x`.
2. Get and build LEAN:
   ```bash
   git clone --depth 1 https://github.com/QuantConnect/Lean.git
   cd Lean
   dotnet build Launcher/QuantConnect.Lean.Launcher.csproj -c Release
   ```
   "Build succeeded" with many warnings is normal. (Tested with LEAN commit `80e7843`.)

### 5.2 Put the KRX data into LEAN

1. Get the built data:
   - Path A: download `lean.zip` from Drive (`qc-krx-data/lean.zip`) and unzip it. It contains
     `lean/equity/krx/…`. To use `lean-install` you need it under a qc-krx data root: create a
     folder `krxdata` and unzip so that you have `krxdata/lean/equity/krx/daily/…`. Also copy
     Drive's `qc-krx-data/raw/krx` to `krxdata/raw/krx` if you want holidays checked against the
     data (optional — LEAN's own holiday list is used either way).
   - Path B: your `data/` folder already has this layout.
2. Install it into LEAN (from the qc-krx folder):
   ```bash
   python -m qc_krx --root <data or krxdata> lean-install <path to Lean>/Data
   ```
   This copies the prices, factor files and map files into `Lean/Data/equity/krx/`, adds the
   `Equity-krx-[*]` entry to `Data/market-hours/market-hours-database.json` (Seoul time,
   09:00–15:30, KRX holidays), and adds `krx,[*],equity,,KRW,1,1,1` to
   `Data/symbol-properties/symbol-properties-database.csv`. Running it again is safe.
   **Re-run it after every data update.**

### 5.3 Run the sample backtest

1. Copy the example algorithm into LEAN and rebuild:
   ```bash
   cp <qc-krx>/examples/KrxSmokeTest.cs <Lean>/Algorithm.CSharp/
   cd <Lean>
   dotnet build Launcher/QuantConnect.Lean.Launcher.csproj -c Release
   ```
2. Run it:
   ```bash
   cd Launcher/bin/Release
   dotnet QuantConnect.Lean.Launcher.dll --algorithm-type-name KrxSmokeTest \
     --algorithm-language CSharp --algorithm-location QuantConnect.Algorithm.CSharp.dll \
     --data-folder <Lean>/Data/ --close-automatically true
   ```
3. Expected log lines (search for them):
   ```
   SPLIT 2018-05-04 005930 factor=0.02 type=SplitOccurred
   ADJ 2018-05-03 close=43070.87…    ADJ 2018-05-04 close=42176.95…
   DIVIDEND … 005930 amount=354.00
   DELISTING 2019-02-13 000030 type=Delisted
   RAW 2018-05-03 close=2650000      RAW 2018-05-04 close=51900
   END value=95,409,943 KRW holdings: 005930=1188
   ```

### 5.4 Writing your own algorithm — required settings

```csharp
SetTimeZone("Asia/Seoul");
SetAccountCurrency("KRW");
SetCash(100_000_000);
var samsung = AddEquity("005930", Resolution.Daily, Market.KRX).Symbol;
// LEAN's default fee model throws "unexpected equity Market krx" on the first order.
// Until a KRX fee model exists (see TODO.md), set one explicitly, e.g.:
SetSecurityInitializer(s => s.SetFeeModel(new ConstantFeeModel(0, "KRW")));
SetBenchmark(samsung);   // the default benchmark (SPY) needs US data
```

- Tickers are 6-character KRX short codes (`005930`); some newer codes contain letters (`0052D0`).
- Prices are adjusted by default (`DataNormalizationMode.Adjusted`): splits, bonus/rights issues,
  capital reductions and cash dividends. Use `DataNormalizationMode.Raw` for exchange prices.
- Delisted stocks are included and are delisted by LEAN on their last trading day, so
  backtests are free of survivorship bias.
- Python algorithms use the same data and settings, but LEAN's Python setup was not tested here.

---

## Part 6 — Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `401 Unauthorized Key` | KRX key wrong | Re-enter the key, no spaces |
| `401 Unauthorized API Call` | KRX service not approved | Apply / wait for approval (2.1) |
| `Invalid … header value: '…\r\n'` | key saved with a line break (old version) | Update the code; keys are now stripped |
| `SERVICE_KEY_IS_NOT_REGISTERED_ERROR` | data.go.kr key not active yet / wrong key | Use the Decoding key; wait ~1 hour after approval |
| `Connection reset by peer` in logs | data.go.kr gateway is flaky | Nothing — retried automatically; re-run if it stops |
| `non-JSON response (HTTP 200)` | KRX briefly returned an error page | Retried automatically; re-run if it stops |
| Notebook says "exit code 1" | an API error | Read the lines above it; re-run to resume |
| Recent date downloaded as empty | KRX publishes the next day / holiday | Automatically retried for 7 days |
| LEAN: `unexpected equity Market krx` | default fee model | Set a fee model (5.4) |
| LEAN: market hours not found for `Equity-krx` | `lean-install` not run on this Data folder | Run `lean-install` |
| Colab run slow (~4 min build) | Drive is slow with many small files | Expected; see TODO.md |

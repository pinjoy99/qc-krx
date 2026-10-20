# qc-krx expert guide: local pipeline + local LEAN build (C# and Python)

For quants and engineers who want the whole chain on their own machine, with no Colab, no
Docker and no LEAN CLI (which needs a paid-tier QuantConnect organization; everything here is free):

```
KRX Open API ─┐                                            ┌─▶ C# algorithms  (Algorithm.CSharp)
data.go.kr ───┼─▶ qc_krx (raw/ → build) ─▶ lean-install ─▶ LEAN (source build, .NET 10)
aikstockdata ─┤      verify → reports/                     └─▶ Python algorithms (pythonnet, Python 3.11)
Yahoo daily ──┘      (cross-checks only)
```

*Optional:* [klean-cli](KLEAN.md) (`tools/klean`, not installed by default) can automate §2–4.
Nothing here needs it; this guide does every step by hand.

Assumes Linux (tested on Ubuntu/Debian x86-64). macOS works the same except for the Python
library path (§4.1). Beginners: [BEGINNER.md](BEGINNER.md). Rules and evidence:
[AUDIT.md](AUDIT.md).

**Scope:** KOSPI stocks and ETFs, **daily** resolution. KOSDAQ, KONEX, NXT and minute data are
not covered (see [AUDIT.md](AUDIT.md) §0 for why).

---

## 0. Tested environment

| Component | Version |
|---|---|
| qc-krx | `main` of `pinjoy99/qc-krx` (record the commit you use, §8) |
| Python (pipeline) | 3.10+ (tested 3.13), `requests`, `yfinance` ≥ 0.2.54 (tested 1.7.0, only for `yahoo-daily`) |
| LEAN | `QuantConnect/Lean` commit `80e7843f645673bcbeaab963049f76f20f6785e1` |
| .NET SDK | 10.0.401 |
| Python (LEAN algorithms) | **3.11** with pandas 2.3.3 and numpy 1.26.4 (the versions in LEAN's `DockerfileLeanFoundation` at that commit) |

---

## 1. Data pipeline on your machine

### 1.1 Install and test

```bash
git clone https://github.com/pinjoy99/qc-krx.git && cd qc-krx
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover tests            # must print OK
```

### 1.2 Keys

Keys are read from environment variables only (whitespace is stripped). Never put them in files
under the repo.

| Variable | For | Services to approve |
|---|---|---|
| `KRX_API_KEY` | `krx`, `krx-index`, `krx-info` | 유가증권 일별매매정보, ETF 일별매매정보, KOSPI 시리즈 일별시세정보, 유가증권 종목기본정보 |
| `DATA_GO_KR_KEY` | `dividends`, `rights` | 금융위원회_주식배당정보 (15043284), 주식권리일정정보 (15059609) — the *Decoding* key |

A practical pattern is a `~/.config/qc-krx.env` file with `chmod 600`, loaded with
`set -a; . ~/.config/qc-krx.env; set +a`.

### 1.3 Initial backfill

All commands write under `--root` (default `./data`; put the option **before** the command
name). Every command is resumable: dates already on disk are skipped.

```bash
R=--root=/srv/krxdata
python -m qc_krx $R krx                 # KOSPI + ETF, 2010-01-04 → today (~8.7k calls)
python -m qc_krx $R krx-index           # KOSPI index series (~4.4k calls)
python -m qc_krx $R krx-info            # security master snapshot (ISIN, share class, par value)
python -m qc_krx $R dividends           # whole dividend table, 8 calls
python -m qc_krx $R rights              # corporate-action table, ~126 calls, 15–25 min (optional)
python -m qc_krx $R build               # ohlcv/, lean/, securities.csv, factor files, universe …
```

Throughput observed: about 100 KRX trading days per minute per market (0.2 s minimum between
calls). Storage observed for 2023-01 → 2026-10: `raw/` 116 MB, `lean/` 84 MB; expect roughly
4× for 2010 onward.

Stop/resume semantics:
- KRX: a non-trading day is stored as an empty file and never requested again, **except** within
  the last 7 days (KRX publishes a day's data the next day; recent empty answers are retried).
  The run stops at the first API error (unapproved service, quota); rerun to resume.
- data.go.kr: whole tables only (the APIs ignore date filters); refreshed at most daily
  (dividends) / weekly (rights) unless `--force`. The gateway resets connections often; each
  page is retried, and `rights` resumes from `raw/rights/.partial/`.

### 1.4 Daily operation

Run after KRX publishes (the next day; data was available by early afternoon KST in tests):

```bash
# crontab (system time zone; 14:30 KST = 05:30 UTC). Weekdays:
30 5 * * 1-5  cd /opt/qc-krx && . .venv/bin/activate && set -a && . ~/.config/qc-krx.env && set +a && \
  python -m qc_krx --root /srv/krxdata krx && python -m qc_krx --root /srv/krxdata krx-index && \
  python -m qc_krx --root /srv/krxdata dividends && python -m qc_krx --root /srv/krxdata build && \
  python -m qc_krx --root /srv/krxdata lean-install /opt/Lean/Data >> /var/log/qc-krx.log 2>&1
```

Add `rights` and `krx-info` weekly if you use `corporate_actions.csv` or `securities.csv`'s
master fields. `build` always rebuilds every output from `raw/` (the only state that matters);
it takes ~2 minutes for 16 years of KOSPI + ETF.

### 1.5 What `build` produces (and the rules behind it)

| Output | Content |
|---|---|
| `lean/equity/krx/daily/{code}.zip` | `yyyyMMdd 00:00,o,h,l,c,v`, prices × 10,000, raw KRW (KRX only) |
| `lean/equity/krx/factor_files/{code}.csv` | `date,price_factor,split_factor,reference_price` |
| `lean/equity/krx/map_files/{code}.csv` | first trading date; `20501231` or the last trading date (delisting) |
| `lean/equity/krx/universe/yyyyMMdd.zip` | `code,market,close,volume,value,market_cap,shares` per trading day |
| `lean/equity/krx/securities.csv` | code → market (used by the models), listing span, master fields |
| `lean/index/krx/daily/{kospi,kospi200}.zip` | index levels (not scaled) |
| `factor_events.csv` | every adjustment/dividend used in factor files (audit trail) |
| `ohlcv/`, `index/`, `dividends.csv`, `corporate_actions.csv` | plain CSVs for research |

Key rules (details and evidence in AUDIT.md §2):
- **Split factor** = KRX's own ratio: `base / previous close`, where `base = close − CMPPREVDD_PRC`.
  It differs from the previous close only on adjustment days (splits, reverse splits, bonus and
  rights issues, capital reductions, spin-offs), so rights issues are adjusted like splits.
- **Price factor** = Π `(close − dividend) / close` with the close before the ex-date; ex-date =
  the trading day before the last trading day ≤ record date (T+2). Only reported amounts are used
  (~13% of cash dividends have only a rate and are skipped).
- **Universe rows** are read by LEAN for the *previous* trading day when selection runs.
- Codes without KRX data are pruned from outputs; aikstockdata/Yahoo never feed them.

### 1.6 Cross-checks

```bash
python -m qc_krx $R daily                                  # aikstockdata: last 30 days of OHLCV
python -m qc_krx $R history 005930 000660                  # aikstockdata: close/volume since 2020
python -m qc_krx $R yahoo-daily 005930 069500 --start 2020-01-01   # paced: 2 s + jitter, 429 backoff
python -m qc_krx $R verify                                 # → reports/verify_summary.csv, verify_mismatches.csv
```

Expect 0 differences against aikstockdata. Yahoo differs before splits and some capital changes
(Yahoo back-adjusts its daily prices; KRX's are raw). Anything else in `verify_mismatches.csv` is
worth a look.

---

## 2. LEAN from source

### 2.1 Build

```bash
curl -sSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel 10.0   # → ~/.dotnet
export PATH=$HOME/.dotnet:$PATH
git clone https://github.com/QuantConnect/Lean.git /opt/Lean && cd /opt/Lean
git checkout 80e7843f645673bcbeaab963049f76f20f6785e1      # the tested commit (optional, recommended)
dotnet build Launcher/QuantConnect.Lean.Launcher.csproj -c Release   # ~2 min; warnings are normal
```

### 2.2 Install the KRX data

```bash
python -m qc_krx --root /srv/krxdata lean-install /opt/Lean/Data
```

To ship the data to another machine, package it in LEAN's layout and install only the config
entries there:

```bash
python -m qc_krx --root /srv/krxdata lean-package lean.zip        # data/equity/krx/…, data/index/krx/…
# on the target, for a lean init workspace:  cd <workspace> && unzip -o lean.zip
# for a source build:                        unzip -o lean.zip -d /tmp/krx && cp -r /tmp/krx/data/. /opt/Lean/Data/
python -m qc_krx lean-install --config-only <the Data folder>      # market hours + symbol properties
```

`--prefix` changes the top folder (`--prefix Data` matches a source build's capitalisation;
`--prefix ""` for none). Unzipping adds and replaces files but never deletes, same as
`lean-install`.

Idempotent. It copies `lean/equity/krx` and `lean/index/krx` over what is there (files are
added and replaced, not deleted — except the old `minute/` folder, which it removes), and:
- adds `Equity-krx-[*]` to `Data/market-hours/market-hours-database.json`: Asia/Seoul for data
  and exchange, pre-market 08:30–09:00, market 09:00–15:30, post 15:40–18:00, holidays = LEAN's
  `Index-krx-[*]` list ∪ every no-trade weekday in the data (it logs how many were only in the
  data; 0 so far);
- adds `krx,[*],equity,,KRW,1,1,1` to `Data/symbol-properties/symbol-properties-database.csv`
  (1-won step there; real tick sizes come from `KrxPriceVariationModel`).

Rerun it after every `build`. LEAN reads `Data/` directly, so no rebuild of LEAN is needed for
new data.

### 2.3 Running and reading results

The launcher takes config overrides on the command line (or edit `Launcher/config.json`). Run it
from `Launcher/bin/Release`; results land in that folder:

| File | Content |
|---|---|
| `<Algorithm>-summary.json` | statistics (`statistics`, `runtimeStatistics`, `totalPerformance`) — use this in scripts |
| `<Algorithm>.json` | full result incl. charts |
| `<Algorithm>-order-events.json` | every order event |
| `<Algorithm>-log.txt` | your `Log()` output |
| `failed-data-requests-*.txt` | files LEAN looked for and didn't find |

`failed-data-requests` for a universe strategy lists `equity/krx/universe/<date>.zip` for
weekends and holidays: expected (no file on non-trading days). Any `daily/`, `factor_files/` or
`map_files/` entry there means missing data — check `lean-install` and the code.

---

## 3. C# strategies

### 3.1 Files

Copy into `Lean/Algorithm.CSharp/` (namespace `QuantConnect.Algorithm.CSharp`):
- `examples/KrxModels.cs` — `KrxBoards`, `KrxFeeModel`, `KrxPriceVariationModel`,
  `KrxUniverseData`, `KrxIndex`;
- your algorithm (start from `examples/KrxTopMarketCapAlgorithm.cs` or `examples/KrxSmokeTest.cs`).

### 3.2 Build and run

```bash
cd /opt/Lean && dotnet build Launcher/QuantConnect.Lean.Launcher.csproj -c Release
cd Launcher/bin/Release
dotnet QuantConnect.Lean.Launcher.dll --algorithm-type-name KrxTopMarketCapAlgorithm \
  --algorithm-language CSharp --algorithm-location QuantConnect.Algorithm.CSharp.dll \
  --data-folder /opt/Lean/Data/ --close-automatically true
```

Rebuild after every change to a `.cs` file (data changes don't need it).

### 3.3 Required setup

```csharp
SetTimeZone("Asia/Seoul");
SetAccountCurrency("KRW");
var boards = KrxBoards.Load();                                  // Data/equity/krx/securities.csv
SetSecurityInitializer(s =>
{
    s.SetFeeModel(new KrxFeeModel(boards));                     // commission 0.015% default (2nd arg)
    s.PriceVariationModel = new KrxPriceVariationModel(boards);
});
SetBenchmark(KrxIndex.Benchmark("kospi200"));
AddEquity("005930", Resolution.Daily, Market.KRX);
// or: AddUniverse<KrxUniverseData>("name", Resolution.Daily, Market.KRX, data => ...)
```

---

## 4. Python strategies on the local build

LEAN hosts Python through pythonnet, which needs **CPython 3.11** (not 3.12/3.13) and the
libraries your algorithm imports, at least pandas and numpy.

### 4.1 One-time Python setup

```bash
# Debian 12: apt packages python3.11, python3.11-venv, libpython3.11.
# Ubuntu 24.04 ships 3.12: add the deadsnakes PPA (python3.11, python3.11-venv, libpython3.11).
# Any CPython 3.11 that provides libpython3.11.so works.
python3.11 -m venv /opt/lean-py311
/opt/lean-py311/bin/pip install pandas==2.3.3 numpy==1.26.4        # + whatever your strategy uses
```

Environment for every run:

```bash
export PYTHONNET_PYDLL=/usr/lib/x86_64-linux-gnu/libpython3.11.so   # macOS: …/libpython3.11.dylib
export PYTHONPATH=/opt/lean-py311/lib/python3.11/site-packages
```

Check with LEAN's own sample before your strategy:

```bash
cd /opt/Lean/Launcher/bin/Release
dotnet QuantConnect.Lean.Launcher.dll --algorithm-type-name BasicTemplateAlgorithm \
  --algorithm-language Python --algorithm-location ../../../Algorithm.Python/BasicTemplateAlgorithm.py \
  --data-folder /opt/Lean/Data/ --close-automatically true
```

### 4.2 Project layout and run

Keep each Python strategy in its own folder with the models next to it; LEAN puts the
algorithm's folder on `sys.path`, so `from krx_models import ...` works:

```
~/strategies/top20/
  main.py          ← cp examples/python/krx_top_market_cap/main.py
  krx_models.py    ← cp examples/python/krx_models.py
```

```bash
dotnet QuantConnect.Lean.Launcher.dll --algorithm-type-name KrxTopMarketCapAlgorithm \
  --algorithm-language Python --algorithm-location ~/strategies/top20/main.py \
  --data-folder /opt/Lean/Data/ --close-automatically true
```

No LEAN rebuild is needed for Python changes.

**Known harmless crash at exit:** after the statistics are printed and the result files are
written, the process can abort with `GIL must always be released, and it must be released from
the same thread that acquired it` (pythonnet shutdown). Exit code is then non-zero, so in scripts
read `<Algorithm>-summary.json` instead of trusting the exit code.

### 4.3 Required setup (Python)

```python
from AlgorithmImports import *
from krx_models import KrxBoards, KrxUniverseData, krx_benchmark, krx_initialize

class MyStrategy(QCAlgorithm):
    def initialize(self):
        self.set_time_zone("Asia/Seoul")
        self.set_account_currency("KRW")
        boards = KrxBoards.load()
        self.set_security_initializer(lambda s: krx_initialize(s, boards))   # fee + tick models
        self.set_benchmark(krx_benchmark("kospi200"))
        self.add_equity("005930", Resolution.DAILY, Market.KRX)
        # universe:
        # self.add_universe(KrxUniverseData, SecurityType.EQUITY, "name", Resolution.DAILY,
        #                   Market.KRX, self.select)   # rows: d["board"], d["market_cap"], ...
```

`krx_initialize(security, boards, commission_rate=0.00015)` sets `KrxFeeModel` and
`KrxPriceVariationModel`. Implementation notes, in case you modify `krx_models.py`:
- **Fees use `Decimal`**: with floats, truncating to whole won drifted by a few won from C#.
- **`KrxPriceVariationModel` subclasses `SecurityPriceVariationModel`** with
  `__namespace__ = "QcKrx"` and also binds `GetMinimumPriceVariation`. Without that, LEAN never
  called the Python method and limit prices weren't rounded.
- **Universe rows store fields by key** (`row["market_cap"]`); read them as `d["market_cap"]`.

### 4.4 Parity with C# (measured)

Same strategy (KOSPI top 20 by market cap, monthly, equal weight, KRX fees/taxes), same data,
2023-02-01 → 2026-10-07, ₩1B:

| | C# | Python |
|---|---|---|
| End equity | ₩2,106,541,997.48 | ₩2,106,541,997.48 |
| Total fees | ₩13,395,456 | ₩13,395,456 |
| Orders | 670 | 670 |
| CAGR / max drawdown / Sharpe | 22.398% / 31.1% / 0.547 | 22.398% / 31.1% / 0.547 |
| Runtime | 18 s | 2 min 21 s |

Python is ~8× slower here; the per-row Python universe reader (~2,000 rows per trading day) is
the likely main cost. For long universe backtests, prefer C#.

---

## 5. Modelling rules and caveats for strategy authors

- **Always `Market.KRX`** and 6-character codes (`"005930"`, letters possible: `"0052D0"`).
- **Fee model is mandatory**: LEAN's default throws `unexpected equity Market krx` on the first order.
- **Sell tax by settlement date** (T+2 via the exchange calendar): KOSPI 0.30% → 0.25%
  (2019-06-03) → 0.23% (2021) → 0.20% (2023) → 0.18% (2024) → 0.15% (2025) → 0.20% (2026), 농특세
  included; ETFs 0. Commission default 0.015% per side; set your broker's rate.
- **Tick sizes** apply to limit/stop prices (LEAN rounds them and logs a warning). In the default
  `Adjusted` normalization LEAN passes adjusted prices, so rounding is exact only in `Raw` mode.
- **Prices are adjusted** (splits, rights/bonus issues, cash dividends) by default; use
  `DataNormalizationMode.Raw` to trade at exchange prices.
- **Benchmark**: use the function (`KrxIndex.Benchmark` / `krx_benchmark`), never an index
  symbol. LEAN subscribes a benchmark symbol hourly and the KRX index data is daily, so the
  benchmark would be empty (alpha/beta 0).
- **Delisted securities** are in the data and universe; LEAN delists them on their last day
  (map file). Liquidate removed universe members yourself (`on_securities_changed`).
- **Not modelled yet:** slippage and market impact, ±30% price limits and auctions (fill model),
  T+2 cash settlement (sale proceeds are usable immediately), short-selling rules. LEAN reports
  "Estimated Strategy Capacity ₩0" for KRX backtests; ignore it.
- **Common vs preferred**: the examples treat codes ending in `0` as common shares (KRX
  convention); use `securities.csv`'s `share_class` for anything stricter.

---

## 6. Changing or extending the models

The C# and Python versions must stay identical; change both and rerun the parity check (§4.4).

| Change | Where |
|---|---|
| Commission rate | constructor / `krx_initialize(..., commission_rate=...)` — no code change |
| New tax rate | `KospiTax`/`KosdaqTax`/`KonexTax` in `KrxModels.cs` and `_KOSPI_TAX`/… in `krx_models.py`; add the source to AUDIT.md §2.3 |
| New tick table | `KrxPriceVariationModel.Tick` and `tick_size()` |
| New universe column | `lean_extras.build_universe` (Python pipeline), then both `KrxUniverseData` readers |

Both example algorithms log `CHECK tax …` and `CHECK tick …` with model values for known dates;
compare those lines after any change.

---

## 7. Automating backtests

```bash
run_krx() {  # run_krx <TypeName> <CSharp|Python> <location>
  ( cd /opt/Lean/Launcher/bin/Release &&
    PYTHONNET_PYDLL=/usr/lib/x86_64-linux-gnu/libpython3.11.so \
    PYTHONPATH=/opt/lean-py311/lib/python3.11/site-packages \
    dotnet QuantConnect.Lean.Launcher.dll --algorithm-type-name "$1" --algorithm-language "$2" \
      --algorithm-location "$3" --data-folder /opt/Lean/Data/ --close-automatically true > "$1.run.log" 2>&1
    python3 -c "import json,sys; s=json.load(open('$1-summary.json'))['statistics']; \
print({k: s[k] for k in ('Compounding Annual Return','Drawdown','Sharpe Ratio','Total Fees','End Equity')})" )
}
run_krx KrxTopMarketCapAlgorithm CSharp QuantConnect.Algorithm.CSharp.dll
run_krx KrxTopMarketCapAlgorithm Python ~/strategies/top20/main.py
```

The second run overwrites the first run's result files (same algorithm name). Copy them away,
or use different class names.

---

## 8. Reproducibility and audit checklist

For every result you keep, record:
1. the qc-krx commit (`git rev-parse HEAD`) and the LEAN commit;
2. the data state: newest date in `raw/krx/KOSPI/`, the dividend snapshot name
   (`raw/dividends/<basDt>.csv.gz`), and optionally `sha256sum` of `raw/` files;
3. `reports/verify_summary.csv` from that build;
4. the algorithm source and its `-summary.json` / `-order-events.json`;
5. the commission rate used.

Because every output is rebuilt from `raw/`, the same raw files + the same qc-krx commit give
the same LEAN data (identical file contents; zip timestamps differ).

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `unexpected equity Market krx` | no fee model | Set `KrxFeeModel` / `krx_initialize` |
| market hours not found for `Equity-krx` | `lean-install` not run on this `Data/` | Run it |
| Benchmark alpha/beta 0 | index symbol as benchmark | Use the benchmark function |
| Python: `Failed to load ... libpython` / `PythonEngine` errors | wrong or missing `PYTHONNET_PYDLL`, Python ≠ 3.11 | Point it at libpython3.11 |
| Python: `No module named pandas` | `PYTHONPATH` not set to the 3.11 venv | Set it (§4.1) |
| Python: `No module named krx_models` | file not next to `main.py` | Copy it there |
| Python: limit prices not rounded | modified `KrxPriceVariationModel` without `__namespace__` / `GetMinimumPriceVariation` | Keep both (§4.3) |
| Process aborts at exit (GIL message) | pythonnet shutdown | Harmless; read `-summary.json` |
| `401 Unauthorized API Call` | KRX service not approved | Approve it on openapi.krx.co.kr |
| Recent day missing | KRX publishes next day | Rerun later; recent days are retried |
| `rate limited 4 times in a row` | Yahoo throttling (`yahoo-daily`) | Rerun later |

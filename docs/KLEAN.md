# klean-cli (optional)

**klean is strictly optional.** Nothing in qc-krx needs it: the data pipeline, `lean.zip`,
`lean-install`, the KRX models and every guide work without it ([BEGINNER.md](BEGINNER.md)
Stage 4 and [EXPERT.md](EXPERT.md) §2–4 do the same steps by hand). It lives in its own folder,
`tools/klean/`, and is only installed if you install it.

`klean` does the local part of the LEAN CLI's workflow (create a workspace, create a project,
backtest) on a **LEAN build from source**: no Docker, no QuantConnect account, no subscription.
It's made for the KRX data of this project and works with Python and C# strategies.

| LEAN CLI | klean | What it does |
|---|---|---|
| (Docker image) | `klean install-lean` | clone LEAN at the tested commit and build it (.NET 10) |
| (Docker image) | `klean install-python` | Python 3.11 environment with pandas/numpy, for Python strategies |
| `lean init` | `klean init` | workspace: `klean.json` + `data/` with LEAN's config files only (no vendor sample data) |
| — | `klean data install lean.zip` | KRX data into `data/` + the KRX market hours and symbol properties |
| `lean project-create` | `klean project-create` | project with `main.py` / `Main.cs` and the KRX models next to it |
| `lean backtest` | `klean backtest` | build/check, run LEAN, results in `<project>/backtests/<timestamp>/`, print statistics |
| — | `klean doctor` | check dotnet, the LEAN build, the data and the Python environment |

Not covered: cloud sync, cloud backtests, live trading, research notebooks, optimization.

## Install

From a clone of this repository:

```bash
git clone https://github.com/pinjoy99/qc-krx.git && cd qc-krx
python3 -m venv ~/.klean/tools && source ~/.klean/tools/bin/activate
pip install -e tools/klean       # installs only the `klean` command
klean --version
```

`klean` uses the clone: it copies the KRX models from `examples/` into new projects and uses
`qc_krx` for `data install`. Keep the clone (and `git pull` it to get model updates). To remove
klean: `pip uninstall klean-cli`. Its tests: `python -m unittest discover tools/klean/tests`.

Prerequisites: `git`, the **.NET 10 SDK**
(`curl -sSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel 10.0`, then add
`~/.dotnet` to `PATH`) and, for Python strategies, a **CPython 3.11** with its shared library
(`libpython3.11.so`; Debian/Ubuntu package `libpython3.11`; on Ubuntu 24.04 via the deadsnakes PPA).

## Quick start

```bash
klean install-lean --dir ~/Lean                     # once; 1–10 min (76 s here), ~0.9 GB
klean install-python --dir ~/.klean/py311           # once, only for Python strategies
klean init ~/krx-workspace --lean ~/Lean --python-venv ~/.klean/py311 --data-zip ~/Downloads/lean.zip
cd ~/krx-workspace
klean doctor                                        # every line should say OK
klean project-create "My First" --language python   # or --language csharp
klean backtest "My First"
```

`lean.zip` is the file the Colab notebook puts in Google Drive (`qc-krx-data/lean.zip`), or make
it yourself with `python -m qc_krx --root <data root> lean-package lean.zip`. If you run the
pipeline on the same machine, `klean data install --root <data root>` copies it directly.

## Workspace layout

```
krx-workspace/
  klean.json                 lean_root, python_venv, python_dll
  data/                      LEAN's data folder for this workspace
    market-hours/            copied from LEAN, plus the Equity-krx entry
    symbol-properties/       copied from LEAN, plus the krx line
    equity/krx/              KRX daily prices, factor/map files, universe, securities.csv
    index/krx/               KOSPI, KOSPI 200
  My First/                  a Python project
    main.py
    krx_models.py
    requirements.txt         optional: extra packages, installed before each backtest
    backtests/2026-10-20_20-17-44/   one folder per run
  My First CS/               a C# project
    Main.cs  KrxModels.cs  MyFirstCS.csproj
```

Projects can live anywhere inside the workspace; klean finds `klean.json` from the project's
folder upwards (like git). `klean init` doesn't copy LEAN's sample market data (US equities,
forex, …; third-party vendors' prices) unless you add `--sample-data`.

## Backtests

```bash
klean backtest "My First"
klean backtest "My First" --parameter weight 0.5 --parameter lookback 20
```

What happens:
1. **Python**: every `.py` file is byte-compiled (syntax check) and `requirements.txt`, if any,
   is installed into the Python 3.11 environment. **C#**: `dotnet build` of the project against the
   DLLs of your LEAN build (`<lean_root>/Launcher/bin/Release`; LEAN's own example algorithms
   are not referenced).
2. LEAN's launcher runs with the workspace's `data/` and a new results folder. The algorithm
   class is found automatically (the class deriving from `QCAlgorithm`; exactly one per project).
3. The main statistics from `<Algorithm>-summary.json` are printed.

Results folder:

| File | Content |
|---|---|
| `<Algorithm>-summary.json` | statistics |
| `<Algorithm>.json` | full result incl. charts |
| `<Algorithm>-order-events.json` | orders and fills |
| `<Algorithm>-log.txt` | your `log()` / `Log()` lines |
| `console.txt` | LEAN's full console output — look here when something fails |
| `failed-data-requests-*.txt` | files LEAN didn't find (universe files for weekends/holidays are expected) |

Parameters reach the algorithm through `self.get_parameter("weight", "0.9")` /
`GetParameter("weight", "0.9")`. Names and values can't contain `,` or `:`.

Python runs can end with a `GIL must always be released` crash *after* the results are written
(pythonnet shutdown); klean treats a run with a summary file as successful.

## Verified (2026-10-20, on this project's data)

| Run | Result |
|---|---|
| `project-create` templates, Python and C# (buy and hold Samsung from 2024-01-02) | identical: end equity ₩328,341,636.58, fees ₩13,017; 11 s / 19 s |
| KOSPI top-20 strategy (`examples/`), Python and C#, 2023-02-01 → 2026-10-07 | identical: end equity ₩2,106,541,997.48, 670 orders, fees ₩13,395,456 — the same as running LEAN by hand; 2 min 27 s / 17 s |
| `--parameter weight 0.45` | end equity ₩214,170,818.79 (vs ₩328,341,636.58 with the default 0.9) |
| `init` with `--data-zip` on LEAN's original config files | `Equity-krx` market hours and `krx` symbol properties added; LEAN's own files untouched |

## Moving projects to or from the LEAN CLI

The project layout matches the CLI's: a Python project (`main.py`, extra `.py` files,
`requirements.txt`) runs unchanged under `lean backtest`. A C# project needs its `.csproj`
swapped: klean's references your LEAN build's DLLs, the CLI's uses the `QuantConnect.Lean`
NuGet package.

## Troubleshooting

| Message | Fix |
|---|---|
| `no klean.json in … or its parents` | run inside a workspace, or `klean init` |
| `dotnet not found` | install the .NET 10 SDK and add `~/.dotnet` to `PATH` |
| `no LEAN build in …` | `klean install-lean`, or fix `lean_root` in `klean.json` |
| `no Python environment in klean.json` | `klean install-python` inside the workspace |
| `no shared libpython3.11` | install `libpython3.11` (or a CPython 3.11 built with `--enable-shared`) |
| `expected one class deriving from QCAlgorithm` | keep exactly one algorithm class per project |
| `backtest failed …` | read the lines shown and `console.txt` in the results folder |
| `unexpected equity Market krx` (in console.txt) | the algorithm has no KRX fee model: keep `krx_initialize` / `KrxFeeModel` |

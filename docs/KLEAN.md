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
| — | `klean data status` | KRX data range, securities (active / delisted), universe files, indices, market hours |
| `lean config get/set/list/unset` | `klean config …` | workspace settings, and LEAN config keys applied to every backtest |
| `lean project-create` | `klean project-create` | project with `main.py` / `Main.cs` and the KRX models next to it; `--template buy-hold / top-market-cap / empty` |
| `lean project-delete` | `klean project-delete` | delete a project and its backtests (asks for the name) |
| `lean backtest` | `klean backtest` | build/check, run LEAN, results in `<project>/backtests/<timestamp>/` with a `manifest.json`, print statistics |
| `lean logs` | `klean logs` | a run's algorithm log, or LEAN's console output |
| — | `klean compare` | runs side by side: statistics and equity curves, says IDENTICAL / DIFFERENT |
| (`lean build`) | `klean lean status` / `klean lean update` | the LEAN commit in use; check out another one and rebuild |
| — | `klean doctor` | check dotnet, the LEAN build, the data and the Python environment |
| `lean gui` (paid) | `klean gui` | local web page: projects, runs, results charts, comparisons, start backtests |

Not covered yet: research notebooks, optimization, reports, live trading (roadmap P2–P4). Cloud features are out
of scope. The plan, command by command against the LEAN CLI: [KLEAN-ROADMAP.md](KLEAN-ROADMAP.md).

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
klean backtest "My First" --backtest-name half-weight --parameter weight 0.5
klean backtest "My First" --extra-config maximum-data-points-per-chart-series 4000
klean backtest "My CS" --build-config Debug --output ~/runs/debug-1
```

What happens:
1. **Python**: every `.py` file is byte-compiled (syntax check) and `requirements.txt`, if any,
   is installed into the Python 3.11 environment. **C#**: `dotnet build` of the project against the
   DLLs of your LEAN build (`<lean_root>/Launcher/bin/Release`; LEAN's own example algorithms
   are not referenced).
2. The run's LEAN config is written to `<results>/config.json`: LEAN's own `Launcher/config.json`
   plus the workspace's LEAN keys (`klean config set KEY VALUE`) plus `--extra-config KEY VALUE`.
   Values are read as JSON when possible (`true`, `4000`, `{"a": 1}`), otherwise as text.
3. LEAN's launcher runs with that config, the workspace's `data/` and the results folder
   (`<project>/backtests/<yyyy-MM-dd_HH-mm-ss>[_<backtest-name>]/`, or `--output`). The
   algorithm class is found automatically (the class deriving from `QCAlgorithm`; exactly one per
   project).
4. `manifest.json` is written and the main statistics are printed.

Results folder:

| File | Content |
|---|---|
| `<Algorithm>-summary.json` | statistics |
| `<Algorithm>.json` | full result incl. charts |
| `<Algorithm>-order-events.json` | orders and fills |
| `<Algorithm>-log.txt` | your `log()` / `Log()` lines |
| `console.txt` | LEAN's full console output — look here when something fails |
| `config.json` | the LEAN config the run used |
| `manifest.json` | what produced the results: project, language, algorithm class, parameters, LEAN config keys, build config, start time and duration, exit code, **qc-krx and LEAN commits** (`-dirty` = uncommitted changes), **last date of the KRX data**, host, and the sha256 of every project file |
| `failed-data-requests-*.txt` | files LEAN didn't find (universe files for weekends/holidays are expected) |

Parameters reach the algorithm through `self.get_parameter("weight", "0.9")` /
`GetParameter("weight", "0.9")`. Names and values can't contain `,` or `:`.

Python runs can end with a `GIL must always be released` crash *after* the results are written
(pythonnet shutdown); klean treats a run with a summary file as successful.

A strategy without `set_end_date` / `SetEndDate` runs up to today, so its yearly figures (CAGR,
Sharpe) change from day to day even when the trades don't. Set an end date when you want runs
to be comparable over time.

## Comparing runs and reading logs

```bash
klean compare "My First" "My CS"            # latest run of each project
klean compare "My First/2026-10-28_20-05" "My First/2026-10-28_20-06-16_renamed"   # by name or prefix
klean compare ~/runs/debug-1 "My CS" --all  # results folders, all statistics
klean logs "My First" --tail 20             # algorithm log of the latest run
klean logs "My First/2026-10-28_20-05" --console
```

A run is named by a project (its latest run), `PROJECT/RUN` or `PROJECT@RUN` (folder name or a
unique prefix), or a results folder path. `compare` prints the statistics side by side, marks
differences with `≠`, compares the equity curves point by point, and ends with `IDENTICAL` or
`DIFFERENT: …`.

## Workspace settings

```bash
klean config list
klean config set python_venv ~/.klean/py311       # also finds its libpython
klean config set maximum-data-points-per-chart-series 4000   # LEAN key, used by every backtest
klean config unset maximum-data-points-per-chart-series
klean data status
klean lean status                                 # LEAN commit (tested: 80e7843) and build
klean lean update [--commit C]                    # check out and rebuild; default: the tested commit
```

`lean_root`, `python_venv` and `python_dll` are klean's own settings; every other key is stored in
`klean.json` under `lean_config` and passed to LEAN. After `lean update` to another commit, rerun
a reference backtest and `klean compare` it with an earlier run before relying on the new build.
`lean status` shows `-dirty` if LEAN's checkout has local changes (for example `lean-install` run
on `Lean/Data` directly).

## Verified (2026-10-20 and 2026-10-28 for P1, on this project's data)

| Run | Result |
|---|---|
| `project-create` templates, Python and C# (buy and hold Samsung from 2024-01-02) | identical: end equity ₩328,341,636.58, fees ₩13,017; 11 s / 19 s |
| KOSPI top-20 strategy (`examples/`), Python and C#, 2023-02-01 → 2026-10-07 | identical: end equity ₩2,106,541,997.48, 670 orders, fees ₩13,395,456 — the same as running LEAN by hand; 2 min 27 s / 17 s |
| `--parameter weight 0.45` | end equity ₩214,170,818.79 (vs ₩328,341,636.58 with the default 0.9) |
| `init` with `--data-zip` on LEAN's original config files | `Equity-krx` market hours and `krx` symbol properties added; LEAN's own files untouched |
| P1: `--template top-market-cap`, C# vs Python, via `klean compare` | IDENTICAL including equity curves: ₩2,417,175,763.24 |
| P1: `--extra-config algorithm-id MyRun` | result files renamed `MyRun-*`, so the per-run config reaches LEAN |
| P1: `project-delete` | asks for the name; refuses `data/` and folders outside the workspace |
| P1: `lean update` (tested commit) | rebuilt in 94 s, 0 errors |
| GUI (Chromium, light/dark, desktop and 420 px wide) | all pages render with no browser errors; hover values; a backtest started from the page runs, the runs list refreshes, results open; compare of C# vs Python top-market-cap: IDENTICAL; requests without the token: 403; runs outside the workspace refused |

## GUI

```bash
cd ~/krx-workspace
klean gui                       # prints http://127.0.0.1:<port>/?token=… and opens the browser
klean gui --port 8765 --no-browser
```

A local web page for the workspace (stop it with Ctrl+C):

| Page | Shows |
|---|---|
| Workspace | projects with their last run (CAGR, drawdown, Sharpe, end equity), KRX data status, setup check, settings |
| Project | its runs (tick two or more → Compare), and a form to start a backtest with a name, parameters and extra LEAN config, with LEAN's output live |
| Run | main figures, equity vs KOSPI 200 (scaled to the starting equity) with hover values, drawdown, all statistics, orders, the algorithm log or LEAN's console output, the run record (`manifest.json`) |
| Compare | equity curves overlaid and statistics side by side, differences highlighted, IDENTICAL / DIFFERENT |

- It uses only Python's standard library, and the page draws its own charts, so it works offline
  and installs nothing.
- **Local only.** It listens on 127.0.0.1, and every request needs the random token in the
  printed URL, so other web pages open in the browser can't use it. Starting a backtest also
  needs the token in a request header, which a cross-site form can't send. It only reads and runs
  projects inside the workspace.
- It reads the same files as `klean compare` / `klean logs`; backtests started from the page are
  ordinary klean runs (`<project>/backtests/<timestamp>_<name>/` with `manifest.json`).
- Long series are thinned to 1,500 points for the charts; the files keep every point.
- It doesn't edit code: use your editor on the project folders.

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

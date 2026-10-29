# klean-cli roadmap: expanding it by comparison with the LEAN CLI

Plan written 2026-10-21, comparing klean 0.1.0 with `QuantConnect/lean-cli` at commit `b4d724c`
(2026-10-15). klean stays **strictly optional** (see [KLEAN.md](KLEAN.md)); nothing here changes
that.

## Principles

1. **Optional and separate.** klean lives in `tools/klean`; the pipeline, the models and the
   guides never depend on it. Each feature must also be doable by hand (documented in EXPERT.md).
2. **Local only.** No QuantConnect account, servers or paid features; no Docker. Features of the
   LEAN CLI that exist to use QuantConnect's services (cloud, their data, their live trading) are
   out of scope. They aren't re-implemented or worked around.
3. **Same project layout as the LEAN CLI**, so a Python project moves between the two unchanged.
   Keep option names the same where the meaning is the same (`--output`, `--parameter`, …).
4. **Built on LEAN's own launchers** (`Launcher`, `Optimizer.Launcher`, `Report`, `Research`)
   from the pinned LEAN commit; klean only prepares configs and folders.
5. **Every feature is tested** on real KRX data and, where it applies, in both Python and C#
   (the parity standard so far: identical results).

## Command-by-command comparison

Status: ✅ in klean 0.1 · 🔜 planned (phase) · ➖ not applicable / out of scope.

| LEAN CLI | What it does | klean | Plan |
|---|---|---|---|
| `lean init` | workspace, `lean.json`, downloads LEAN's `Data/` (incl. vendor sample data) | ✅ `klean init` | Copies only LEAN's config files by default; `--sample-data` optional |
| `lean login` / `logout` / `whoami` | QuantConnect account | ➖ | No account needed |
| `lean config get/set/list/unset` | edit `lean.json` | ✅ `klean config …` (P1) | Same verbs on `klean.json` (lean_root, python env, defaults such as commission rate, start cash) |
| `lean create-project --language` | project from a template | ✅ `klean project-create` | ✅ P1: `--template` (buy-hold, top-market-cap universe, empty) |
| `lean delete-project` | delete a project | ✅ `klean project-delete` (P1) | Asks for confirmation; refuses outside the workspace |
| `lean backtest` | compile + run in Docker | ✅ `klean backtest` | P1 options below |
| `  --output` | results folder | ✅ (P1) | Default stays `<project>/backtests/<timestamp>/` |
| `  --backtest-name` | name the run | ✅ (P1) | Folder suffix + `backtest-name` in LEAN |
| `  --extra-config` | extra LEAN config keys | ✅ (P1) | `--extra-config KEY VALUE`, written to a per-run config file |
| `  --release` / `--debug` | C# build config / attach a debugger | ✅ P1 `--build-config`, 🔜 P3 `--debug` | P3: VS Code / Rider attach for C#, `debugpy` for Python |
| `  --python-venv` | Python env | ✅ (klean.json) | — |
| `  --detach` | run in the background | 🔜 P2 | Background process + `klean logs` to follow it |
| `  --download-data`, `--data-provider-historical`, `--data-purchase-limit` | QuantConnect / vendor data | ➖ | Data comes from the qc-krx pipeline (`klean data install`) |
| `  --image`, `--update`, `--no-update`, `--extra-docker-config`, `--addon-module` | Docker image / modules | ➖ | No Docker. Engine updates: P1 `klean lean update` |
| `lean optimize` | parameter search via Optimizer.Launcher | ✅ `klean optimize` (P2, 2026-10-29) | Grid search; `--parameter NAME MIN MAX STEP`, `--target`, `--target-direction`, `--constraint`, `--max-concurrent-backtests`, `--estimate`. klean runs the grid itself (see P2); no Euler strategy |
| `lean report` | HTML/PDF report from backtest results | 🔜 P2 `klean report` | Build LEAN's `Report` project once; run it on a results folder; check that won (KRW) amounts and the KOSPI 200 benchmark show correctly |
| `lean research` | Jupyter with QuantBook (Docker research image) | 🔜 P3 `klean research` | Jupyter in the Python 3.11 env with LEAN's `Research/` (QuantBook) on the source build; needs investigation (kernel start-up, pythonnet) |
| `lean logs` | show a run's log | ✅ `klean logs` (P1) | Latest (or `--backtest NAME`) `-log.txt` / `console.txt` of a project |
| `lean build` | build custom Docker images | ➖ / ✅ P1 | No images. Equivalent: `klean lean update [--commit]` (fetch, rebuild, re-check) |
| `lean library add/remove` | share code between projects | 🔜 P2 `klean library …` | Shared folders on the Python path / C# project references. First use: one shared copy of the KRX models instead of a copy per project |
| `lean data download` | buy/download QuantConnect data | ➖ | Paid QuantConnect data |
| `lean data generate` | random synthetic data | ➖ (maybe later) | Low value for KRX; real data is available |
| `lean object-store …` | local key-value store for algorithms | 🔜 P3 `klean object-store …` | LEAN's local object store pointed at `<workspace>/storage` |
| `lean live deploy/stop/liquidate/…` | live trading (local engine + brokerage) | 🔜 P4 | Only with the qc-krx-broker plugin (KIS), paper trading first |
| `lean cloud …` (backtest, live, push/pull, optimize, object-store, status) | QuantConnect cloud | ➖ | QuantConnect service |
| `lean private-cloud …` | QuantConnect private cloud | ➖ | QuantConnect service |
| `lean encrypt` / `decrypt` | encrypt project files for the cloud | ➖ | Cloud feature |
| `lean gui` / `lean ui` | local GUI (paid) / terminal UI | ✅ `klean gui` (2026-10-28) | Local web page: workspace, project runs, results charts, compare, start backtests. No code editor |

## Additions that the LEAN CLI doesn't have (KRX-specific)

| Command | Why | Phase |
|---|---|---|
| `klean doctor` | check .NET, LEAN build, data, Python env | ✅ |
| `klean data install` | lean.zip / data root into the workspace + KRX market config | ✅ |
| `klean data status` | KRX data range, last trading day, securities (active / delisted), universe files, indices, market hours | ✅ P1 |
| Run manifest (`manifest.json` in every results folder) | reproducibility: qc-krx and LEAN commits, data last date, parameters, LEAN config, build config, sha256 of the project files (EXPERT.md §8 checklist, automatic) | ✅ P1 |
| `klean compare RUN_A RUN_B` | statistics side by side; used for the C#/Python parity checks and before/after model changes | ✅ P1 |
| `klean check-models` | run the `CHECK tax/tick` cases in C# and Python and compare | P2 |

## Phases

### P1 — everyday use ✅ done (2026-10-28)
- `backtest`: `--output`, `--backtest-name`, `--extra-config`, `--build-config Release|Debug`
  (instead of the CLI's `--release`: klean builds Release by default); run manifest and per-run
  LEAN config in every results folder.
- `config get/set/list/unset`, `logs`, `project-delete`, `project-create --template`.
- `data status`, `compare`, `lean status` / `lean update`.
- **Verified:** the top-market-cap template gives the identical result in Python and C#
  (`klean compare`: IDENTICAL incl. equity curves); 14 klean unit tests. See KLEAN.md.

### P2 — research workflow
- ✅ `optimize` (2026-10-29). Deviation from the plan: not on `Optimizer.Launcher`, whose child
  backtests get no `--data-folder` / `--config` (they would read LEAN's `Data/`); klean compiles
  once and runs the grid as ordinary klean runs in parallel, so only grid search (no Euler).
  Tested with a 1-parameter grid (`holdings` 5–30, 6 runs) in C# and a 2-run Python grid; the
  rebalance-month parameter wasn't added. GUI: optimization page (ranked runs, target chart).
- `report` on LEAN's `Report` project; HTML first, PDF if the tooling is available.
- `library add/remove`; switch templates to a shared KRX-models library (optional per project).
- `backtest --detach`; `check-models`.
- **Done when:** an optimization of ≥ 6 combinations finishes and its best run is identical to a
  plain backtest with the same parameters; a report opens with KRW amounts and the benchmark.

### P3 — tools
- `research` (Jupyter + QuantBook on the source build), `--debug` (C# attach, `debugpy`),
  `object-store`.
- **Done when:** a notebook loads KRX history through QuantBook; a breakpoint is hit in both
  languages.

### P4 — paper/live trading
- Depends on qc-krx-broker (KIS Developers, paper account) and `KrxBrokerageModel`
  (qc-krx-market). `klean live deploy --brokerage kis --paper`, `stop`, `liquidate`, order commands.
- **Done when:** a paper-trading session places, fills and reconciles orders on the KIS paper
  account; nothing runs against a real account without an explicit flag.

## Risks and open questions

- **LEAN version drift.** Launchers' configs and DLL names change between LEAN versions. Keep the
  pinned commit as default; `klean lean update` must rerun the parity tests before switching.
- **Python 3.11 only** (pythonnet). Watch LEAN's foundation image for the move to a newer Python.
- **Report and Research** haven't been tried on the source build; they may need extra packages
  (the report uses Python plotting libraries) — find out before committing to P2/P3 dates.
- **Optimizer.Launcher** runs backtests as separate processes; Python runs are ~8× slower than C#
  (2 min 27 s vs 17 s for the top-20 strategy), so optimizations should prefer C# or limit
  concurrency by memory.
- **Cross-platform.** Only Linux is tested; macOS needs the libpython lookup and paths checked.
- **Scope creep toward QuantConnect's services.** Anything that needs their account or data stays
  out (principle 2).

## Suggested order

P1 is done, and `optimize` from P2; next `report`, because parameter
searches and reports are the most common next needs after single backtests. P3 on demand. P4 only
after the broker plugin exists.

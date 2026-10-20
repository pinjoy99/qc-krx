# qc-krx for beginners

This guide is for you if you have never used an API key, Google Colab, Python or LEAN.
It takes you from nothing to:

1. **Korean stock data in your Google Drive** (no installation, about 1 day including waiting
   for approvals), and
2. **your first backtest** in Python on your own computer with klean and LEAN — free, no
   Docker (optional, about 1 hour).

Every step says what to click, what you should see and what to do if it goes wrong. If you
want the technical details, read [GUIDE.md](GUIDE.md) after this.

---

## What this project does, in one picture

```
 Korea Exchange (KRX) ──┐
 Public data portal ────┼──▶  Google Colab  ──▶  Your Google Drive  ──▶  LEAN (backtests)
 Yahoo Finance ─────────┘     (runs the code      (keeps the data)        on your computer
                               in your browser)
```

- **KRX** (Korea Exchange) gives the daily prices of every stock and ETF on KOSPI since 2010.
- **The public data portal** (data.go.kr) gives dividends and corporate events (splits etc.).
- **Yahoo Finance** daily prices are used only to double-check the KRX prices.
- **Google Colab** is a free Google service that runs code in your web browser. You don't
  install anything.
- **LEAN** is free software from QuantConnect that replays history to test a trading idea
  (a "backtest").

**What is covered now:** stocks on **KOSPI** and **ETFs**. KOSDAQ, KONEX and NXT are not covered
yet.

---

## Words you will see

| Word | Meaning |
|---|---|
| API key | A password that lets a program download data from a website. Keep it secret. |
| Colab notebook | A web page with code blocks ("cells") that you run with a ▶ button. |
| Secret (in Colab) | A safe place in Colab to store an API key so it doesn't appear on screen. |
| OHLCV | Open, High, Low, Close price and Volume of one day. |
| Ticker / code | The 6-character KRX code of a security, e.g. `005930` = Samsung Electronics. |
| Split | A company divides each share into several (Samsung: 1 → 50 in 2018); the price drops by the same factor. |
| Adjusted price | Past prices recalculated so splits and dividends don't look like crashes. |
| Backtest | Running a trading rule on past data to see how it would have done. |
| Daily bar | One row of OHLCV for one day. |
| klean | The `klean` command that comes with this project: builds LEAN once and runs your backtests. |
| Workspace | The folder made by `klean init`: your projects plus a `data/` folder LEAN reads. |

---

## Stage 1 — Get your keys (one time; about 1 day because of approvals)

You need three keys. All are free.

### 1.1 KRX key (required)

1. Open <https://openapi.krx.co.kr/> and click **회원가입** (sign up). Make an account and log in.
2. Click **마이페이지** (my page) → **API 인증키 신청** (request API key). You get a key: 40
   letters and digits. Copy it into a note for now.
3. Ask for permission to use four services. For each one: click **서비스 이용**, find the
   service, click **API 이용신청**, choose **12M** (12 months).

   | Menu | Service name to look for |
   |---|---|
   | 주식 | 유가증권 일별매매정보 |
   | 주식 | 유가증권 종목기본정보 |
   | 증권상품 | ETF 일별매매정보 |
   | 지수 | KOSPI 시리즈 일별시세정보 |

4. Wait for approval (usually within a day). Check **마이페이지 → 이용현황**: all four should
   say approved.

### 1.2 Public data portal key (recommended — needed for dividends)

1. Open <https://www.data.go.kr/>, sign up and log in.
2. Open these two pages and click **활용신청** (apply) on each:
   - Dividends: <https://www.data.go.kr/data/15043284/openapi.do>
   - Corporate events: <https://www.data.go.kr/data/15059609/openapi.do>
3. Go to **마이페이지 → 데이터활용 → Open API → 활용신청 현황**, open one of them and copy the
   **일반 인증키 (Decoding)**. The same key works for both.
4. A new key can take about an hour to start working.

### 1.3 GitHub token (required — lets Colab download this project's code)

The code is in a private GitHub repository, so Colab needs a token to read it.

1. Log in to <https://github.com>. Click your picture (top right) → **Settings** →
   **Developer settings** (bottom of the left menu) → **Personal access tokens** →
   **Fine-grained tokens** → **Generate new token**.
2. Name: `colab`. Expiration: your choice (e.g. 90 days).
3. **Repository access → Only select repositories** → choose `pinjoy99/qc-krx`.
4. **Permissions → Repository permissions → Contents → Read-only.** Nothing else.
5. Click **Generate token** and copy it (it starts with `github_pat_`). You can't see it again.

> **Keep keys private.** Never paste them into a chat, an email, a document or the code.
> Only put them in Colab's Secrets (next stage). If a key leaks, make a new one on the same site.

---

## Stage 2 — Download the data with Colab (no installation)

### 2.1 Open the notebook

1. Open <https://colab.research.google.com/> and sign in with your Google account.
2. **File → Open notebook → GitHub** tab. Tick **Include private repos** (allow access when
   asked). Choose the repository `pinjoy99/qc-krx` and open `notebooks/qc_krx_colab.ipynb`.
3. **File → Save a copy in Drive**, so you have your own copy. Use that copy from now on.

### 2.2 Add your keys as Secrets

1. Click the **key icon 🔑** in the left sidebar ("Secrets").
2. Click **Add new secret** three times and fill in:

   | Name (type exactly) | Value |
   |---|---|
   | `GITHUB_TOKEN` | the GitHub token from 1.3 |
   | `KRX_API_KEY` | the KRX key from 1.1 |
   | `DATA_GO_KR_KEY` | the data.go.kr key from 1.2 |

3. Switch on **Notebook access** for each of the three.

### 2.3 Run it

1. **Runtime → Run all.**
2. A window asks to connect to Google Drive. Choose your account and allow it.
3. Watch the output under each cell. Each step prints a line like `(11s)` when it finishes.

**How long?**
- **The first run takes a few hours**: it downloads every trading day since 2010 (one request
  per day for KOSPI and again for ETFs), plus the dividend and corporate-event tables.
  You can leave the browser tab open and come back. Colab may disconnect after a while; that's
  fine — just **Run all** again. It continues where it stopped and never downloads a day twice.
- **Later runs take about 5–10 minutes.**

**You're done when** the last cells print `done (…s)` and lines like `2026 … rows`.

### 2.4 If something goes wrong

| You see | What it means | What to do |
|---|---|---|
| `401 Unauthorized Key` | The KRX key is wrong | Check the `KRX_API_KEY` secret (no spaces) |
| `401 Unauthorized API Call` | A KRX service isn't approved yet | Wait for approval (1.1 step 4) |
| `SERVICE_KEY_IS_NOT_REGISTERED_ERROR` | data.go.kr key not active yet | Wait an hour; use the Decoding key |
| `exit code 1 … re-run to resume` | A step stopped (network, limit) | **Run all** again later |
| `rate limited … times in a row` | Yahoo is busy | Run again later (an hour or the next day) |
| `SecretNotFoundError` | A secret name is misspelled or access is off | Check names and **Notebook access** (2.2) |
| Git asks for a password / `Authentication failed` | GitHub token wrong or expired | Make a new token (1.3) |

---

## Stage 3 — Look at your data

Open Google Drive → **My Drive → qc-krx-data**. The useful files:

| File | What's inside | Open with |
|---|---|---|
| `combined/prices_2026.csv` (one per year) | Every stock and ETF, every day: date, code, name, open, high, low, close, volume | Google Sheets (double-click) |
| `securities.csv` | List of all securities, first and last trading day | Google Sheets |
| `index/KOSPI.csv`, `index/KOSPI200.csv` | Index levels per day | Google Sheets |
| `dividends.csv` | Every dividend | Google Sheets |
| `reports/verify_summary.csv` | How well KRX data matches the other sources | Google Sheets |
| `lean.zip` | Everything LEAN needs, in LEAN's folder layout (`data/equity/krx/…`) — for `klean init` / `klean data install` (Stage 4) | — |
| `raw/` | The original downloads. **Don't delete or edit.** | — |

Things to know:
- Prices are in **won** and **not adjusted** in these CSV files: Samsung shows 2,650,000 on
  2018-05-03 and 51,900 the next day because of its 1:50 split. LEAN adjusts them for you.
- A security whose last date in `securities.csv` is old has been **delisted**. It's kept on
  purpose: leaving out failed companies makes backtests look better than reality.

---

## Stage 4 — Your first backtest (optional, on your own computer, about 1 hour)

You'll run backtests in **Python** on your own computer with **klean**, a small tool that comes
with this project. It builds LEAN (QuantConnect's free, open-source backtesting engine) once and
then runs your strategies with it. **No Docker, no QuantConnect account, nothing to pay.** You
never write C#. The steps are for **Ubuntu**.

You need about **5 GB** of free disk space.

> Why not QuantConnect's own `lean` CLI? It needs a paid QuantConnect subscription (from about
> $10/month) and a large Docker image. If you have one, it works too: the project folders below run
> under `lean backtest` unchanged ([KLEAN.md](KLEAN.md), last section).

### 4.1 Install the tools

1. **Git, Python 3.11 and its library.** LEAN runs Python strategies with Python **3.11**
   exactly. Ubuntu 24.04 ships 3.12, so add the deadsnakes package source first:
   ```bash
   sudo apt install -y git python3-venv software-properties-common unzip
   sudo add-apt-repository -y ppa:deadsnakes/ppa      # not needed on Ubuntu 22.04 / Debian 12
   sudo apt install -y python3.11 python3.11-venv libpython3.11
   ```
2. **.NET 10** (LEAN is written in C#; you only need it to build LEAN):
   ```bash
   curl -sSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel 10.0
   echo 'export PATH=$HOME/.dotnet:$PATH' >> ~/.bashrc && source ~/.bashrc
   dotnet --list-sdks                                 # should show 10.0.something
   ```
3. **This project and klean.** It asks for your GitHub user name and password: paste your
   **GitHub token** from 1.3 as the password (nothing appears while you paste):
   ```bash
   cd ~
   git clone https://github.com/pinjoy99/qc-krx.git
   python3 -m venv ~/.klean/tools
   source ~/.klean/tools/bin/activate                 # run this again in every new terminal
   pip install -e ~/qc-krx
   klean --version
   ```

### 4.2 Build LEAN and the Python environment (once)

```bash
klean install-lean --dir ~/Lean                      # downloads and builds LEAN: 2–10 minutes
klean install-python --dir ~/.klean/py311            # Python 3.11 with pandas and numpy
```

"Build succeeded" with many yellow warnings is normal.

### 4.3 Make a workspace with the KRX data

From Google Drive, download `qc-krx-data/lean.zip` (say, to `~/Downloads`). Then:

```bash
klean init ~/krx-workspace --lean ~/Lean --python-venv ~/.klean/py311 --data-zip ~/Downloads/lean.zip
cd ~/krx-workspace
klean doctor                                         # every line should start with OK
```

The workspace is a folder with your projects and a `data/` folder that LEAN reads: the KRX
prices, adjustments, stock lists and indices, plus KRX's trading hours, holidays and the won
currency.

### 4.4 Run the example strategy

The example buys the 20 biggest KOSPI companies in equal amounts and rebalances every month
from 2011, paying Korean commissions and taxes.

```bash
cd ~/krx-workspace
klean project-create "KRX Top Market Cap"
cp ~/qc-krx/examples/python/krx_top_market_cap/main.py "KRX Top Market Cap/main.py"
klean backtest "KRX Top Market Cap"
```

The project folder holds two files: `main.py` (the strategy) and `krx_models.py` (the Korean
market rules: fees and taxes, price steps, the daily stock list and the KOSPI 200 benchmark).
That's all a KRX project needs.

The backtest takes several minutes. At the end klean prints the main statistics; everything
else is in `KRX Top Market Cap/backtests/<date and time>/`. Look for:

| Line | What it means | Reference result |
|---|---|---|
| `Compounding Annual Return` | Average yearly return | about 5.9% |
| `Drawdown` | Worst fall from a peak | about 40.8% |
| `Sharpe Ratio` | Return per unit of risk (higher is better) | about 0.20 |
| `Total Fees` | Commissions and taxes paid | about ₩44.7M on ₩1B |

The reference results come from the C# version of this strategy. The Python version uses the
same rules and gave identical results to C# on the same data (2023–2026, see EXPERT.md §4.4).

`KRX Top Market Cap/backtests/<date and time>/KrxTopMarketCapAlgorithm-log.txt` starts with
`CHECK tax …` and `CHECK tick …`: the tax rates and price steps the model uses on known dates.
Your numbers can differ slightly if your data is newer. **This is a test of the setup, not an
investment recommendation.**

### 4.5 Write your own strategy

Make a new project with `klean project-create "<name>"`: it already contains these lines in
`main.py`, with `krx_models.py` next to it. Every KRX strategy needs them:

```python
from AlgorithmImports import *
from krx_models import KrxBoards, krx_initialize, krx_benchmark


class MyKrxStrategy(QCAlgorithm):
    def initialize(self):
        self.set_time_zone("Asia/Seoul")      # KRX time
        self.set_account_currency("KRW")      # account in won
        self.set_start_date(2020, 1, 1)
        self.set_cash(100_000_000)            # ₩100M
        boards = KrxBoards.load()             # which code is KOSPI / ETF
        self.set_security_initializer(lambda s: krx_initialize(s, boards))   # fees, taxes, price steps
        self.set_benchmark(krx_benchmark("kospi200"))                       # compare with KOSPI 200
        self.samsung = self.add_equity("005930", Resolution.DAILY, Market.KRX).symbol

    def on_data(self, data):
        if not self.portfolio.invested:
            self.set_holdings(self.samsung, 0.9)
```

Rules to remember:
- Always pass **`Market.KRX`** and the 6-character code (`"005930"`, `"069500"`).
- Keep `krx_initialize` — without a fee model LEAN refuses the first KRX order
  (`unexpected equity Market krx`).
- Use `krx_benchmark("kospi200")`, not `set_benchmark("…")` with a symbol: the KRX index data is
  daily and LEAN would show an empty benchmark.
- Prices are adjusted for splits and dividends automatically.
- Use **`Resolution.DAILY`**. There is no minute data for now (see below).

Run it with `klean backtest "<project name>"`. To try settings without editing the code, read
them with `self.get_parameter("weight", "0.9")` and pass `--parameter weight 0.5`.

---

## Stage 5 — Keep the data up to date

| How often | What | Why |
|---|---|---|
| Every trading day or week | Open your notebook copy → **Run all** (5–10 minutes) | Adds the new days. KRX publishes a day's data the next afternoon, so run it after lunch. |
| After each update you want in LEAN | Download the new `lean.zip`, then in the workspace: `klean data install ~/Downloads/lean.zip` | LEAN reads its own copy in the workspace's `data/` folder. |

---

## Good to know before trusting results

- **Daily data only.** Minute prices were tried (from Yahoo) and removed: they stopped at 14:59
  (the market trades until 15:30), had volume spikes and prices that weren't real trades, and only
  went back 4 weeks. They'll come back when a better source is available.
- **Daily data comes only from KRX** and is checked against two other sources; on the overlap it
  matched exactly (see `reports/verify_summary.csv`).
- **About 13% of dividends** have no amount in the public data, so prices around those dates are
  adjusted slightly less than they should be.
- **Data use:** for personal, non-commercial use only. Don't sell or publish the data.

---

## FAQ

**Do I have to pay for anything?** No. The keys, Colab, Drive (the data fits in the free 15 GB),
LEAN and klean are free. (QuantConnect's own `lean` CLI needs a paid subscription; this guide
doesn't use it.)

**Does the notebook download everything every time?** No. It only downloads days it doesn't have.

**Can I run it on my phone?** Colab works in a phone browser, but use a computer for the first run.

**I closed the browser during the first run. Did I lose everything?** No. Everything downloaded
is already in Drive. Run all again and it continues.

**Can I use KOSDAQ stocks?** Not yet. It's planned for later (see `TODO.md`).

**Can I use this on QuantConnect's website?** No. Their cloud can't read your own data folder;
use LEAN on your computer as in Stage 4.

**Do I need C#?** No. Everything in this guide is Python. LEAN is written in C#, which is why
.NET is installed, but klean builds it for you. (`klean project-create --language csharp` makes
a C# project if you ever want one.)

**klean says something is missing.** Run `klean doctor` in the workspace: it checks .NET, the LEAN
build, the data and the Python environment and says what to fix. More in [KLEAN.md](KLEAN.md).

**A backtest failed.** klean shows the last lines of LEAN's output; the full output is in
`console.txt` in the project's newest `backtests/…` folder. `unexpected equity Market krx` means
the strategy has no KRX fee model (keep `krx_initialize`).

**`No module named krx_models`.** Keep `krx_models.py` in the same project folder as `main.py`
(`klean project-create` puts it there).

**Where do I find more detail?** [KLEAN.md](KLEAN.md) (all klean commands), [EXPERT.md](EXPERT.md) (everything on your own machine: local
pipeline, LEAN built from source, C# and Python), [GUIDE.md](GUIDE.md) (full step-by-step guide),
[AUDIT.md](AUDIT.md) (where every number comes from), [COMPONENTS.md](COMPONENTS.md) (how the
project is organised, in Korean), [TODO.md](../TODO.md) (what's next).

# qc-krx for beginners

This guide is for you if you have never used an API key, Google Colab, Python or LEAN.
It takes you from nothing to:

1. **Korean stock data in your Google Drive** (no installation, about 1 day including waiting
   for approvals), and
2. **your first backtest** in Python with the LEAN CLI and Docker on your own computer
   (optional, about 1 hour).

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
- **Yahoo Finance** gives 1-minute prices for a few stocks, for the last 4 weeks only.
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
| OHLCV | Open, High, Low, Close price and Volume of one day (or one minute). |
| Ticker / code | The 6-character KRX code of a security, e.g. `005930` = Samsung Electronics. |
| Split | A company divides each share into several (Samsung: 1 → 50 in 2018); the price drops by the same factor. |
| Adjusted price | Past prices recalculated so splits and dividends don't look like crashes. |
| Backtest | Running a trading rule on past data to see how it would have done. |
| Daily / minute bar | One row of OHLCV for one day / one minute. |
| Docker | A program that runs other software in a ready-made "container", so you don't install it yourself. |
| LEAN CLI | The `lean` command (`pip install lean`) that runs LEAN in Docker for you. |
| Workspace | The folder made by `lean init`: your projects plus a `data/` folder LEAN reads. |

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
| `lean.zip` | Everything LEAN needs (Stage 4) | — |
| `raw/` | The original downloads. **Don't delete or edit.** | — |

Things to know:
- Prices are in **won** and **not adjusted** in these CSV files: Samsung shows 2,650,000 on
  2018-05-03 and 51,900 the next day because of its 1:50 split. LEAN adjusts them for you.
- A security whose last date in `securities.csv` is old has been **delisted**. It's kept on
  purpose: leaving out failed companies makes backtests look better than reality.

---

## Stage 4 — Your first backtest (optional, on your own computer, about 1 hour)

You'll run backtests in **Python** with the **LEAN CLI**: a small program that runs LEAN for you
inside a **Docker** container (a ready-made box with LEAN and Python in it). You never build
LEAN or touch C#. The steps are for **Ubuntu**; macOS and Windows work the same once Docker
Desktop is installed.

You need **a lot of free disk space** for LEAN's Docker image (tens of GB) plus a few GB for the
data.

### 4.1 Install Docker, Python and the LEAN CLI

1. **Docker.** Follow <https://docs.docker.com/engine/install/ubuntu/>, then let your user run it
   without `sudo` and check it works:
   ```bash
   sudo usermod -aG docker $USER      # then log out and back in
   docker run hello-world             # should print "Hello from Docker!"
   ```
2. **Python and git** (Ubuntu usually has Python already):
   ```bash
   sudo apt install -y python3 python3-pip python3-venv git
   ```
3. **The LEAN CLI**, in its own Python environment:
   ```bash
   python3 -m venv ~/lean-env
   source ~/lean-env/bin/activate     # run this again in every new terminal
   pip install lean
   lean --version
   ```

### 4.2 Make a LEAN workspace

```bash
mkdir ~/lean-workspace && cd ~/lean-workspace
lean init                              # asks you to log in to a free QuantConnect account if needed
```

This creates `lean.json` and a `data/` folder. The first backtest also downloads LEAN's Docker
image, which takes a while once.

*Already have a workspace from `lean init`? Use it and skip this step.*

### 4.3 Put the KRX data into the workspace

1. Get this project's code (it asks for your GitHub user name and password: paste your **GitHub
   token** from 1.3 as the password; nothing appears while you paste):
   ```bash
   cd ~
   git clone https://github.com/pinjoy99/qc-krx.git
   source ~/lean-env/bin/activate     # the environment from 4.1
   pip install -r qc-krx/requirements.txt
   ```
2. From Google Drive, download `qc-krx-data/lean.zip`, then unzip it into a folder called
   `krxdata`, so that you have `~/krxdata/lean/equity/krx/daily/…`:
   ```bash
   mkdir -p ~/krxdata && unzip ~/Downloads/lean.zip -d ~/krxdata
   ```
3. Install it into your workspace's `data/` folder:
   ```bash
   cd ~/qc-krx
   python -m qc_krx --root ~/krxdata lean-install ~/lean-workspace/data
   ```
   You should see a line ending with `holidays: … from LEAN …`. This copies the KRX prices,
   corporate-action adjustments, universe files and KOSPI indices into `data/`, and teaches LEAN
   KRX's trading hours, holidays and the won currency.

### 4.4 Run the example strategy

The example buys the 20 biggest KOSPI companies in equal amounts and rebalances every month
from 2011, paying Korean commissions and taxes.

```bash
cd ~/lean-workspace
lean project-create --language python "KRX Top Market Cap"
cp ~/qc-krx/examples/python/krx_models.py "KRX Top Market Cap/"
cp ~/qc-krx/examples/python/krx_top_market_cap/main.py "KRX Top Market Cap/main.py"
lean backtest "KRX Top Market Cap"
```

The project folder now holds two files: `main.py` (the strategy) and `krx_models.py` (the
Korean market rules: fees and taxes, price steps, the daily stock list and the KOSPI 200
benchmark). That's all a KRX project needs.

The backtest takes several minutes. At the end LEAN prints **STATISTICS** lines (they're also
saved under `KRX Top Market Cap/backtests/`). Look for:

| Line | What it means | Reference result |
|---|---|---|
| `Compounding Annual Return` | Average yearly return | about 5.9% |
| `Drawdown` | Worst fall from a peak | about 40.8% |
| `Sharpe Ratio` | Return per unit of risk (higher is better) | about 0.20 |
| `Total Fees` | Commissions and taxes paid | about ₩44.7M on ₩1B |

The reference results come from the C# version of this strategy; the Python version uses the
same rules (its full 2011–2026 run hasn't been compared yet).

The first lines of the log show `CHECK tax …` and `CHECK tick …`: the tax rates and price steps
the model uses on known dates. Your numbers can differ slightly if your data is newer. **This is
a test of the setup, not an investment recommendation.**

### 4.5 Write your own strategy

Start every KRX strategy from these lines in `main.py` (with `krx_models.py` next to it):

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
- **Minute data** (Samsung, SK hynix, KODEX 200, last ~4 weeks): use
  `self.add_equity(code, Resolution.MINUTE, Market.KRX, fill_forward=False)` and don't trade after
  14:59. `examples/python/krx_minute_smoke_test/main.py` is a ready example (set its dates to the
  last weeks).

Run it with `lean backtest "<project name>"` as above.

---

## Stage 5 — Keep the data up to date

| How often | What | Why |
|---|---|---|
| Every trading day or week | Open your notebook copy → **Run all** (5–10 minutes) | Adds the new days. KRX publishes a day's data the next afternoon, so run it after lunch. |
| **At least every 3 weeks** | The same | Yahoo keeps 1-minute prices for only ~4 weeks. If you wait longer, the missed minutes are gone for good. |
| After each update you want in LEAN | Download the new `lean.zip`, unzip it over `~/krxdata` and run the `lean-install` command of 4.3 again | LEAN reads its own copy in the workspace's `data/` folder. |

---

## Good to know before trusting results

- **Minute data is for testing code, not for research.** It's for a few stocks only (Samsung
  Electronics, SK hynix, KODEX 200 by default), only the last 4 weeks, and Yahoo's data has gaps:
  - **No prices after 14:59.** The market trades until 15:30 (15:00–15:20 normal trading,
    15:20–15:30 closing auction). Don't backtest anything that trades at the close with minute
    data.
  - **Volumes have spikes** — sometimes one minute shows most of the day's volume.
  - **Some prices are not real trade prices** (they don't fit KRX's price steps).
- **Daily data comes only from KRX** and is checked against two other sources; on the overlap it
  matched exactly (see `reports/verify_summary.csv`).
- **About 13% of dividends** have no amount in the public data, so prices around those dates are
  adjusted slightly less than they should be.
- **Data use:** for personal, non-commercial use only. Don't sell or publish the data.

---

## FAQ

**Do I have to pay for anything?** No. All keys, Colab, Drive (the data fits in the free 15 GB),
the LEAN CLI and local backtests are free.

**Does the notebook download everything every time?** No. It only downloads days it doesn't have.

**Can I run it on my phone?** Colab works in a phone browser, but use a computer for the first run.

**I closed the browser during the first run. Did I lose everything?** No. Everything downloaded
is already in Drive. Run all again and it continues.

**Can I use KOSDAQ stocks?** Not yet. It's planned for later (see `TODO.md`).

**Can I use this on QuantConnect's website?** No. Their cloud can't read your own data folder;
use LEAN on your computer as in Stage 4.

**Do I need C#?** No. Everything in this guide is Python. (The project also has C# versions of
the examples, and GUIDE.md Part 5 builds LEAN from source; you don't need either.)

**`lean backtest` says it can't find `krx_models`.** Copy `krx_models.py` into the same project
folder as `main.py`.

**LEAN says `unexpected equity Market krx` or can't find market hours for `Equity-krx`.** The
fee model isn't set (keep `krx_initialize`) or `lean-install` wasn't run on this workspace's
`data/` folder (4.3).

**Where do I find more detail?** [GUIDE.md](GUIDE.md) (full step-by-step guide),
[AUDIT.md](AUDIT.md) (where every number comes from), [COMPONENTS.md](COMPONENTS.md) (how the
project is organised, in Korean), [TODO.md](../TODO.md) (what's next).

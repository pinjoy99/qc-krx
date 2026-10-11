# qc-krx for beginners

This guide is for you if you have never used an API key, Google Colab, Python or LEAN.
It takes you from nothing to:

1. **Korean stock data in your Google Drive** (no installation, about 1 day including waiting
   for approvals), and
2. **your first backtest** on your own computer (optional, about 1 hour).

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

LEAN runs on Windows, macOS or Linux. You need about 3 GB of free disk space.

### 4.1 Install three programs

1. **Git** — <https://git-scm.com/downloads> (Windows: keep all default options).
2. **Python 3.10 or newer** — <https://www.python.org/downloads/> (Windows: tick
   **Add python.exe to PATH** on the first installer screen).
3. **.NET 10 SDK** — <https://dotnet.microsoft.com/download> → .NET 10 → **SDK** for your system.

Open a terminal (Windows: **PowerShell**; macOS: **Terminal**) and check:

```bash
git --version
python --version        # on macOS/Linux it may be: python3 --version
dotnet --list-sdks      # should show 10.0.something
```

If one says "not found", restart the terminal (or the computer) and try again.

### 4.2 Download LEAN and this project, and build LEAN

Copy these lines one at a time into the terminal. Use a folder you can find again, e.g. your
home folder.

```bash
git clone --depth 1 https://github.com/QuantConnect/Lean.git
git clone https://github.com/pinjoy99/qc-krx.git
```

The second command asks for your GitHub user name and a password: paste your **GitHub token**
from 1.3 as the password (nothing appears while you paste; press Enter).

```bash
cd Lean
dotnet build Launcher/QuantConnect.Lean.Launcher.csproj -c Release
cd ..
```

This takes 2–10 minutes. **"Build succeeded"** at the end means it worked (many yellow
"warning" lines are normal).

### 4.3 Put the KRX data into LEAN

1. From Google Drive, download `qc-krx-data/lean.zip` into the folder that contains `Lean` and
   `qc-krx`.
2. Make a folder called `krxdata` there and unzip `lean.zip` into it. You should now have
   `krxdata/lean/equity/krx/daily/…`.
3. Install it into LEAN:

```bash
cd qc-krx
python -m pip install -r requirements.txt
python -m qc_krx --root ../krxdata lean-install ../Lean/Data
cd ..
```

You should see a line ending with `holidays: … from LEAN …`.

### 4.4 Run the example strategy

The example buys the 20 biggest KOSPI companies, in equal amounts, and rebalances every month
from 2011, paying Korean fees and taxes.

```bash
cp qc-krx/examples/KrxModels.cs qc-krx/examples/KrxTopMarketCapAlgorithm.cs Lean/Algorithm.CSharp/
cd Lean
dotnet build Launcher/QuantConnect.Lean.Launcher.csproj -c Release
cd Launcher/bin/Release
dotnet QuantConnect.Lean.Launcher.dll --algorithm-type-name KrxTopMarketCapAlgorithm --algorithm-language CSharp --algorithm-location QuantConnect.Algorithm.CSharp.dll --data-folder ../../../Data/ --close-automatically true
```

On Windows PowerShell, use this instead of the first (`cp`) line:
`copy qc-krx\examples\KrxModels.cs, qc-krx\examples\KrxTopMarketCapAlgorithm.cs Lean\Algorithm.CSharp\`.
On macOS/Linux, if `python` isn't found, type `python3` instead.

It runs in about a minute. At the end LEAN prints **STATISTICS** lines. Look for:

| Line | What it means | Reference result |
|---|---|---|
| `Compounding Annual Return` | Average yearly return | about 5.9% |
| `Drawdown` | Worst fall from a peak | about 40.8% |
| `Sharpe Ratio` | Return per unit of risk (higher is better) | about 0.20 |
| `Total Fees` | Commissions and taxes paid | about ₩44.7M on ₩1B |

Your numbers can differ slightly if your data is newer. **This is a test of the setup, not an
investment recommendation.**

### 4.5 Try your own idea

Open `Lean/Algorithm.CSharp/KrxTopMarketCapAlgorithm.cs` in any text editor, change something
small (for example `20` to `10` stocks), save, and run the two `dotnet` commands of 4.4 again.
GUIDE.md section 5.6 lists the settings every KRX algorithm needs.

---

## Stage 5 — Keep the data up to date

| How often | What | Why |
|---|---|---|
| Every trading day or week | Open your notebook copy → **Run all** (5–10 minutes) | Adds the new days. KRX publishes a day's data the next afternoon, so run it after lunch. |
| **At least every 3 weeks** | The same | Yahoo keeps 1-minute prices for only ~4 weeks. If you wait longer, the missed minutes are gone for good. |
| After each update you want in LEAN | Download the new `lean.zip` and repeat 4.3 | LEAN reads its own copy of the data. |

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

**Do I have to pay for anything?** No. All keys, Colab, Drive (the data fits in the free 15 GB) and LEAN are free.

**Does the notebook download everything every time?** No. It only downloads days it doesn't have.

**Can I run it on my phone?** Colab works in a phone browser, but use a computer for the first run.

**I closed the browser during the first run. Did I lose everything?** No. Everything downloaded
is already in Drive. Run all again and it continues.

**Can I use KOSDAQ stocks?** Not yet. It's planned for later (see `TODO.md`).

**Can I use this on QuantConnect's website?** No. Their cloud can't read your own data folder;
use LEAN on your computer as in Stage 4.

**Where do I find more detail?** [GUIDE.md](GUIDE.md) (full step-by-step guide),
[AUDIT.md](AUDIT.md) (where every number comes from), [COMPONENTS.md](COMPONENTS.md) (how the
project is organised, in Korean), [TODO.md](../TODO.md) (what's next).

# To-do

Ordered by priority. ✅ = done (kept for the record).

## Now

- [ ] **Reissue the API keys.** The KRX Open API key and the data.go.kr key were pasted into a chat
      session during development. Reissue both (KRX: 마이페이지 → API 인증키; data.go.kr: 마이페이지 →
      인증키 재발급) and update the Colab secrets `KRX_API_KEY` / `DATA_GO_KR_KEY`.
- [ ] **Get the remaining KRX services approved** and add them to the notebook settings:
      코스닥 / 코넥스 일별매매정보 (prices), 코스닥 / 코넥스 종목기본정보 (security info),
      KOSDAQ / KRX 시리즈 일별시세정보 (indices). Then run once with `REWRITE_ALL_YEARS = True`.
- [ ] **Write a KRX fee model for LEAN** (plan §8.3): broker commission (account-specific, e.g.
      0.015%) plus the sell-side securities transaction tax by year and market. Without it LEAN's
      default model throws `unexpected equity Market krx`.

## Next

- [ ] **KRX tick-size (price variation) model** (plan §8.3, §6.1): tick size by price band and market,
      with the 2023 reform; the data uses a fixed 1-won step.
- [ ] **Index data in LEAN format** (`index/krx/daily/*.zip`) so `SetBenchmark` can use KOSPI / KOSPI 200.
- [ ] **Test a Python LEAN algorithm** (requires LEAN's Python environment / pythonnet setup).
- [ ] **Speed up the Colab build** (~4 minutes): bundle each finished year's daily files into one file
      per year and market so the build reads ~50 files instead of ~13,000 over Drive.
- [ ] **Dividends with only a rate** (~13% since 2010): fill amounts from another source (e.g. DART
      dividend disclosures) or the historical par value, then include them in price factors.
- [ ] **Map preferred shares and delisted companies in `corporate_actions.csv`** (currently only the
      common share's code, via the dividend table). The KRX security master (`krx-info`) has ISINs.
- [ ] **Automate the daily run** (Colab scheduled notebook, or cron on a machine) in the afternoon KST;
      first confirm the exact time KRX publishes each day's data.

## Later (from the K-LEAN plan)

- [ ] Minute data source (plan §8.2, §9) — not available from these APIs.
- [ ] Fill / slippage / settlement (T+2) models, price-limit (±30%) fill rules (plan §8.3).
- [ ] KIS brokerage plugin for paper/live trading (plan §8.4, §10).
- [ ] Licensed data (KRX Data Marketplace / KOSCOM) for production use (plan §9.2).

## Done

- ✅ Scraper for aikstockdata.com (no key) — `3c0e42b`
- ✅ KRX Open API: prices (KOSPI, KOSDAQ, KONEX, ETF), indices, security master — `613783a`, `27971db`
- ✅ Full backfill 2010–2026 of KOSPI, ETF, KOSPI index family; verified — see `docs/AUDIT.md`
- ✅ Colab notebook storing data in Google Drive, incremental re-runs, step timings — `0041e1d` … `08162f7`
- ✅ Dividend history and corporate-action schedules from data.go.kr — `bd1057d`, `f5d07e2`
- ✅ LEAN factor files and map files, validated on 22k event days — `8fe4d26`
- ✅ `lean-install` (KRX equity market hours + symbol properties) and a LEAN backtest on real data — `70af60e`
- ✅ Step-by-step guide (`docs/GUIDE.md`), audit record (`docs/AUDIT.md`), this list

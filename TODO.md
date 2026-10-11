# To-do

Ordered by priority. ✅ = done (kept for the record).

## Now

- [ ] **Reissue the API keys.** The KRX Open API key and the data.go.kr key were pasted into a chat
      session during development. Reissue both (KRX: 마이페이지 → API 인증키; data.go.kr: 마이페이지 →
      인증키 재발급) and update the Colab secrets `KRX_API_KEY` / `DATA_GO_KR_KEY`.
- [ ] **Get the remaining KRX services approved** and add them to the notebook settings:
      코스닥 / 코넥스 일별매매정보 (prices), 코스닥 / 코넥스 종목기본정보 (security info),
      KOSDAQ / KRX 시리즈 일별시세정보 (indices). Then run once with `REWRITE_ALL_YEARS = True`.

## Next

- [ ] **Verify the pre-2023 KOSDAQ/KONEX tick table and the Jan–Oct 2010 tick table** against KRX's
      시행세칙 (see `docs/AUDIT.md` 2.3); confirm each tax change's exact effective trade date.
- [ ] **Slippage model** (plan §4.6) and a market-impact check for small caps; the strategy example has none.
- [ ] **Investigate LEAN's "Estimated Strategy Capacity ₩0"** in KRX backtests.
- [ ] **Universe flags** (plan §3.5): 관리종목 / 투자경고 / 거래정지, sector — need another source
      (KRX 정보데이터시스템 or KIND). Preferred-share detection beyond the code-ends-in-0 rule.
- [ ] **Python versions of the models** (`KrxModels.cs`) once LEAN's Python setup is tested.
- [ ] **Test a Python LEAN algorithm** (requires LEAN's Python environment / pythonnet setup).
- [ ] **Speed up the Colab build** (~4 minutes, more now that universe files are built): bundle each
      finished year's daily files into one file per year and market so the build reads ~50 files
      instead of ~13,000 over Drive; keep the built universe files on Drive between runs.
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
- ✅ Step-by-step guide (`docs/GUIDE.md`), audit record (`docs/AUDIT.md`), this list — `9d2337c`
- ✅ 4.1 KrxFeeModel (commission + sell tax by settlement date and market) and 4.2 KrxPriceVariationModel (tick sizes incl. 2023 reform) — `examples/KrxModels.cs`
- ✅ 2.4 Benchmark: KOSPI / KOSPI 200 index files for LEAN + `KrxIndex.Benchmark`
- ✅ 3.5 Universe: daily `universe/yyyyMMdd.zip` (market cap, trading value, shares) + `KrxUniverseData`
- ✅ First strategy backtest (KOSPI top 20 by market cap, 2011–2026) in LEAN, replicated independently in Python

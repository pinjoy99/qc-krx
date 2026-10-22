# To-do

Grouped by the three parts of the project (see `docs/COMPONENTS.md`), most urgent first in each.
WBS numbers refer to the K-LEAN plan. ✅ = done (kept for the record).

**Current scope:** KOSPI stocks and ETFs. KOSDAQ, KONEX and NXT are out of scope for now (items for
them are under "Later: scope expansion"). Daily bars: KRX only; aikstockdata and Yahoo daily bars:
cross-checks only. **No minute data** until a better source is available.

## Now (all parts)

- [ ] **Reissue the API keys.** The KRX Open API key and the data.go.kr key were pasted into a chat
      session during development. Reissue both (KRX: 마이페이지 → API 인증키; data.go.kr: 마이페이지 →
      인증키 재발급) and update the Colab secrets `KRX_API_KEY` / `DATA_GO_KR_KEY`.

## qc-krx-data — data pipeline

- [ ] **Thresholds for `verify`**: decide acceptable differences (e.g. aikstockdata must match
      exactly; Yahoo daily only around adjustment events) and make the notebook flag violations.
- [ ] **Universe flags** (3.5): 관리종목 / 투자경고 / 거래정지, sector — need another source
      (KRX 정보데이터시스템 or KIND). Preferred-share detection beyond the code-ends-in-0 rule.
- [ ] **Dividends with only a rate** (~13% since 2010): fill amounts from another source (e.g. DART
      dividend disclosures) or the historical par value, then include them in price factors.
- [ ] **Map preferred shares and delisted companies in `corporate_actions.csv`** (currently only the
      common share's code, via the dividend table). The KRX security master (`krx-info`) has ISINs.
- [ ] **Map files: code changes and mergers** (3.3) — currently first/last trading date only.
- [ ] **Speed up the Colab build** (~4 minutes, more now that universe files are built): bundle each
      finished year's daily files into one file per year and market so the build reads ~50 files
      instead of ~13,000 over Drive; keep the built universe files on Drive between runs.
- [ ] **Automate the daily run** (Colab scheduled notebook, or cron on a machine) in the afternoon KST;
      first confirm the exact time KRX publishes each day's data.
- [ ] **Automated data QA** (3.6): run the cross-checks in `docs/AUDIT.md` §3 after each build.
- [ ] Later: **minute data from a better source** (KIS API, purchased data; must include
      15:00–15:30 and the closing auction), then bring back the minute pipeline; licensed data (KRX Data Marketplace / KOSCOM) for
      production use (plan §9.2).

## qc-krx-market — market definition & models

- [ ] **Verify the pre-2023 KOSDAQ/KONEX tick table and the Jan–Oct 2010 tick table** (4.2) against
      KRX's 시행세칙 (see `docs/AUDIT.md` 2.3); confirm each tax change's exact effective trade date.
- [ ] **Slippage model** (4.6) and a market-impact check for small caps; the strategy example has none.
- [ ] **Fill model** (4.3): price limits (±30%), opening/closing single-price auctions, VI.
- [ ] **Settlement model** (4.4): T+2 sell proceeds.
- [ ] **KrxBrokerageModel** (4.5): supported order types, tick-size violations, short-selling rules.
      Needed before qc-krx-broker so backtests and live trading follow the same rules.
- [ ] **Market hours** (2.1): late opens (first trading day of the year, 수능일).
- [ ] **Investigate LEAN's "Estimated Strategy Capacity ₩0"** in KRX backtests.
- [ ] Later: upstream contribution (7.3) — `Equity-krx` market definition and KRX models as a
      QuantConnect/Lean PR.

## Later: scope expansion (KOSDAQ, KONEX, NXT)

- [ ] Get the KRX services approved: 코스닥 / 코넥스 일별매매정보, 종목기본정보, KOSDAQ / KRX 시리즈
      일별시세정보; add them to `KRX_MARKETS` and run once with `REWRITE_ALL_YEARS = True`.
- [ ] Verify the KOSDAQ/KONEX data with `verify` (aikstockdata covers KOSDAQ; Yahoo uses `.KQ`).
- [ ] NXT (alternative exchange, since 2025-03): find a data source; sessions (08:00–20:00) in
      market hours; how to combine KRX + NXT volume.

## klean-cli (optional tool)

Plan by phase, compared with the LEAN CLI: `docs/KLEAN-ROADMAP.md`.

- [ ] Research notebooks (Jupyter with LEAN's Python environment) and `klean optimize` (LEAN's
      Optimizer.Launcher), if needed.
- [ ] Package the KRX models with klean (today they're copied from the clone's `examples/`).
- [ ] macOS / Windows: test `install-python` (libpython lookup) and the launcher paths.

## qc-krx-broker — broker plugin (not started)

- [ ] Several strategies on one account: design written for IBKR (`docs/design/ibkr-multi-instance.md`); apply the same virtual-account ledger idea to KIS.
- [ ] Prerequisites: KIS Developers account, app key/secret, **paper-trading account**; decide how
      secrets are stored and masked in logs.
- [ ] 5.1 Authentication / token refresh (`Connect()`).
- [ ] 5.2 Orders: limit, market, conditional limit, best, IOC/FOK (`PlaceOrder` / `UpdateOrder` / `CancelOrder`).
- [ ] 5.3 Fills, holdings, cash (D+2) sync (`GetOpenOrders`, `GetAccountHoldings`, `GetCashBalance`).
- [ ] 5.4 Real-time quotes over WebSocket with subscription limits (`IDataQueueHandler`).
- [ ] 5.5 History provider with rate limiting (`IHistoryProvider`).
- [ ] 5.6 Reconnection and open-order resync; live-trading safeguards (plan §10.2), monitoring/alerts (6.3).

## Done

### qc-krx-data
- ✅ Scraper for aikstockdata.com (no key) — `3c0e42b`
- ✅ KRX Open API: prices (KOSPI, KOSDAQ, KONEX, ETF), indices, security master — `613783a`, `27971db`
- ✅ Full backfill 2010–2026 of KOSPI, ETF, KOSPI index family; verified — see `docs/AUDIT.md`
- ✅ Colab notebook storing data in Google Drive, incremental re-runs, step timings — `0041e1d` … `08162f7`
- ✅ Dividend history and corporate-action schedules from data.go.kr — `bd1057d`, `f5d07e2`
- ✅ LEAN factor files and map files, validated on 22k event days — `8fe4d26`
- ✅ 2.4 Benchmark data: KOSPI / KOSPI 200 index files for LEAN — `58f9804`
- ✅ 3.5 Universe: daily `universe/yyyyMMdd.zip` (market cap, trading value, shares) — `58f9804`
- ✅ Scope KOSPI + ETF; KRX the only daily source; `verify` against aikstockdata and Yahoo — `baafa70`
  (Yahoo minute bars were added there and removed again on the same day)

### qc-krx-market
- ✅ `lean-install` (KRX equity market hours + symbol properties) and a LEAN backtest on real data — `70af60e`
- ✅ 4.1 KrxFeeModel (commission + sell tax by settlement date and market) and 4.2 KrxPriceVariationModel (tick sizes incl. 2023 reform) — `58f9804`
- ✅ `KrxUniverseData`, `KrxIndex.Benchmark` (works around LEAN's hourly benchmark subscription) — `58f9804`
- ✅ First strategy backtest (KOSPI top 20 by market cap, 2011–2026) in LEAN, replicated independently in Python — `58f9804`
- ✅ Python versions of the models (`examples/python/krx_models.py`) for the LEAN CLI, tested in LEAN — `4141be7`
- ✅ C# vs Python parity on the top-20 strategy (2023–2026): identical results

### Documentation
- ✅ Step-by-step guide (`docs/GUIDE.md`), audit record (`docs/AUDIT.md`), this list — `9d2337c`
- ✅ Beginner's guide (`docs/BEGINNER.md`)
- ✅ Expert guide: local pipeline + local LEAN build, C# and Python (`docs/EXPERT.md`)
- ✅ klean-cli (optional tool in `tools/klean`): local LEAN workflow without Docker or a QuantConnect account (`docs/KLEAN.md`)
- ✅ Three-part project structure (`docs/COMPONENTS.md`) — `ced8ab5`

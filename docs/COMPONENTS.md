# qc-krx 구성: 세 부분

qc-krx 프로젝트는 세 부분으로 나뉩니다. 지금은 한 저장소(`pinjoy99/qc-krx`) 안에 있고,
이 문서는 각 파일과 작업이 어느 부분에 속하는지, 무엇이 끝났고 무엇이 남았는지를 정리합니다.

**현재 범위 (2026-10-11 결정)**
- 시장: **KOSPI 주식과 ETF만**. KOSDAQ·KONEX·NXT(대체거래소)는 이번 단계에서 다루지 않습니다
  (코드는 남겨 두지만 기본값에서 빠지고 검증하지 않음).
- 일봉: **KRX Open API가 유일한 소스**. aikstockdata.com과 Yahoo 일봉은 **검증용**(`verify`)으로만 씁니다.
- 분봉: **없음.** Yahoo 분봉을 한때 넣었다가, 15:00 이후 누락·거래량 급증·호가단위 밖 가격·28일 제한
  때문에 **더 나은 소스가 생길 때까지 프로젝트에서 뺐습니다** (2026-10-11).

```
            ┌──────────────────────────┐
 KRX Open API ─┐ (일봉)                  │  파일 (LEAN Data 폴더)
 data.go.kr ───┼─▶ qc-krx-data ──────────┼─▶ equity/krx/{daily, factor_files, map_files, universe}
 Yahoo ────────┤   (데이터 파이프라인)     │   index/krx/daily, securities.csv
 aikstockdata ─┘  (검증용)                │
                                          │
                   qc-krx-market ◀────────┘  (시장 정의·현실 모델: 데이터를 읽어 LEAN이 KRX를 "이해"하게 함)
                   (시장 정의·모델)
                        │  수수료·호가·체결 규칙 공유
                        ▼
                   qc-krx-broker
                   (증권사 연동: 모의/실거래)
```

- **qc-krx-data → qc-krx-market**: 파일로만 연결됩니다. 데이터 쪽은 LEAN `Data/` 폴더에 들어갈
  파일을 만들고(`lean-install`), 시장 쪽은 그 파일을 읽습니다. 서로의 코드를 호출하지 않습니다.
- **qc-krx-market → qc-krx-broker**: 백테스트와 실거래가 같은 수수료·호가 규칙을 쓰도록
  시장 쪽 모델(`KrxFeeModel`, `KrxPriceVariationModel`, 이후 `KrxBrokerageModel`)을 공유합니다.
- 상태 표시: ✅ 완료 · 🟡 일부 · ❌ 안 함. 괄호 안 번호는 K-LEAN 기획안 WBS 번호입니다.

---

## 1. qc-krx-data — 데이터 파이프라인

**목적**: 한국 시장 데이터를 모으고(원본 보존), LEAN이 읽는 형식으로 변환합니다.

**언어·실행 환경**: Python 3.10+ (`requests`, `yfinance`). 로컬 또는 Google Colab + Drive.

### 들어 있는 것

| 파일 | 역할 |
|---|---|
| `qc_krx/krx_api.py` | KRX Open API: 일별 시세(범위: KOSPI·ETF; KOSDAQ·KONEX 코드는 보존), 지수, 종목기본정보 |
| `qc_krx/dividends.py` | data.go.kr 배당 정보 → `dividends.csv` |
| `qc_krx/rights.py` | data.go.kr 권리일정(분할·증자·합병·상호변경…) → `corporate_actions.csv` |
| `qc_krx/yahoo.py` | Yahoo Finance 검증용 일봉. 호출 간격·429 대기·요청 한도 |
| `qc_krx/verify.py` | KRX 일봉을 aikstockdata·Yahoo와 대조 → `reports/verify_*.csv` |
| `qc_krx/scraper.py` | aikstockdata.com (검증용) |
| `qc_krx/client.py` | HTTP 공통 처리(재시도, 속도 제한, ETag) |
| `qc_krx/build.py` | KRX 원본 → `ohlcv/`, LEAN 일봉 zip, `securities.csv`, `index/` |
| `qc_krx/factors.py` | LEAN factor file(분할·증자 권리락·배당), map file(상장·폐지일) |
| `qc_krx/lean_extras.py` | LEAN용 지수 파일(KOSPI, KOSPI200), 일별 universe 파일, `securities.csv` 복사 |
| `qc_krx/cli.py` | `python -m qc_krx <명령>` |
| `notebooks/qc_krx_colab.ipynb` | Colab에서 실행, 결과는 Google Drive `qc-krx-data/` |
| `tests/test_build.py`, `test_krx_api.py`, `test_dividends.py`, `test_rights.py`, `test_factors.py`, `test_lean_extras.py`, `test_yahoo.py` | 단위 테스트 |

### 상태

| WBS | 항목 | 상태 | 내용 |
|---|---|---|---|
| 3.1 | 수집기 | 🟡 | 일봉: KOSPI·ETF 2010~2026 완료(상장폐지 종목 포함). 분봉·틱 없음(Yahoo 분봉은 품질 문제로 제외). KOSDAQ·KONEX·NXT는 범위 밖 |
| 3.2 | LEAN 포맷 변환기 | ✅ | 일봉 zip(가격 ×10,000) |
| 3.3 | Map File | 🟡 | 상장일·폐지일. 종목코드 변경·합병 이력은 없음 |
| 3.4 | Factor File | ✅ | KRX 기준가 조정비율(분할·병합·무상/유상증자·감자) + 현금배당. 시장 전체 검증(조정일 이상치 634 → 7) |
| 3.5 | Fundamental / Universe | 🟡 | 일별 시총·거래대금·상장주식수 universe 파일. 관리종목·업종 플래그 없음 |
| 3.6 | 데이터 QA·대사 | 🟡 | `verify`: aikstockdata 일봉 21,972건 KRX와 완전 일치, Yahoo 일봉 대조. 기준 초과 시 경고·실패 처리는 없음 |
| 2.4 | 벤치마크 데이터 | ✅ | KOSPI·KOSPI200 지수(LEAN 형식). KOSDAQ 지수는 승인 대기 |
| — | 배당·권리일정 | ✅ | data.go.kr 두 API, 매일·매주 갱신 |
| — | 운영 | 🟡 | Colab 1회 실행 약 5분+. 자동 스케줄 없음 |

### 남은 일

- (범위 확대 시) KOSDAQ·KONEX·NXT: API 승인 후 수집, 검증 (`KRX_MARKETS`에 추가, 한 번 `REWRITE_ALL_YEARS = True`)
- `verify` 결과에 기준(허용 차이) 두고 Colab 실행에서 경고
- 금액 없이 비율만 있는 배당(2010년 이후 약 13%) 보완 (DART 등)
- `corporate_actions.csv`의 우선주·상장폐지 회사 코드 매핑 (krx-info의 ISIN 활용)
- 관리종목·투자경고·거래정지·업종 플래그 (KRX 정보데이터시스템 / KIND)
- Colab 빌드 속도: 연도별 묶음 저장, universe 파일 Drive 보존
- 매일 자동 실행 (KRX 데이터 공개 시각 확인 후)
- 분봉 데이터: 더 나은 소스 확보 후 다시 추가 (기획안 §9: KIS API, 데이터 구매)
- 운영 단계: 정식 라이선스 데이터(KRX Data Marketplace / KOSCOM)

---

## 2. qc-krx-market — 시장 정의·현실 모델

**목적**: LEAN이 KRX 주식을 올바르게 다루게 합니다. 거래 시간·휴장일, 원화, 호가단위,
수수료·세금, 종목 선택(universe), 벤치마크.

**언어·실행 환경**: LEAN 설정 파일(JSON/CSV) + C# (LEAN 알고리즘 프로젝트에 복사).
.NET 10, LEAN 소스 빌드(Docker 불필요).

### 들어 있는 것

| 파일 | 역할 |
|---|---|
| `qc_krx/lean_install.py` | LEAN `Data/`에 설치: `Equity-krx-[*]` 장 시간·휴장일, `krx,[*],equity,,KRW,1,1,1` 심볼 속성, 데이터 파일 복사 |
| `examples/KrxModels.cs` | `KrxFeeModel`(수수료+거래세+농특세, 결제일 기준), `KrxPriceVariationModel`(호가단위, 2023 개편 전후), `KrxUniverseData`(시총 universe), `KrxIndex`(일봉 벤치마크), `KrxBoards`(종목→시장) |
| `examples/KrxTopMarketCapAlgorithm.cs` | 전략 백테스트: KOSPI 시총 상위 20, 월간 리밸런싱, 2011~2026 |
| `examples/KrxSmokeTest.cs` | 데이터 검증용 테스트(분할·배당·상장폐지 이벤트) |
| `examples/python/krx_models.py`, `examples/python/krx_top_market_cap/main.py` | 같은 모델·전략의 Python 버전 (LEAN CLI + Docker용; `main.py` 옆에 `krx_models.py`만 두면 됨) |
| `tests/test_lean_install.py` | 설치기 테스트 (C# 모델은 LEAN 실행으로 검증) |

### 상태

| WBS | 항목 | 상태 | 내용 |
|---|---|---|---|
| 2.1 | market-hours-database | 🟡 | KRX 정규장 09:00–15:30, 휴장일(LEAN 목록 ∪ 데이터, 일치 확인). 수능일 지연 개장 없음. NXT는 범위 밖 |
| 2.2 | symbol-properties-database | ✅ | KRW, lot 1. 호가단위는 4.2 모델이 담당 |
| 2.3 | Symbol 체계 | 🟡 | 6자리 단축코드(영문 포함 코드 지원) ↔ ISIN(krx-info). LEAN SecurityIdentifier는 map file로 생성 |
| 2.4 | 벤치마크 | ✅ | `KrxIndex.Benchmark("kospi200")` (LEAN이 벤치마크를 시간봉으로 구독하는 문제 우회) |
| 4.1 | KrxFeeModel | ✅ | 위탁수수료(기본 0.015%) + 매도세(2019~2026 세율 변경 반영, ETF 면제) |
| 4.2 | KrxPriceTickModel | 🟡 | 2023-01-25 전후 표. 2023 이전 코스닥·코넥스 표와 2010년 1~10월은 원문 미확인 |
| 4.3 | KrxFillModel | ❌ | 상·하한가, 단일가, VI |
| 4.4 | KrxSettlementModel | ❌ | T+2 |
| 4.5 | KrxBrokerageModel | ❌ | 주문유형 검증, 공매도 규정 |
| 4.6 | 슬리피지 | ❌ | |
| 7.2 | 샘플 전략 | 🟡 | 시총 상위 20 전략: CAGR 5.89%, MDD 40.8%, 베타 0.82 (Python 독립 재현 6.36%, 수수료 제외) |

### 남은 일

- 4.2 호가단위표 원문(한국거래소 시행세칙) 확인, 세율 변경 시점 확인
- 4.6 슬리피지 모델 (거래량 기반), 소형주 시장충격 점검
- 4.3 체결 모델: 상·하한가(±30%) 미체결, 시가·종가 단일가
- 4.4 T+2 결제(매도 대금 사용 시점)
- 4.5 KrxBrokerageModel: 지원 주문유형, 호가단위 위반 주문 처리, 공매도 규정
- 2.1 수능일·연초 지연 개장 (NXT 세션은 범위 확대 시)
- LEAN "Estimated Strategy Capacity ₩0" 원인 조사
- Python 버전 모델 + LEAN Python 환경 테스트
- 업스트림 기여(7.3): `Equity-krx` 시장 정의·KRX 모델을 QuantConnect/Lean에 PR

---

## 3. qc-krx-broker — 증권사 연동 플러그인

**목적**: LEAN 알고리즘이 한국 증권사 계좌로 모의/실거래를 하게 합니다.
기획안 1차 대상은 **한국투자증권 KIS Developers** (REST + WebSocket, 모의투자 제공).

**언어·실행 환경**: C# (LEAN 브로커리지 플러그인 구조, `Lean.Brokerages.Template` 준수).

### 상태: ❌ 시작 전

아직 코드가 없습니다. 데이터·시장 모델이 먼저였고, 백테스트 결과를 본 뒤 진행하는 순서입니다.

### 할 일 (기획안 §8.4 기준)

| WBS | 항목 | LEAN 인터페이스 | 내용 |
|---|---|---|---|
| 5.1 | 인증·토큰 | `Connect()` | KIS 접근토큰 발급·갱신 (유효기간·발급 빈도 제한 확인 필요) |
| 5.2 | 주문 | `PlaceOrder` / `UpdateOrder` / `CancelOrder` | 지정가, 시장가, 조건부지정가, 최유리, 최우선, IOC/FOK |
| 5.3 | 체결·잔고·예수금 | `GetOpenOrders`, `GetAccountHoldings`, `GetCashBalance` | 재시작 시 동기화, D+2 예수금 구분 |
| 5.4 | 실시간 시세 | `IDataQueueHandler` | WebSocket 체결가·호가, 세션당 구독 수 제한 대응 |
| 5.5 | 히스토리 | `IHistoryProvider` | 일봉·분봉 조회, 초당 호출 제한 대응 |
| 5.6 | 장애 복구 | — | 재연결, 미체결 재동기화 |

### 시작 전 준비

- KIS Developers 가입, 앱키·시크릿 발급, **모의투자 계좌**
- 비밀정보 관리 방식 정하기 (Colab/로컬 환경변수, 로그 마스킹) — 기획안 §7.2 원칙 5
- qc-krx-market의 4.5 `KrxBrokerageModel`을 먼저 만들어 백테스트와 실거래 규칙을 맞추기
- 라이브 운영 안전장치(기획안 §10.2), 모니터링·알림(6.3)

---

## 저장소를 실제로 나눌 경우

지금은 나눌 필요가 크지 않습니다. 세 부분이 파일로만 연결되고, 아직 qc-krx-broker 코드가 없습니다.
나눈다면 다음처럼 옮기면 됩니다.

| 새 저장소 | 옮길 것 |
|---|---|
| `qc-krx-data` | `qc_krx/` (lean_install 제외), `notebooks/`, 해당 `tests/`, `docs/GUIDE.md` 1~4부, `docs/AUDIT.md` 1~3절 |
| `qc-krx-market` | `qc_krx/lean_install.py`, `examples/`, `tests/test_lean_install.py`, `docs/GUIDE.md` 5부 |
| `qc-krx-broker` | 새로 시작 (C# LEAN 브로커리지 플러그인) |

나누는 시점은 qc-krx-broker를 시작할 때, 또는 시장 모델을 QuantConnect/Lean에 올리기(7.3) 직전이 적당합니다.

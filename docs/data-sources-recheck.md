# 추가 금융지표 수집 재검토

검토일: **2026-10-11**. 공식 제공자 문서와 실제 읽기 전용 응답을 구분해서 확인했다. 현재 벤치마크는 **14개 설정 / 3개 활성화(EURUSD·USDJPY·UST10Y)** 그대로다. 이번 작업은 계정 생성, 유료 신청, 공급자 연락, 라이선스 수락, 공개 데이터 업로드를 하지 않았다.

**우선 확장할 수 있는 후보는 ECB 환율 5개와 미국 국채 만기 3개다.** 기존 허용 피드에서 실제 최신 관측과 충분한 길이를 확인했다. 기존 14개 중 다른 목표를 이들로 바꾸지 않는다. 특히 ECB 기준 USDKRW는 서울 종가와 다르고, EIA WTI 현물은 최근월물 선물 결제가격과 다르다.

## 기존 지표별 다음 단계

| 지표 | 현재 수집 가능성 / 이번 확인 | 필요한 것 |
|---|---|---|
| EURUSD, USDJPY | ECB 무키 XML 실제 응답 정상. 10월 9일 관측 확인 | 기존 출처 표기·교차환율 변환 설명 유지. 매일 직전 필요 세션이 도착했는지 확인 |
| UST10Y | Treasury 무키 XML 실제 응답 정상. 10월 9일 관측 확인 | 기존 국채 관측시각·SIFMA 휴장/단축장 적용. 공식 보장 게시 SLA로 간주하지 않음 |
| KOSPI, KOSDAQ | ECOS 또는 KRX 공식 API 경로 존재. 인증 관측 미수집 | 개인 소유 ECOS 키, 또는 KRX 키와 두 API 서비스별 승인. 정확한 항목·종가·게시시각과 공개/장기보관 범위 확인 |
| USDKRW | ECOS의 정확한 일별 벤치마크 미확정 | 키 + 항목 메타데이터. 15:30 스냅샷인지 전체 시장 종가인지 먼저 확정. XKRX 달력 그대로 활성화 불가 |
| KTB3Y, KTB10Y | ECOS 원생산기관/수익률 정의 미확정 | 키 + 만기별 항목. KOFIA 오후 최종호가수익률이면 관측 16:00·발표 16:30 KST이며 기존 15:30 설정 수정 필요 |
| S&P 500 | FRED `SP500`은 정확한 일별 가격지수지만 저작권 표시와 재배포 사전허가 조건 존재 | FRED 경로 선택 시 `FRED_API_KEY`와 S&P의 해당 사용 허가. 장기 원장·예측분포·오차 통계·다운로드 허용 범위를 별도 확인 |
| Nasdaq Composite | FRED `NASDAQCOM`은 종합지수 일별 종가, Nasdaq 저작권 표시 | FRED 키만으로 공개 권리 확보 안 됨. Nasdaq 또는 정식 벤더의 공개/파생사용 범위 확인. Nasdaq-100으로 대체하지 않음 |
| WTI 최근월물 결제가격 | CME의 데이터/파생/비표시 사용 라이선스 체계 확인. 웹 페이지 열람은 TSFM 사용권이 아님 | AI 사용을 포함한 허가된 결제가격 피드, 계약 선택·롤 규칙, 확정 게시시각. EIA 현물은 별도 신규 지표 후보 |
| Gold USD/oz | LBMA PM 등 구체적인 벤치마크를 먼저 선택해야 함 | LBMA/IBA 선택 시 역사·실시간 취득/사용/재배포 라이선스. PM 경매는 런던 15:00 시작이며 경매 시작을 확정 게시시각으로 대체하지 않음 |
| VIX | Cboe 공식 CSV 경로는 기존 어댑터에 구현. 오늘 대량 다운로드는 하지 않음 | 저장·공개 파생사용 허가와 CSV 일별 최종값 게시시각. `return_only`는 자동 허가가 아님 |
| BTCUSDT (USD 대용) | Binance Vision의 구체적인 비상업 조건을 새로 확인. 현재 비활성 유지 | 아래 비상업/동일조건변경허락·API 적용범위 검토. USD와 USDT 구분, 22:00–23:00 UTC 완성 봉 확정 유지 |

한국 지표의 공식 링크, ECOS/KRX 신청 절차와 시간 정의는 [한국 데이터 요건](korea-source-requirements.md)에 정리했다. 2026년 하반기 정부의 외환시장 24시간화 정책 일정은 확인했지만 실제 개시 공지·현재 운용 달력·ECOS 항목 적용은 검증되지 않았다. 정책 발표만으로 시장 운영이 이미 바뀌었다고 단정하지 않는다.

미국 주가지수의 근거는 [FRED SP500 원출처·허가 안내](https://fred.stlouisfed.org/series/SP500), [NASDAQCOM 원출처·정의](https://fred.stlouisfed.org/series/NASDAQCOM), [FRED API 키 요건](https://fred.stlouisfed.org/docs/api/api_key.html)이다. 키 발급은 데이터 권리 허가와 별개다.

CME는 [라이선스 종류](https://www.cmegroup.com/market-data/license-data.html)와 [웹 데이터 고지](https://www.cmegroup.com/trading/market-data-explanation-disclaimer.html)에서 사용 범위를 구분한다. 후자는 웹 데이터의 AI/ML 사용도 제한하므로 무허가 웹 수집을 우회 경로로 채택하지 않았다. [LBMA 안내](https://www.lbma.org.uk/prices-and-data/lbma-precious-metal-prices)는 IBA 라이선스와 경매시각을 명시한다. [Cboe 고지](https://www.cboe.com/global-disclaimers/) 및 [역사 데이터 계약 안내](https://datashop.cboe.com/data-policies)는 공개 CSV의 존재만으로 본 프로젝트의 저장·재배포 권리를 확정할 수 없음을 보여 준다. 공급자의 구체적 승인 범위를 확보하는 것이 다음 단계다.

## 키 없이 검증한 신규 후보 8개

| 신규 ID | 정확한 정의 | 실제 확인한 수준 관측 수 | 최신 관측 시각(UTC) |
|---|---|---:|---|
| `gbpusd_ecb` | ECB EURUSD ÷ EURGBP, USD/GBP | 509 | 2026-10-09 14:00 |
| `audusd_ecb` | ECB EURUSD ÷ EURAUD, USD/AUD | 509 | 2026-10-09 14:00 |
| `usdcad_ecb` | ECB EURCAD ÷ EURUSD, CAD/USD | 509 | 2026-10-09 14:00 |
| `usdchf_ecb` | ECB EURCHF ÷ EURUSD, CHF/USD | 509 | 2026-10-09 14:00 |
| `usdkrw_ecb` | ECB EURKRW ÷ EURUSD, KRW/USD; 서울 종가와 다름 | 509 | 2026-10-09 14:00 |
| `ust2y` | Treasury daily par yield `BC_2YEAR`, 연율 % | 444 | 2026-10-09 19:30 |
| `ust5y` | Treasury daily par yield `BC_5YEAR`, 연율 % | 444 | 2026-10-09 19:30 |
| `ust30y` | Treasury daily par yield `BC_30YEAR`, 연율 % | 444 | 2026-10-09 19:30 |

ECB는 같은 날짜의 양쪽 기준환율을 사용한다. [공식 기준환율 페이지](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html)는 TARGET 영업일과 통상 16시 갱신을 설명하고, [재사용 조건](https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html)은 정확한 출처 표기와 변환 사실의 설명을 요구한다. 여기의 교차환율은 계산값이며 별도 시장의 종가가 아니다.

국채는 [Treasury 공식 XML 안내](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed)에 따른 동일 par yield 피드의 다른 만기다. 기존 UST10Y와 같은 정부 통계 출처 평가를 적용하되 단위는 가격이 아닌 연율 수익률이다. `diff_bp` 변환 시 1%p = 100bp를 유지한다. [금리 통계 방법론](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics)은 곡선/산출 방식의 근거이며, HTTP 응답 수신 시각을 과거 공식 게시 시각으로 꾸미지 않는다.

위 수치는 **이번에 확인한 기간 내 수준 데이터 개수**다. 300개 변화값에는 최소 301개 수준값이 필요하다. 최신값 존재와 관측 수만으로 300/512 연속 문맥, 과거 당시 게시 여부, 모델 적합성을 보증하지 않는다. 활성화 전 독립 ID·단위·변환·어댑터·문맥 연속성·예측 마감 검증을 수행해야 한다. 이번에는 기존 14개 벤치마크 구성을 바꾸지 않았다.

## 암호화폐 및 원유 대안의 구체적 조건

- **Binance Vision:** [공식 저장소 약관](https://github.com/binance/binance-public-data/blob/master/TERMS_AND_CONDITIONS.md), 2026-08-26판은 비상업 연구/오픈소스 평가를 CC BY-NC-SA 4.0 조건으로 허용하고 파생물 출처 표기·동일조건변경허락을 요구한다. 상업적 활용에는 별도 서면 계약이 필요하다. 기존 코드/데이터의 포괄 라이선스와 충돌하지 않도록 산출물 범위를 정하고, `data-api.binance.vision` 봉에 대한 적용범위를 확인해야 한다. [공식 REST 안내](https://developers.binance.com/en/docs/products/spot/rest-api)는 공개 시장 데이터 전용 엔드포인트를 명시한다. 무키 접속 가능 여부와 목적별 이용 조건은 분리해서 판단한다.
- **Coinbase BTC-USD:** [시장 데이터 약관](https://www.coinbase.com/legal/market_data), 2026-08-07판 §3은 외부 공개 파생물뿐 아니라 **AI/ML 검증·벤치마킹·운용**도 사전 명시적 서면 동의 대상으로 둔다. 따라서 키 없는 BTC-USD API를 개인 TSFM 검증이나 공개 사이트의 자동 대안으로 쓰지 않았다. 필요한 다음 단계는 해당 목적을 포함한 Coinbase 허가다.
- **Kraken BTC/USD:** [글로벌 약관](https://www.kraken.com/legal/global-terms) §8–9의 자체 이용 범위·제3자 제공 제한을 넘어서는 공개 사용 허가가 필요하다. 기술적으로도 [OHLC API](https://docs.kraken.com/api-reference/market-data/get-ohlc-data)는 최근 720개 봉까지만 반환하고 마지막 봉은 미완성이다. 1시간 봉으로는 약 30일뿐이므로 23:00 UTC 종가 300일 문맥을 바로 구성할 수 없다. 허가된 역사 봉의 별도 확보와 완성 봉 필터가 필요하다.
- **EIA WTI 현물:** [EIA API 문서](https://www.eia.gov/opendata/documentation.php)는 무료 개인 API 키를 요구한다. `petroleum/pri/spt`, `RWTC`는 [Cushing WTI 현물](https://www.eia.gov/dnav/pet/TblDefs/pet_pri_spt_tbldef2.asp)로 최근월물 결제가격과 다르다. [EIA 재사용 페이지](https://www.eia.gov/about/copyrights_reuse.php)는 출처/게시일 표기와 배포를 폭넓게 허용하지만 해당 표는 원자료 제공자를 Refinitiv/LSEG로 밝힌다. 공개 파생사용에 적용되는 항목별 범위를 확인하고, 별도 `wti_spot_eia` ID·관측/게시 달력을 설계할 후보로 남겼다. 무료 키만으로 현재 `wti`를 활성화하지 않는다.

## 매일 다시 확인하는 코드

`pipeline` 디렉터리에서 실행한다. 출력 디렉터리는 공개 저장소 밖이어야 한다.

```powershell
.\.venv\Scripts\python.exe -m tsfm_live.source_probe --output-dir '..\..\..\work\source-probe' --network
```

`--network`를 생략하면 외부 요청 없이 설정과 필요한 자격증명 **존재 여부만** 조사한다. Python 호출은 `run_probe(output_dir, network=False, now=None)`이다. 네트워크 모드도 ECB 전체 XML 한 번과 Treasury 전년/당년 XML 두 번만 요청한다. 비활성 제공자·인증 API는 호출하지 않는다. 소켓 I/O 타임아웃 12초, 요청당 최대 2회, 응답 크기 16MiB 제한을 적용한다. 이는 전체 실행의 엄격한 벽시계 제한이 아니다. 일별 실행기의 요청/모델 작업 제한과 구분되며, 선택적인 Windows 예약 작업을 설치한 경우에는 그 작업의 1시간 제한도 적용된다.

보고서는 외부 폴더에 변경 불가능한 고유 이름 JSON과 원자적으로 교체하는 `latest.json`으로 남는다. 주요 필드:

| 필드 | 의미 |
|---|---|
| `checked_at_utc`, `endpoints[].fetched_ts_utc` | 검사 시작 기준시각과 실제 응답 수신시각 |
| `indicators[]`, `candidates[]` | 기존 14개와 별도 신규 후보 8개. `auto_enabled`는 항상 false |
| `collection_status` | `not_checked`, `blocked_not_requested`, `fresh`, `lagging`, `source_error`, `no_observations` |
| `latest_close_ts`, `expected_close_ts`, `next_close_ts` | 검증한 관측·필요 직전 세션·다음 세션. 휴일과 DST 반영 |
| `history_observations_checked`, `minimum_301_levels_present` | 검사 기간의 수준 개수와 최소 길이 조건 |
| `missing_sessions_in_checked_span` | 검사한 첫 관측부터 필요 직전 세션까지 빠진 세션 수. 전체 문맥 검증 대체 아님 |
| `required_credentials` | 환경변수 이름·존재 여부. 비밀값 없음; 키가 있어도 자동 활성화 안 함 |
| `endpoints[].body_sha256`, `bytes` | 응답 증거. 가격이나 원시 응답 본문은 보고서에 저장하지 않음 |

`fresh`는 관측 세션이 맞는다는 뜻이며 공개 가능한 새 예측이 생성되었다는 뜻이 아니다. 게시시각이 없는 피드의 `publication_timestamp_available`은 false다. 전년/당년만 확인하는 국채 검사는 연초에는 301개 미만을 반환할 수 있으므로 전체 역사 길이의 부족으로 단정하지 않는다. CLI 종료코드 0은 보고서 저장 성공을 의미한다. 호출자는 활성 지표의 `collection_status`를 읽어 실패/지연을 구분해야 한다.

## 실제 확인 결과와 한계

2026-10-11 **06:07:41–43 UTC**에 공식 세 응답을 수신했다. ECB는 8,196,871바이트, Treasury 2025년은 345,104바이트, 2026년은 301,948바이트였다. 활성 3개와 후보 8개 모두 10월 9일 관측까지 도착했다. ECB 다음 필요 세션은 10월 12일, UST는 Columbus Day 휴장을 반영해 10월 13일이다. 초기 제한된 네트워크 환경에서는 `source_error`였고, 허용된 공식 피드 읽기 실행에서 성공했다. 오류 보고서를 성공으로 덮어쓰지 않고 각각 보존했다.

최종 필드로 **06:12:04–05 UTC**에 재확인한 보고서에서도 같은 결과였으며 신규 후보 8개 모두 `minimum_301_levels_present=true`, `missing_sessions_in_checked_span=0`이었다. 비공개 실행 증거는 작업공간 `work/source-probe/20261011T061129525694Z-7ef65e41.json`에 있다. 응답 SHA-256은 ECB `7ddf0f32a828b2b4778e4200389a2cd6cdb63e685b9477be256a732e9e771e9d`, Treasury 2025 `2ce4091c4a7d0368225407c0f824e83136b88e9686514047492fad4d4936c4f0`, 2026 `2c4090f084618a16b4f56f25119e1c81a001283f039e72599c5f050843858584`였다.

단위검증 9개와 Ruff 검사를 통과했다. 검증은 오프라인 무요청, 키 비노출, 비활성 제공자 무요청, 같은 원본 공유, 휴일, 미완성 시각 제외, 중복·손상·지연·누락, 외부 출력 강제와 제한된 재시도를 포함한다. 이 재검토는 추가 모델 추론, 실시간 예측 공표, 365일 전체 TSFM 평가를 실행하지 않았다.

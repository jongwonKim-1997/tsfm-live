# 시간별 데이터 소스 — 2026-10-11 확인

## 무료 공개 연결: Coin Metrics Community

공개용 소스로 Coin Metrics Community의 `btc`·`eth`, `ReferenceRateUSD`, `frequency=1h`를 선택했다. API 키와 유료 구독이 필요 없다. 표시 이름은 BTC/USD·ETH/USD **시간별 기준가격**이다. 거래소 OHLC 종가, 업비트 KRW 가격, USD/USDT 가격을 서로 대체하거나 이어 붙이지 않는다.

공개 사용의 근거는 [Community Data 안내](https://docs.coinmetrics.io/packages/coin-metrics-community-data)가 Reference Rates Community를 포함해 연결하는 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)이다. 비상업적 복제·공개·가공을 허용하며 출처, 라이선스 링크, 가공 사실을 표시해야 한다. 자세한 운영 범위는 [공개 데이터 이용 조건](public-data-licensing.md)에 정리했다. 유료 Pro 상품의 계약 조건을 Community에 적용한 판단이 아니다.

### 확인한 응답과 제공 범위

2026-10-11 09:21:01 UTC에 아래 무키 요청이 HTTP 200을 반환했다. BTC와 ETH 각각 **169개**, `2026-10-04T09:00Z`부터 `2026-10-11T09:00Z`까지였고 다음 페이지는 없었다. 같은 날 `PriceUSD`의 `1h` 요청은 403이어서 `ReferenceRateUSD`를 사용한다. 이는 당시 실측 기록이며 상시 제공량 보증이 아니다.

```text
GET https://community-api.coinmetrics.io/v4/timeseries/asset-metrics
    ?assets=btc,eth&metrics=ReferenceRateUSD&frequency=1h
    &start_time=2026-09-01&page_size=2000
```

[Community 설명](https://docs.coinmetrics.io/packages/coin-metrics-community-data)은 세밀한 Reference Rates의 이력을 “last 7 data points”라고 설명하지만, 위 응답은 169개였다. 따라서 무료 API가 항상 7일·600시간을 제공한다고 전제하지 않는다. 허용되는 응답만 이용하고 권한·이력 제한을 우회하지 않는다. [API v4 문서](https://docs.coinmetrics.io/api/v4/)가 구분하는 무료 호스트 `community-api.coinmetrics.io`를 사용하며, Community 호출 제한은 IP당 6초 동안 10회다.

### 시각과 모델 입력

- [ReferenceRateUSD 정의](https://docs.coinmetrics.io/market-data/reference-rates-overview/reference_rate)의 `time`은 기준가격 계산 시각이다. 산정에는 기준 시각 전 60분부터 후 1분까지의 관측창이 사용되고 계산은 약 5분 뒤부터 시작된다. 정각에 이미 알려진 값이라고 가정하지 않는다. 실제 수집 시각도 따로 기록한다.
- 공개 연결의 입력 정책은 연속 관측 **최소 128개**, 모델 입력 **최대 512개**다. 초기에는 확보된 연속 구간으로 시작하고, 주기 수집분을 로컬에 누적해 최근 최대 600개 관측을 유지하는 방식으로 연결한다. 초기부터 512개를 확보했다고 표시하지 않는다.
- 모든 모델은 같은 지표의 동일한 이용 가능 과거 구간으로 다음 24시간의 가격 수준을 직접 예측한다. 사전학습 가중치를 고정한 zero-shot 추론이며 추가 학습·파인튜닝은 하지 않는다. 입력 길이는 실행 결과에 기록한다.
- 시간 누락을 보간하거나 직전 값으로 채우지 않는다. 미래 시각·중복·비정상 값·불연속 입력·오래된 최신값은 수집 및 추론 검증 대상으로 삼는다. 수집 실패를 가상의 가격으로 채우지 않는다.

**진행 상태:** Coin Metrics 어댑터, 최소 128개 초기 입력 및 최대 600개 관측 누적을 구현·검증했다. 실제 실행 `20261011T092916411724Z-7765bbbf`는 2026-10-11 09:29:16.411724–09:31:21.647539 UTC에 로컬 CPU에서 완료됐다(125.235815초). BTC·ETH 각각 169개 관측을 입력했고, 7개 모델 × 2개 지표의 14개 추론이 모두 성공해 24시간씩 총 336개 예측 시점을 생성했다. 차트의 실제값 표시 구간은 지표별 168개다. 운영 상태는 작업공간 `work/tsfm-hourly-dashboard`에 보관한다. 공개 내보내기에는 Coin Metrics 두 지표만 포함되며 개인용 Upbit 데이터는 제외했다. 현재 이 스냅샷의 저장소 배포를 준비 중이며, Cloudflare 관리 화면의 브라우저 접근 차단으로 KV 자동 업로드는 아직 연결하지 못했다. 로컬 추론 성공을 공개 배포나 매시간 자동 업로드 성공으로 간주하지 않는다. 기존 `hourly-dashboard-smoke.json`의 Upbit 결과와 이번 Coin Metrics 실행 결과는 별개다.

## 기존 개인 로컬 소스: Upbit

업비트 BTC/KRW·ETH/KRW의 완료된 60분 캔들 연결은 개인 로컬 분석용이다. [시세 API](https://docs.upbit.com/kr/reference/api-overview)는 무키이며 주문·계좌 API를 사용하지 않는다. [캔들 API](https://docs.upbit.com/kr/reference/list-candles-minutes)는 요청당 최대 200개, `to` 이전 구간을 반환하므로 3페이지로 최대 600개를 받는다. `candle_date_time_utc`는 시작 시각이며 차트의 종료 시각은 시작 + 1시간이다. `timestamp`는 업데이트 시각으로 실제 응답에서 종료 경계보다 수십 ms 늦을 수 있다.

수집 시작 시 경계를 고정해 미완료 봉을 제외한다. 없는 시간의 캔들은 채우지 않으며 [호출 제한](https://docs.upbit.com/kr/reference/rate-limits)을 지킨다. [업비트 이용 안내](https://www.upbit.com/historical_data/download?prefix=candle%2FKRW-POKT%2Fmonthly%2F60m%2F2026)는 개인 PC 보관·전략 분석과 외부 제공을 구분한다. 기존 연결은 `public_export: false`이며 원자료·예측·차트를 GitHub·Cloudflare 공개 스냅샷에서 제외한다. Coin Metrics의 라이선스를 Upbit 데이터에 적용하지 않는다.

추가 공개 허가 요청 초안은 작업공간의 `outputs/upbit-data-permission-request.txt`에 별도로 준비했다. **외부 발송이나 승인 수령은 아직 하지 않았다.** 무료 Coin Metrics 공개 연결은 Upbit 허가 회신을 기다릴 필요가 없다.

## 다른 무료 후보와 미확인 범위

| 후보 | 확인한 내용 | 연결 상태 |
| --- | --- | --- |
| [CoinGecko Demo](https://docs.coingecko.com/demo/reference/coins-id-market-chart-range) | 무료 키, 최근 365일 내 시간별 가격. BTC·ETH 600시간을 요청할 수 있는 문서상 범위 | 대체 후보. 출처 있는 웹사이트 사용을 [공식 FAQ](https://support.coingecko.com/hc/en-us/articles/4538761098521-Can-I-use-CoinGecko-data-and-screenshots-for-my-website-book-etc)가 허용. 키 발급·실제 수집·장기 보관 정책은 아직 적용하지 않음 |
| [Kraken OHLC](https://docs.kraken.com/api-reference/market-data/get-ohlc-data) | 60분, 최근 최대 720개. 마지막 미확정 봉 제외 필요 | 공개 차트·데이터 제공 권한을 이번에 확정하지 못해 공개 연결하지 않음 |
| [Binance market-data API](https://developers.binance.com/en/docs/products/spot/faqs/market_data_only) | 무키 1시간 klines | [archive 이용 조건](https://github.com/binance/binance-public-data/blob/master/TERMS_AND_CONDITIONS.md)의 live API 적용 범위를 확정하지 못해 공개 연결하지 않음 |

주식·주가지수·FX·금리에서 **무료 최신 시간별 수집과 공개 표시를 함께 충족하는 소스는 이번 확인에서 확정하지 못했다.** ECB 기준환율과 미 재무부 par yield는 일간 발표 자료이므로 시간별 값으로 늘리지 않는다. 향후 후보는 종목, 실제 관측 주기, 지연, 거래시간, 공개 이용 조건을 함께 확인한다.

# 시간별 데이터 소스 — 2026-10-11 확인

## 현재 로컬 연결

업비트 BTC/KRW와 ETH/KRW의 완료된 60분 캔들을 사용한다. USD 시세나 기존 ECB 환율·국채 수익률의 대체 지표라고 표시하지 않는다. 두 거래쌍은 24시간 거래되지만 API 장애·무거래·누락이 있으면 예측 대상에서 숨긴다.

- [공식 Quotation API](https://docs.upbit.com/kr/reference/api-overview)는 시세 조회에 인증키가 필요하지 않다. 주문·계좌 API는 사용하지 않는다.
- [60분 캔들 API](https://docs.upbit.com/kr/reference/list-candles-minutes)는 요청당 최대 200개, `to` 이전 구간을 반환한다. 3페이지로 최대 600개를 받고 모델 입력은 최근 최대 512개다.
- `candle_date_time_utc`는 시작 시각이다. 그래프는 시작 + 1시간을 종료 시각으로 사용한다. `timestamp`는 업데이트 시각이며 실제 응답에는 종료 경계보다 수십 ms 늦은 값도 있다.
- 수집 시작 시 정각 경계를 고정하고 진행 중인 봉을 제외한다. 캔들이 없는 시간을 보간하거나 직전 가격으로 채우지 않는다. 최근 입력 구간에 시간 누락이 있거나 최신 종료봉이 없으면 해당 지표를 숨긴다.
- [호출 제한](https://docs.upbit.com/kr/reference/rate-limits)을 지켜 페이지 사이에 간격을 두며, 실패 재시도에도 기존 HTTP 요청 예산을 적용한다.

[업비트 이용 안내](https://www.upbit.com/historical_data/download?prefix=candle%2FKRW-POKT%2Fmonthly%2F60m%2F2026)는 개인 PC 보관·본인 전략 분석과 공개 제공을 구분한다. [공식 Strategy Toolkit](https://docs.upbit.com/kr/docs/upbit-strategy-toolkit)도 개인 분석·백테스트 흐름을 제공한다. 이 구현은 개인 로컬 분석 범위로 구성했다. 원자료와 그 데이터를 이용한 예측·차트 모두 `public_export: false`로 설정하며 GitHub·Cloudflare 스냅샷에서 제외한다. TSFM Live의 공개 데이터 라이선스를 이 소스에 적용하지 않는다.

## 환율·주가·금리 연결에 필요한 항목

ECB 기준환율과 미 재무부 par yield는 일간 발표 자료이므로 시간봉을 만들어내지 않는다. 시간별 환율·주가지수를 추가하려면 해당 주기 API를 제공하는 소스와 키, 이용 가능한 종목, 지연 시간, 거래소 시간표, 로컬 분석/공개 표시 권한을 확인해야 한다. 지수와 ETF, 현물과 선물, USD와 USDT는 구분한다.

| 후보 | 시간별 기능 | 이번 적용 |
| --- | --- | --- |
| [Twelve Data](https://twelvedata.com/pricing) | 키를 사용하는 intraday 시계열 | 키·종목 권한 확인 필요. 공개 표시는 [별도 이용 조건](https://twelvedata.com/terms) 확인 후 연결 |
| [Kraken OHLC](https://docs.kraken.com/api-reference/market-data/get-ohlc-data) | 60분, 최근 최대 720개; 마지막 미확정 봉 제외 필요 | [Global Terms](https://www.kraken.com/legal/global-terms)의 제3자 제공 제한 때문에 공개 소스로 활성화하지 않음 |
| [Binance market-data API](https://developers.binance.com/en/docs/products/spot/faqs/market_data_only) | 무키 1시간 klines | [archive 데이터 조건](https://github.com/binance/binance-public-data/blob/master/TERMS_AND_CONDITIONS.md)이 live API에도 적용되는지 확인 전 공개 사용 보류 |

기술적 접근 성공과 공개 배포 허용은 별개의 확인 항목이다. 현재 공개 홈페이지에는 시간별 소스 대기 상태를 표시하며, 개인 데이터로 빈 공개 그래프를 채우지 않는다.

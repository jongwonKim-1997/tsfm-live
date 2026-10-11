# 공개 데이터 이용 조건

확인일: 2026-10-11. TSFM Live는 무료 비상업 연구·시각화 사이트로 운영하는 범위에서 아래 소스를 사용한다. 데이터 출처별 권리는 분리하며, 이 문서나 프로젝트 코드 라이선스로 제3자 데이터의 권리를 새로 부여하지 않는다.

## Coin Metrics Community — 공개 사용 근거

[Coin Metrics Community Data 공식 안내](https://docs.coinmetrics.io/packages/coin-metrics-community-data)는 Community Metrics와 Reference Rates Community를 포함하며 [Creative Commons Attribution-NonCommercial 4.0 International](https://creativecommons.org/licenses/by-nc/4.0/)로 연결한다. 적용 대상은 무료 Community API에서 제공받는 `btc`·`eth`의 시간별 `ReferenceRateUSD`다. 유료 Pro 데이터나 별도 계약 상품을 가져오는 연결이 아니다.

CC BY-NC 4.0은 비상업적 복제·공유·가공을 허용한다. 따라서 조건을 지킨 실제 가격 차트, 로컬 계산, 예측·오차 시각화의 공개에 이 라이선스를 근거로 삼는다. 모델은 고정된 사전학습 가중치로 zero-shot 추론만 수행한다. 데이터 라이선스와 별개로 각 모델 가중치의 이용 조건도 유지한다. 원자료와 모델 출력은 구분하며 Coin Metrics가 예측을 산출·승인·보증한 것으로 표시하지 않는다.

공개 차트와 배포 데이터에 다음 내용을 함께 유지한다.

- 출처: **Coin Metrics Community**, 지표 **ReferenceRateUSD**, 자산 **BTC 또는 ETH**, 관측 주기 **1h** 및 USD 단위.
- [공식 Community 안내](https://docs.coinmetrics.io/packages/coin-metrics-community-data)와 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) 링크.
- 변경 설명: TSFM Live가 기간 선택·형식 정리·차트 표시를 수행하고, 예측·오차는 모델 및 평가 코드가 계산했다는 사실. 추가 변환이 있으면 그 내용도 고지.
- 제공된 저작권·라이선스·면책 고지를 유지하고, 해당 라이선스가 허용한 이용을 다시 막는 추가 조건을 붙이지 않음.

표시 문구 예시:

> Source: Coin Metrics Community — ReferenceRateUSD (BTC/ETH, hourly USD reference rates), CC BY-NC 4.0. Selected and formatted by TSFM Live. Forecasts and error metrics are calculated by TSFM Live; Coin Metrics does not endorse them.

위 문구에서 출처와 라이선스명에는 앞의 공식 링크를 연결한다. 기준가격은 거래소 OHLC 종가가 아니며 데이터 변환·예측 곡선·후속 실제값을 구별한다. 수집 응답, 입력, 산출물의 보관·공유에도 동일한 출처·비상업 조건을 유지한다. 라이선스는 API 이력 범위나 가용성을 보증하지 않으므로 실측된 제공량과 품질 검증은 [시간별 소스 문서](hourly-data-sources.md)에서 별도로 다룬다.

현재 범위는 광고·유료 구독·판매 목적이 없는 공개 연구 사이트다. 광고, 유료화, 상업 고객용 제공 등 운영 목적을 바꾸기 전에 비상업 조건과 새 사용 범위를 다시 확인한다. 조건을 준수한 비상업 공개 연결을 위해 별도의 유료 계약을 먼저 구할 필요는 없다. 세부 권리·의무는 [라이선스 법률 전문](https://creativecommons.org/licenses/by-nc/4.0/legalcode.en)을 따른다.

## Upbit — 개인 로컬 분석, 공개 제외

기존 Upbit KRW-BTC·KRW-ETH 연결의 `public_export`는 `false`다. 개인용 관측값과 그 값으로 만든 예측·오차를 공개 스냅샷에 포함하지 않는다. 공개 허가 요청 문안은 별도로 준비했지만 발송·승인은 하지 않았다. 문의 초안을 만들었다는 사실은 허가를 얻었다는 뜻이 아니다.

공식 [Open API 기술지원 안내](https://docs.upbit.com/kr/page/upbit_open_api_support)는 데이터 요청·제휴를 기술지원 범위에서 제외한다. 요청은 [고객센터 1:1 문의 안내](https://support.upbit.com/hc/ko/articles/900006527463--%EC%83%81%EB%8B%B4-1-1%EB%AC%B8%EC%9D%98-%EB%B0%8F-%EC%B9%B4%EC%B9%B4%EC%98%A4%ED%86%A1-%EC%83%81%EB%8B%B4-%EB%B0%A9%EB%B2%95)에 따라 데이터 공개 이용 담당자에게 전달하도록 준비한다. Data Lab 등 다른 서비스의 공개 조건을 Quotation API에 자동 적용하지 않는다.

## CoinGecko Demo — 무료 대체 후보

[공식 재사용 FAQ](https://support.coingecko.com/hc/en-us/articles/4538761098521-Can-I-use-CoinGecko-data-and-screenshots-for-my-website-book-etc)는 출처를 표시한 웹사이트·연구보고서에서 데이터 사용을 허용한다. [Demo 시간별 API](https://docs.coingecko.com/demo/reference/coins-id-market-chart-range)는 최근 365일을 지원하며, [가격표](https://www.coingecko.com/en/api/pricing)의 무료 한도는 월 10,000호출이다. BTC·ETH를 매시간 각각 한 번 호출하면 30일 기준 약 1,440호출이다. [무료 키 설정](https://docs.coingecko.com/docs/setting-up-your-api-key) 후 연결할 수 있는 대안이며 아직 활성화하지 않았다.

[API 약관](https://www.coingecko.com/en/api_terms)은 사이트 통합을 허용하고 API 접근 재배포를 제한한다. 저장 시 캐시를 최소 24시간마다 갱신하도록 권고하며 접근 종료 시 저장 데이터 삭제 조건을 둔다. 따라서 대체 연결 시 현재 차트의 표시용 캐시와 영구 보관 데이터를 분리하고, 장기 기록 정책을 해당 조건에 맞춰 정해야 한다. 이 조건을 AI 추론의 포괄적 금지로 해석하지 않는다. 현재 연구 범위에서 추가 학습은 하지 않는다.

외부 연락·약관 수락·키 발급·구독은 이 문서 작업에서 수행하지 않았다.

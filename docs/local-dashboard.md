# 시간별 실제값과 로컬 zero-shot 예측

기본 실행은 정각 기준의 시간별 관측값을 수집하고, 각 모델이 향후 24시간의 값을 한 번에 예측한다. 로컬 HTML에서 실제값은 실선, 모델별 24개 중앙값은 점선으로 연결한다. 기본 과거 구간은 한국 시간 오늘이며 오늘/최근 7일 버튼은 과거 구간만 바꾼다. 축과 상세 정보는 KST 날짜·시간을 표시한다.

현재 기본 지표는 Coin Metrics Community BTC/USD·ETH/USD 시간별 기준가격이다. 거래소의 시간봉 종가와 구분하며, 일간 ECB 환율·국채 수익률을 시간별 값으로 보간하지 않는다. [소스와 이용 범위](hourly-data-sources.md)를 참고한다. 업비트 설정은 비활성·비공개로 보존한다.

## 실행

설치된 7개 TSFM의 CPU 가중치로 추론한다. 학습·미세조정·원격 추론 API·추가 가중치 다운로드를 실행하지 않는다.

```powershell
.\pipeline\.venv\Scripts\python.exe ops\update_dashboard.py --runtime-env-file ..\..\work\model-smoke\runtime.env
# 실제값만 갱신
.\pipeline\.venv\Scripts\python.exe ops\update_dashboard.py --runtime-env-file ..\..\work\model-smoke\runtime.env --observations-only
# 종전 일간 진단을 명시적으로 실행
.\pipeline\.venv\Scripts\python.exe ops\update_dashboard.py --runtime-env-file ..\..\work\model-smoke\runtime.env --frequency 1d --no-site --report-output ..\tsfm-daily-dashboard.html
```

`ops/run-dashboard.ps1`도 같은 기능을 제공한다. Windows PowerShell 스크립트 실행이 제한되면 위 Python 명령을 사용한다. `--check-only`는 런타임 확인, `--no-site`는 사이트 스냅샷 갱신 생략, `--state-dir`는 저장소 밖 기록 경로 지정, `--report-output`은 사용자에게 보이는 HTML 경로 지정이다.

기본 기록은 작업 폴더의 `work/tsfm-hourly-dashboard`에 둔다.

- `reports/index.html`, `reports/latest.json`: 최신 개인 그래프와 데이터.
- `runs/<ID>/forecast.json`, `dashboard.json`, `cache/`: 실제 생성 시각의 예측 및 입력 문맥.
- `latest-run.json`, `attempts/`: 수집·추론 성공/실패 상태.
- 작업 폴더의 `outputs/tsfm-live-dashboard.html`: 매 실행에 원자적으로 교체되는 사용자용 보고서. 열린 문서는 5분마다 새로고침한다.

## 예측과 시간 검증

입력은 최근 최대 512개의 연속된 시간별 관측값이다. 무료 소스의 초기 약 7일 내역부터 시작하며, 실제 사용한 길이를 `context_length`로 표시한다. 매시간 수집 내역을 저장해 최대 600개까지 누적한다. 기존 일간 변화량 벤치마크와 별도로 가격 수준을 직접 예측하며 `forecast_basis: direct_level`로 기록한다. 각 미래 시간의 10%·90% 분위수는 그 시간의 80% 주변 구간이다. 24시간 전체 경로가 동시에 포함될 확률이라는 뜻은 아니다.

추론 전 최신 정각 관측과 소스별 최소 입력 수를 확인한다(Coin Metrics 128개, 기존 Upbit 300개). 미래 값·미확정 관측·중복·누락·지연 또는 미확인 시장 시간표가 있으면 해당 지표를 숨긴다. 누락값을 보간하거나 다른 소스로 채우지 않는다. 추론 완료 시 이미 지난 목표 시각은 삭제하며, 다음 시간에 들어가 원자료가 뒤처졌다면 현재 그래프에 노출하지 않는다. 프런트에서도 마지막 실제값으로부터 75분이 지난 항목을 숨긴다.

소스는 최신인데 모델 실행만 실패한 경우에는 실제값을 유지하고 예측 실패 상태를 표시한다. 모델당 최대 120초, 전체 추론 예산 600초이며 중복 실행은 잠금으로 건너뛴다. 공개 확정 벤치마크 원장은 변경하지 않는다. 모든 로컬 결과는 `public_ledger_eligible: false`다.

## 자동 갱신

`TSFM-Local-Dashboard` 작업은 매시 10분에 Python GUI 실행기로 수집·추론·HTML 갱신을 수행하도록 구성한다. 기준가격이 정각 직후 계산·발행될 시간을 확보한다. PC가 켜져 있고 사용자가 로그인한 상태여야 한다. 실행 중이면 중복 작업을 시작하지 않는다.

```powershell
# 다른 컴퓨터에서 설치 전 정의 확인
.\ops\configure-daily-task.ps1 -Runner Dashboard -TaskName TSFM-Local-Dashboard -RuntimeEnvFile ..\..\work\model-smoke\runtime.env
# 새 작업 설치
.\ops\configure-daily-task.ps1 -Runner Dashboard -TaskName TSFM-Local-Dashboard -RuntimeEnvFile ..\..\work\model-smoke\runtime.env -Action Install
```

기존 작업을 자동으로 덮어쓰지는 않는다. 현재 작업의 변경 시에는 실행 파일·인수를 확인한 후 트리거를 갱신한다. Windows 정책 변경이나 유료 클라우드를 사용하지 않는다.

사이트용 JSON은 `public_export: true`인 시간별 소스만 포함한다. Coin Metrics의 두 항목은 포함하고 업비트 데이터는 제외한다. 공개 페이지는 60초마다 최신 JSON을 읽으며, standalone 로컬 HTML은 네트워크 polling 없이 기존 5분 새로고침을 사용한다. 자동 업로드 코드는 구현했지만 Cloudflare KV 바인딩과 전용 토큰 설정은 아직 필요하다. [공개 자동 갱신 설정](public-hourly-updates.md)을 참고한다.

과거 일간 21개 예측의 실행 증거는 `local-dashboard-smoke.json`에 그대로 보존하며 시간별 추론의 증거로 재사용하지 않는다.

## 현재 컴퓨터 실측

2026-10-11 18:29:16–18:31:21 KST에는 무료 Coin Metrics BTC/USD·ETH/USD 각 169개 입력으로 14/14 모델 실행에 성공했다. 향후 24시간 예측점은 총 336개이며 실행 시간은 125.24초였다. 실제 HTML의 오늘/7일 전환과 두 지표 선택을 실행해 각 19개/168개 실제값과 7개 예측 선을 확인했다. [Coin Metrics 실행 증거](coinmetrics-hourly-smoke.json)를 보관했다. 매시 10분 예약과 다음 실행 19:10 KST를 확인했다. 공개 자동 업로드는 별도 설정 전이다.

아래는 소스 전환 전 업비트의 최초 실행 기록이다.

2026-10-11 17:49:10–17:51:32 KST에 실제 7개 모델을 실행했다. BTC/KRW·ETH/KRW 각 600개 시간봉을 수집하고, 2개 지표 × 7개 모델 × 24시간 = 336개 예측점을 모두 생성했다. 총 141.79초이며 모델 실패는 0개였다. [숫자값을 제외한 실행 증거](hourly-dashboard-smoke.json)를 보관했다. 작업 스케줄러 Ready, 24개 트리거, 다음 실행 18:05 KST도 확인했다. 이는 최초 실측이며 장기간 연속 운영 성과를 뜻하지 않는다.

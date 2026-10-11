# 실제값과 로컬 zero-shot 예측 그래프

홈페이지의 첫 그래프는 `site/public/api/v1/local_dashboard.json`이 있으면 검증된 로컬 스냅샷을 읽습니다. 각 지표의 확정 일별 실제값은 실선, 마지막 실제값에서 다음 시장 관측일로 이어지는 모델별 중앙값은 점선입니다. 기본 화면은 최근 7일이며, 상단에서 오늘/최근 7일을 바꿀 수 있습니다. 일별 데이터의 오늘 모드에는 실제 관측점 하나만 표시합니다.

## 실행

현재 컴퓨터에 설치된 7개 TSFM과 CPU 가중치를 사용합니다. 학습·미세조정·원격 추론 API를 호출하지 않습니다. 저장소 루트의 PowerShell에서 실행합니다.

```powershell
.\ops\run-dashboard.ps1 -RuntimeEnvFile ..\..\work\model-smoke\runtime.env
# 데이터만 수집하고 실제값 그래프 갱신 (모델을 실행하지 않음)
.\ops\run-dashboard.ps1 -RuntimeEnvFile ..\..\work\model-smoke\runtime.env -ObservationsOnly
```

Windows PowerShell에서 `.ps1` 실행이 제한된 경우에는 설치된 Python을 직접 실행합니다.

```powershell
.\pipeline\.venv\Scripts\python.exe ops\update_dashboard.py --runtime-env-file ..\..\work\model-smoke\runtime.env
```

`-CheckOnly`는 기존 환경과 가중치만 검사합니다. `-NoSite`는 웹사이트 소스 JSON을 쓰지 않고 개인 보고서만 생성합니다. `-StateDir`로 저장소 밖의 개인 기록 경로를 지정할 수 있습니다. 기본 기록 경로는 이 작업의 `work/tsfm-local-dashboard`입니다.

- `reports/index.html`: 네트워크 없이 열 수 있는 실제값·예측 선 그래프.
- `reports/latest.json`: 그래프용 최신 스냅샷.
- `runs/<실행 ID>/`: 실제 생성 시각의 예측 결과·그래프 스냅샷과 입력 문맥.
- `latest-run.json`, `attempts/`: 수집·추론·내보내기 상태.

실행은 수집 → 런타임 확인 → 각 활성 지표에 대해 7개 TSFM 추론 → JSON/HTML 갱신 순서입니다. 중복 실행은 잠금으로 건너뜁니다. 데이터와 모델 오류는 사유를 남기며, 관측값이 있으면 예측이 없어도 실제값 곡선을 보여 줍니다. `-ObservationsOnly` 실행은 기존 예측을 재활용하지 않으므로 해당 스냅샷에는 실제값만 있습니다.

## 날짜와 의미

수집한 날과 원래 관측일을 구분합니다. 휴일에 금요일 실제값을 받았다고 일요일 값으로 바꾸지 않습니다. 수집 시각·마지막 실제 관측일·예측 생성 시각·목표일을 표시합니다. 오늘 값이 아직 발표되지 않았거나 원자료가 지연되면 상태를 표시하고 확인되지 않은 값을 만들지 않습니다.

예측은 수집된 전체 확정 이력 중 최대 512개 과거 변화량을 입력으로 사용하는 1단계 zero-shot 출력입니다. 입력 전체가 그래프의 최근 7일로 제한되는 것은 아닙니다. 내일이 휴장일이면 목표는 다음 실제 시장 관측일입니다. 예측 생성 중 목표 시각이 지나면 유효한 미래 예측으로 표시하지 않습니다.

이 실행기는 실제 현재 시각으로 실행되며, 기존 벤치마크의 08:10–08:48 시작 제한을 적용하지 않습니다. 기존 `run-daily.ps1`과 공개 원장의 시간·증거·평가 규칙은 변경하지 않습니다. 로컬 스냅샷은 `local_zero_shot`, `public_ledger_eligible: false`로 표시하며 공개 확정 벤치마크·누적 성과로 편입하지 않습니다.

현재 활성 지표는 ECB EUR/USD, ECB에서 계산한 USD/JPY, 미국 재무부 10년 국채 수익률입니다. 기준환율은 체결 종가와 구분해야 합니다. 단위·출처 표기를 유지하며, 별도 조사한 후보 8개는 이 변경으로 활성화되지 않습니다.

## 매일 갱신

기존 작업 스케줄러 스크립트에 그래프 실행 모드를 추가했습니다. 아래 첫 명령은 작업 정의만 출력합니다.

```powershell
.\ops\configure-daily-task.ps1 -Runner Dashboard -TaskName TSFM-Local-Dashboard -RuntimeEnvFile ..\..\work\model-smoke\runtime.env
.\ops\configure-daily-task.ps1 -Runner Dashboard -TaskName TSFM-Local-Dashboard -RuntimeEnvFile ..\..\work\model-smoke\runtime.env -Action Install
```

등록 시 매일 06:10·08:10·23:10 KST에 실행합니다. 현재 사용자가 로그인해 있고 컴퓨터가 실행 가능한 상태여야 합니다. UTC·서머타임·시장별 발표 지연 때문에 매 실행에 새 관측값이 생긴다고 보장하지 않습니다. 원자료가 늦으면 다음 실행에서 다시 수집합니다.

그래프 작업은 설치된 `pythonw.exe`로 Python 실행기를 직접 호출합니다. 콘솔 창을 표시하지 않으며, Windows PowerShell의 스크립트 정책 변경이 필요하지 않습니다. 실제 작업과 같은 실행 파일·인수로 환경 검사를 수행해 종료 코드 0을 확인했습니다.

이 작업은 로컬 보고서와 웹사이트 소스 파일을 갱신합니다. 공개 Cloudflare 주소를 매일 갱신하려면 변경된 스냅샷을 GitHub에 게시하고 사이트를 재배포하는 인증 경로가 추가로 필요합니다. 스크립트가 GitHub 인증 정보를 저장하거나 공개 게시를 자동 수행하지는 않습니다.

## 현재 컴퓨터 검증

2026-10-11 16:43:09–16:47:38 KST에 실제 수집과 7개 모델 추론을 실행했습니다. 총 269.09초, 3개 지표 × 7개 모델의 21개 예측이 모두 성공했고 실패는 0개였습니다. 최근 7일 구간의 실제 관측점은 지표별 5개로 총 15개입니다. 최신 관측일은 10월 9일, 다음 관측일은 ECB 환율 10월 12일·미국 국채 10월 13일입니다. [실행 증거](local-dashboard-smoke.json)에 측정 결과를 보관했습니다.

`TSFM-Local-Dashboard` 작업을 등록하고 `Ready`, 트리거 3개, 다음 실행 2026-10-11 23:10 KST를 확인했습니다. 이는 등록 상태 검증이며 여러 날 연속 실행 실적을 뜻하지 않습니다. 기존 공개 벤치마크 작업은 등록하지 않았습니다.

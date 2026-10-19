# Daily public forecasts from local GPU

The home page compares yesterday-issued forecasts for today's observation date,
today's released actual, and the latest forecasts for tomorrow (or the next source
session). It never synthesizes an earlier issue date. On launch day the previous
forecast is absent. Release days use each source's local calendar; issue dates and
the operating schedule use Asia/Seoul. A U.S. observation may arrive the following
Korean morning. Closed sessions and unreleased observations are explicitly absent.

## Initial scope and source conditions

| Indicator | Official source | Public reuse basis |
| --- | --- | --- |
| TAIEX | TWSE/FSC government open dataset 11755, daily close | Open Government Data License (Taiwan) v1.0 with attribution |
| EUR/USD | ECB reference rate | ECB reuse conditions with attribution |
| USD/JPY, USD/KRW | Cross rates calculated from the same dated ECB EUR quotes | ECB reuse conditions; calculation disclosed |
| U.S. Treasury 2Y, 10Y | Treasury daily fitted par yield | U.S. federal government statistical work; 17 USC 105 |

These are daily index closes, reference rates and fitted par yields, not intraday quotes or
executable prices. The ECB KRW cross is distinct from the Seoul-market USD/KRW
closing series in the research configuration.

- [ECB reuse conditions](https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html)
- [ECB downloadable history](https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml)
- [Treasury XML documentation](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed)
- [Treasury methodology](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics)
- [17 USC 105](https://www.copyright.gov/title17/92chap1.html#105)

ECB data is available free from the ECB. TSFM Live calculates cross rates and
forecasts; the ECB does not issue these forecasts. Preserve attribution and the
distinction between source data and derived output. If selling access, inform
buyers before payment and each access that the underlying ECB data is free, as
required by the linked terms. Review conditions again before introducing billing.
This is a source-specific reuse assessment, not a claim about every item on a
government website. KOSPI, S&P 500 and NASDAQ remain visibly pending until a data
licence permits commercial public display; API access alone is insufficient.
CoinMetrics noncommercial crypto data is not an input to this daily board.

## Runtime

The daily runner uses only each indicator's own last 480 daily levels, without
other indicators or future actuals. Shorter histories use complete 96-point
patches shared by every model (at least 192 observations). It rejects missing
latest releases and calendar gaps. Chronos-2, Chronos-Bolt, TimesFM 2.5, Toto and
Timer use pinned model revisions in `models.yaml`, all Apache-2.0. Timer provides
point forecasts only: interval bounds are null and coverage is not evaluated.
It participates in point-error and direction metrics. Rankings require at least
20 matched targets per indicator across all five models, with matching input hashes.
Existing immutable issues are preserved, including older 512-point inputs; these
do not form matched comparisons against newer 480-point inputs. The separate
CUDA runtime changes neither the existing research model settings nor their CPU
environments. There is no CPU fallback. GPU arithmetic is checked before each run.

Create a Python 3.11 virtual environment outside the repository. Install
`torch==2.7.0` from the official PyTorch cu126 index, then the packages in
`ops/daily-gpu-requirements.txt`. The complete tested dependency pins are in
`ops/daily-gpu-lock.txt`. Download the five pinned model revisions to a private
Hugging Face cache before running; execution is offline. Keep a private
runtime file with `TSFM_PYTHON_DAILY_GPU`, `HF_HOME`, and optionally
`HF_HUB_CACHE` and `TSFM_TORCH_THREADS=4`. Add `TSFM_PYTHON_TIMER_GPU` pointing to
a separate Python 3.11 runtime with the same CUDA PyTorch and
`transformers==4.40.1`, `tokenizers==0.19.1`. Timer's official custom generation
code is incompatible with the main runtime's transformers version. The tested
Windows Timer runtime shares the main runtime's site-packages through a `.pth`
file, with those two packages installed locally using `--ignore-installed --no-deps`;
local packages take precedence. Keep the referenced main runtime available.

Timer remote code is pinned and reviewed in `timer-code-audit.txt`. Model downloads
are a separate provisioning step; inference runs offline in isolated processes
and releases VRAM between models. `gpu-model-smoke-20261019.json` records a
480-point synthetic-input, 24-step CUDA execution check on an RTX 3070 Ti. These
timings establish runtime compatibility, not predictive accuracy or hourly data
availability. Actual public targets still follow each source's daily sessions.

Using the pipeline environment's Python:

```powershell
python ops/public_daily.py --runtime-env-file <private-runtime.env> --check-only
python ops/public_daily.py --runtime-env-file <private-runtime.env>
python ops/public_daily.py --runtime-env-file <private-runtime.env> --publish-env-file <private-publish.env> --no-site --issue-hourly
```

Private state defaults to the workspace's `work/tsfm-daily-public`. Each
`issued/YYYY-MM-DD/indicator--model.json` is written once with the real completion
time, input hash and model revision. A rerun refreshes actuals without rewriting
forecasts. Missing models may retry; successful models remain frozen. SHA-256
integrity checks detect accidental corruption, not an independently timestamped
audit trail. These records are not added to the research benchmark ledger.

## Cloudflare and schedule

The Pages production binding `TSFM_DASHBOARD` points to `tsfm-live-dashboard`.
The uploader writes only key `daily-dashboard`. Its credential file stays outside
the repository and contains `CLOUDFLARE_ACCOUNT_ID`,
`CLOUDFLARE_KV_NAMESPACE_ID`, and `CLOUDFLARE_API_TOKEN`. The token needs Account /
Workers KV Storage / Edit for the selected account. The dashboard's token UI
grants account-level KV access, not an individual namespace-only capability.
Use an expiry and rotate before expiry. Neither browser code nor Pages needs the
upload token. The public endpoint is `/api/v1/daily_dashboard.json`.

A PUT success alone is not publication success: the runner reads the public
endpoint without credentials and verifies the complete payload. A static snapshot
is the fallback; the page polls once per minute and labels hourly-mode snapshots over two hours old (30 hours in legacy daily mode).
Failed refreshes keep the dated snapshot rather than inventing fresh results.

After a successful GPU run and public readback, preview then apply
`ops/configure-public-daily.ps1 -IssueHourly` with the two private file paths. It backs up the
existing Windows task XML, changes only the action, and preserves its 24 hourly
triggers, principal and settings. With `--issue-hourly`, every scheduled run can issue a new forecast for its Korean hour, including before 08:10. Without this flag, legacy once-daily issuance after 08:10 remains available. The PC and network must be
available; sleep/offline periods can delay execution. Failures are recorded in
private `latest-run.json` and return a nonzero task exit code. No external alert
service is configured.

To roll back scheduling, register the saved task XML under its original name.
To roll back the UI, revert the deployment commit through a normal pull request.
Retain the private issued archive so previously published forecasts are not lost.


## Hourly issuance, daily observations

`--issue-hourly` changes issue cadence, not source resolution or target cadence.
TAIEX closes, ECB reference rates and Treasury par yields are daily observations. We do not
forward-fill them into invented hourly observations or label daily model steps
as one-hour forecasts. There is no newly approved intraday equity-index source.
TAIEX uses only the specifically licensed daily open dataset. See `equity-source-review.txt` for the source-specific rights review and official links.

Hourly issues are immutable at `issued-hourly/YYYY-MM-DD/HH--indicator--model.json`.
The saved `issue_slot` must match the genuine completion time in Asia/Seoul.
An inference crossing an hour boundary is rejected and may retry next run.
Same-hour retries cannot overwrite successful issues. Every hour uses only
confirmed source observations; missing completed source sessions block fresh
inference. Thus hourly scheduling does not guarantee a fresh issue if a source
is delayed, the PC is offline, or inference fails.

The chart shows the latest issue and the first genuine issue from yesterday for
comparison. Historical once-daily issues remain byte-for-byte intact. Daily
comparison history retains one first issue per model and day; full hourly issue
history stays in private storage. Unchanged daily inputs may produce unchanged
forecasts. The page shows the actual issuance timestamp separately from refresh
time. Hourly price-path forecasting requires a source with real intraday
observations and commercial public-display rights, and is not implemented by
this cadence flag.

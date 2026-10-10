# TSFM Live

A prospective, public benchmark of time-series model outputs, with immutable
lock-ins, paired scoring, and an English/Korean static site. Public operator:
**TSFM Live**. Data-permission and correction contact: **jdk12987@gmail.com**.

The Python distribution and CLI are `tsfm-live`; imports use `tsfm_live`.
The owner's original implementation specification is retained privately. Source,
model, mathematical, and operational decisions are documented under `docs/`.

## Current evidence and release status

The public preview is [tsfm-live.pages.dev](https://tsfm-live.pages.dev/).
The homepage opens with a date-axis line plot: confirmed observations followed
by a separate line to each model's next-session median. Today / last 7 days
controls the observation history, and selecting a model emphasizes its line.
Model values retain their 80% intervals and exact market target dates. Before
the first public lock-in the chart honestly shows an unavailable state.
Seven pinned TSFMs have completed real-weight CPU inference on this computer.
A three-indicator historical integration took **254.18 seconds**, with 30
successful outputs and zero failures; see [measured evidence](docs/integration-smoke.md).

The application builds a truthful empty prospective view before any live
record exists. Historical baseline/calendar validation is documented in
[shadow-backtest.md](docs/shadow-backtest.md). It is not a live performance
record or a complete TSFM backtest. Installing packages and passing unit tests
do not establish weight-backed inference, deployment, 14 consecutive successful
runs, or the required 90-calendar-day shadow-live period.

`doctor` lists current launch blockers. Public daily operation still requires
configured publication credentials and a validated operating procedure. Disabled
indicators and entrants retain explicit reasons. No sample
observations are inserted into the live ledger to make the interface look full.

**Current operating mode: local execution only.** The owner deferred paid cloud
deployment on 2026-10-08. Cloud templates remain available for a future decision;
no Cloud Run job, cloud scheduler, or Windows scheduled task is enabled by the
local launcher. Local diagnostic results do not create public prospective history.

## Local setup

Use Python 3.12 for the core, Python 3.11.17 for isolated model profiles, Node 24,
and the pinned uv version recorded in the deployment image. From the repository:

```sh
uv sync --project pipeline --frozen --python 3.12
uv run --project pipeline pytest pipeline/tests ops/tests
uv run --project pipeline tsfm-live validate
uv run --project pipeline tsfm-live doctor
uv run --project pipeline tsfm-live export-site
npm ci --prefix site
npm run build --prefix site
npm run dev --prefix site
```

PowerShell can use the same commands. `doctor` emits readiness and blockers in
JSON; inspect that result, not just process exit status. Copy `.env.example`
into a private environment configuration; it is a reference, not automatically
loaded by the CLI. Put the raw-data/model cache outside the public checkout.
Never commit a populated environment file or credentials.

Model runtimes are intentionally isolated to preserve vendor dependency pins:

```sh
uv sync --project model_envs/chronos --frozen --python 3.11.17
uv sync --project model_envs/timesfm --frozen --python 3.11.17
uv sync --project model_envs/moirai --frozen --python 3.11.17
uv sync --project model_envs/toto --frozen --python 3.11.17
uv sync --project model_envs/tirex --frozen --python 3.11.17
uv sync --project model_envs/sundial --frozen --python 3.11.17
```

Set each `worker_env` named in `pipeline/tsfm_live/config/models.yaml` to that
profile's Python executable (`.venv/bin/python`, or `.venv/Scripts/python.exe`
on Windows). Chronos-2 and Chronos-Bolt share the Chronos profile. The core
environment does not load mutually incompatible vendor packages together.
Model weights must be warmed at the exact configured revision, smoke-tested,
and available locally before live operation. Keep `HF_HUB_OFFLINE=1` in live
runs. A successful install alone must not set `runtime_verified` to true.

### Run on this Windows computer

The installed profiles and private weight cache can be reused without an install
or weight download. From the repository root, open PowerShell and run:

```powershell
.\ops\run-local.ps1 -RuntimeEnvFile ..\..\work\model-smoke\runtime.env -CheckOnly
.\ops\run-local.ps1 -RuntimeEnvFile ..\..\work\model-smoke\runtime.env
```

The environment file path is explicit and must be outside the public repository.
It contains only the model interpreter paths, `HF_HOME`, and optional CPU thread
settings. The launcher validates all enabled runtime versions and pinned cached
snapshots, forces CPU and offline model loading, and runs the current Asia/Seoul
calendar date as a **dry-run**. Data-source HTTPS requests are still permitted.
It does not load publication credentials, send notifications, or create a schedule.
Missing runtimes or cached weights fail before the pipeline starts. `-CheckOnly`
performs these local checks without fetching source data or running inference.
The recorded [local preflight result](ops/local-preflight-results.json) confirms
six Python 3.11.17 profiles and seven pinned model snapshots on this computer;
weight-backed inference evidence is recorded separately in
[model-smoke.json](docs/model-smoke.json).

For a historical diagnostic, use an explicit past date:

```powershell
.\ops\run-local.ps1 -RuntimeEnvFile ..\..\work\model-smoke\runtime.env -AsOf 2026-10-07
```

`-AsOf` always remains a dry-run and cannot target a future date. Source series
may include revisions received after that historical date, so a replay is not a
prospective record. Raw cache defaults to `../../work/tsfm-live-cache`; override
it with `-CacheDir` pointing outside the repository. Results are written under
`../../work/tsfm-live-dry-run/<run-id>/` and the CLI prints the exact destination.
The PowerShell process preserves the pipeline's exit code. Historical dry-runs
produce forecasts and a diagnostic manifest; they do not append scored live rows.

## Daily flow

When public daily operation is explicitly enabled in the future, its scheduler
starts at 08:10 Asia/Seoul every calendar day. The pipeline ingests
confirmed data, applies source/calendar eligibility, and obtains next-session
outputs. The forecast and hash-index commits must reach public protected `main`
before 08:50. It then collects available outcomes, scores, aggregates, creates
cards, records a manifest, and publishes the derived static data.

```sh
uv run --project pipeline tsfm-live run --date YYYY-MM-DD
```

Live execution additionally requires `TSFM_LIVE_ENABLED=1` and all readiness
gates. Historical dates never become live lock-ins. For an isolated diagnostic:

```sh
uv run --project pipeline tsfm-live run --dry-run --as-of YYYY-MM-DD
```

Diagnostic artifacts stay outside the live ledger. The optional
`--baselines-only` flag is permitted only with `--dry-run`; it cannot disguise a
baseline as a foundation model.

## Retry and incident runbook

1. Check the public manifest, hash index, PR status, and `/status`. Determine
   whether the original forecast reached public `main` before its deadline.
2. If a timely confirmed lock-in exists, resume downstream work with the same
   date. The run must reuse the original forecast bytes:

   ```sh
   uv run --project pipeline tsfm-live run --date YYYY-MM-DD --step actuals,score,aggregate,cards
   ```

3. If only rendering failed, `tsfm-live export-site` and `tsfm-live cards` can
   regenerate derived files. Published ledger files remain append-only.
4. If publication missed its deadline, preserve the void/failure record. Do not
   change the date, rerun inference to replace it, or publish it as timely later.
5. If publication is ambiguous after a crash, reconcile the remote commit/PR and
   receipt. A missing receipt is not inferred from local file existence. Private
   recovery archives may retain failure evidence, but cannot create a valid late
   forecast. A fresh public correction records the resolution.
6. For a Cloud Run lease left by abrupt termination, first confirm that no
   execution is still running. Inspect the lease's execution ID and generation;
   remove only that verified stale object with a generation precondition.
   Then resume the already-authorized post-lock-in work.

Do not force-push, bypass required checks, rename old ledger files, or edit old
JSON records. Automatic model/whole-job retries cannot extend the deadline.

## Corrections

Prepare a new JSON correction matching `ledger/schema/corrections.json`, with
a unique ID, creation timestamp, author, reason, affected file and exact record
selector. For example, a void record has `type: "void"`, `replacement: null`,
and points to the original forecast file. Issued forecast numbers cannot be
replaced; use void/disqualification corrections instead. An actual-level
revision recomputes the transformed outcome and scores from the original public
anchor. Where levels are not published, a revision must supply the transformed
outcome explicitly. Use the current schema and tests for record selectors.

```sh
uv run --project pipeline tsfm-live correction path/to/correction.json
uv run --project pipeline tsfm-live validate
uv run --project pipeline tsfm-live export-site
```

The correction command creates an append-only local record and reports
`pending_review`; it does not silently publish. Commit the correction and
derived views on a branch, open a PR, wait for required checks, and merge using
the checked head SHA. Keep the original bytes. Review the resulting aggregate
changes and disclose the correction on the public record.

## Independent hash verification

Clone the public repository. Read the date's digest and forecast commit from
`ledger/HASHES.md`. Verify both the working file and the same file at that commit:

```sh
uv run --project pipeline tsfm-live validate
sha256sum ledger/forecasts/YYYY/YYYY-MM-DD.json
git show FORECAST_COMMIT:ledger/forecasts/YYYY/YYYY-MM-DD.json | sha256sum
```

On Windows, use `Get-FileHash -Algorithm SHA256` for the working file. For the
commit bytes, avoid text-mode shell piping; Python's `subprocess.check_output`
preserves the exact blob. Verify that the publication receipt's timestamp is
strictly before the recorded deadline. A hash alone proves bytes, not timing.
OpenTimestamps evidence, where available, is additional evidence rather than a
replacement for the publication receipt. See [ledger/README.md](ledger/README.md).

## Change management and CI

To add an indicator, verify source rights, exact series, availability, transform,
and calendar; add configuration, adapter tests and a public decision. To add an
entrant, pin package and weight revision, document its licence, add the isolated
adapter/profile and a weight-backed smoke test, and measure the deadline budget.
Only then enable it and update the image/cache bundle. Model/profile changes
invalidate the previous image's code fingerprint.

Required branch checks are `pipeline` and `site`. They cover tests, lint, ledger
validation, append-only diffs, copy/i18n/build checks, and mobile Lighthouse
thresholds. CI uses read-only tokens and no production secrets. Pin changes are
reviewable code changes.

Manual negative CI check: on a disposable PR branch, edit one byte in an already
published forecast, then run `tsfm-live check-immutability BASE_SHA`. The check
must fail. Repeat for a rename/deletion, an old snapshot/correction, and an
existing hash-index line. Close the test PR without merging. This manual hosted
check remains pending until a real public repository exists; unit tests do not
claim it has occurred.

## Deferred deployment, credentials, and launch evidence

Follow [operations-decisions.md](docs/operations-decisions.md) for Cloud Run,
Cloud Scheduler, persistent caches, Cloudflare Pages, retention, and monitoring.
These are retained setup instructions; cloud deployment and billing are deferred
under the owner's current local-only operating choice.
The deployment templates contain placeholders and have not themselves created
any cloud resources. No scheduler or publishing job is enabled by checking out
this repository.

Rotate the repository token by adding a new secret version, updating the job's
explicit version reference, testing a staging PR, then revoking the old version.
Use a single-repository fine-grained token with only the contents/PR/check access
the publisher requires. It must not bypass branch protection. Rotate source and
webhook secrets similarly; never print them in logs or command-line URLs.

Before public announcement retain evidence for: at least six working TSFMs plus
two baselines and ensemble; verified or explicitly disabled sources; 14
consecutive on-time live runs; at least 90 calendar days of shadow live; seven
days of valid cards; tested red alerts; CORS/cache/OG checks; rank/PI sample
thresholds; and a second operator's successful retry/correction rehearsal.

The software code licence and the derived-ledger licence are separate. Upstream
data and model licences remain applicable; consult [docs/compliance.md](docs/compliance.md).

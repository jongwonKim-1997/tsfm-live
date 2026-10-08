# Operations decisions and deployment procedure

Reviewed 2026-10-08 against the official references linked below. These files
prepare a deployment; they do not establish that any cloud resources, hosted
checks, schedules, or live runs exist. Public brand/operator is **TSFM Live**;
the owner-provided contact is **jdk12987@gmail.com**. No lab affiliation is used.

**2026-10-08 operating decision: local execution only; cloud deployment deferred.**
The owner chose to defer cloud billing. The GCP project identifier
`tsfm-live-20261008` was created during setup, but these retained procedures do not
authorize further resource creation, billing activation, or scheduling. Use
`ops/run-local.ps1 -RuntimeEnvFile <private-path>` for manual CPU dry-runs. The
launcher validates the existing profiles and pinned local weights, suppresses
publication, and does not register a Windows scheduled task. The remaining cloud
sections describe a future deployment procedure, not active infrastructure.

## Scheduler, image, and cache architecture

Use Google Cloud Run Jobs with Cloud Scheduler at **23:10 UTC every day**,
equivalent to 08:10 the next calendar date in Asia/Seoul. The job has one task,
parallelism one, zero task retries, a 40-minute task timeout, 4 CPUs and 16GiB
RAM. The pipeline independently enforces the 08:50 KST publication deadline;
the infrastructure timeout cannot extend it. Job timing and retries follow the
[Cloud Run jobs API](https://docs.cloud.google.com/run/docs/create-jobs), while
OAuth-authenticated Scheduler invocation follows the
[official scheduling procedure](https://docs.cloud.google.com/run/docs/execute/jobs-on-schedule).

The image installs the core, six isolated model profiles, and the optional
OpenTimestamps client profile at build
time. It uses CPython 3.11.17 for the model profiles, uv 0.12.23, and a verified
GitHub CLI 2.102.0 archive checksum. Python and Node base images are pinned by
manifest digest. The final built image must also be deployed by digest. OS
packages are resolved during image build; retain the image digest and SBOM to
identify them, and rebuild deliberately for security changes. No packages or
model revisions are resolved during a daily run.

Persistent storage uses separate private GCS buckets for approved model bundles
and raw source evidence. GCS capacity is not preallocated like a disk; allow at
least 20GiB of model objects in the capacity/cost budget. An approved model-cache
archive is named by revision and pinned by SHA-256 in job configuration. Runtime
copies it onto a **50GiB local ephemeral disk**, verifies its hash, extracts it
locally, and sets `HF_HUB_OFFLINE=1`. HF locks and model memory mapping therefore
use a local filesystem. The persistent model mount is read-only.

Cloud Storage FUSE does not provide file-locking concurrency guarantees. It is
used here only for reading the approved archive and persisting private cache
files under an exclusive object-generation lease, as explained in the
[Cloud Storage mount limitations](https://docs.cloud.google.com/run/docs/configuring/jobs/cloud-storage-volume-mounts).
An atomic GCS `ifGenerationMatch=0` upload acquires `locks/active.json` across
job executions. Release requires its matching generation. The lease is never
stolen automatically; a crashed execution requires operator reconciliation.

The local disk uses Cloud Run's beta ephemeral-disk support. A 50GiB per-instance
quota is required because the documented default is 10GiB. The template must
not be deployed until that quota is granted. Local disk is not persistent;
its capacity and beta limitations are documented in the
[ephemeral-disk reference](https://docs.cloud.google.com/run/docs/configuring/jobs/ephemeral-disk).
If this feature or quota is unavailable, use a scheduler with a persistent
POSIX volume and record the change, rather than silently placing 20GiB of
cache into a memory-backed filesystem.

The raw cache is restored locally and copied back on normal completion or
handled exceptions. Identical evidence files are not rewritten, preserving
their storage age. A hard kill or OOM can still interrupt this final copy;
staging must exercise that failure and add incremental persistence if necessary
before relying on complete failure-time source evidence. Failed local ledger
files are archived privately under `recovery/<execution>/` when the process can
handle the failure; such archives never establish public lock-in.

The internal `cache/lockin-receipts` directory is linked directly to the private
raw mount before the CLI starts, while the exclusive generation lease is held.
Closed receipt/key writes therefore do not wait for the final cache copy.
Receipt recovery still validates its authenticated envelope, original forecast
bytes, run date, timely publication time, and public commit reachability; it
cannot import a user-supplied receipt. A kill before a complete receipt is closed
still requires manual reconciliation. GCS FUSE close/rename behavior and abrupt
termination recovery remain cloud staging checks, not locally proven guarantees.

## Cloud provisioning

Use an owner-selected billed project and region. Replace all `REPLACE_*` values
in a private copy of `ops/cloud-run-job.template.yaml`. Public identifiers may
be committed after review, but secret values must remain in Secret Manager.

1. Enable Run, Scheduler, Artifact Registry, Storage, Secret Manager, and Logging
   APIs. Create separate runtime and scheduler service accounts. Create a private
   Artifact Registry Docker repository and two private buckets with uniform
   bucket-level access and public-access prevention.
2. Grant the runtime account `roles/storage.objectViewer` on the **model bucket**,
   and `roles/storage.objectUser` on the **raw bucket**, scoped to those buckets.
   The latter permits the generation-precondition lease and cache writes. Do
   not grant project-wide storage administration. Grant
   `roles/secretmanager.secretAccessor` only on the three named secrets.
3. Create secrets `tsfm-ecos-key`, `tsfm-github-token`, and `tsfm-webhook` using
   protected input files or the console. Reference explicit version numbers.
   The GitHub token must access only the chosen repository and cannot bypass
   its ruleset. The webhook destination must be owner-provided.
4. Grant the scheduler account `roles/run.invoker` on the daily job only, after
   creating it. The deploying identity needs the separate deployment/IAM rights;
   the runtime account does not inherit them.
5. Apply `ops/raw-lifecycle.json` to the raw bucket. This retains raw response
   objects and private recovery objects for 90 days before lifecycle deletion.
   Never attach this lifecycle to the model bucket or public ledger.
6. Set Cloud Logging retention to at least 30 days, and verify that the job's
   structured logs route to that bucket. See the
   [log bucket retention documentation](https://docs.cloud.google.com/logging/docs/buckets).

Before building, obtain the reviewed source commit and set `CODE_REVISION` to
its full 40-character SHA. The container checks that its executable/config
paths match public main; ledger-only updates do not require rebuilding.

```sh
docker build --platform linux/amd64 -f ops/Dockerfile --build-arg CODE_REVISION=FULL_SOURCE_SHA -t REGION-docker.pkg.dev/PROJECT/tsfm/runner:SOURCE_SHA .
docker push REGION-docker.pkg.dev/PROJECT/tsfm/runner:SOURCE_SHA
gcloud run jobs replace PRIVATE_RESOLVED_JOB.yaml --region REGION --project PROJECT
```

The build is substantial because all isolated vendor environments are included.
Test this exact Linux image before enabling it; local Windows smoke tests alone
do not verify Linux wheels, custom operators, cold starts, or cloud performance.

Warm only licensed, approved weight revisions in an isolated preparation job.
Use the packaging helper to include only enabled pinned snapshots and their
referenced blobs, excluding HF token files, unrelated models, and lock files:

```sh
uv run --project pipeline python ops/package_model_cache.py --cache PRIVATE_HF_HOME --output PRIVATE_OUTPUT/model-cache-REVISION.tar.gz
```

The helper records the SHA-256 and included model revisions in an adjacent JSON
manifest. Upload the archive under a new model-bundle object name, and place
the object path/hash in the job configuration. Do not overwrite an approved bundle.
No live run may download weights. Measure archive restore plus all critical
steps; the target is less than 20 minutes with enough CI/publication margin.

Keep `TSFM_LIVE_ENABLED=0` until image tests, source gates, model smoke tests,
public repository checks, branch rules, secrets, and `doctor` readiness pass.
Then configure the reviewed job with the flag set to 1 for prospective shadow
operation. Only then create the schedule:

```sh
gcloud scheduler jobs create http tsfm-live-daily --project PROJECT --location REGION --schedule="10 23 * * *" --time-zone="Etc/UTC" --uri="https://run.googleapis.com/v2/projects/PROJECT/locations/REGION/jobs/tsfm-live-daily:run" --http-method=POST --oauth-service-account-email=tsfm-scheduler@PROJECT.iam.gserviceaccount.com --message-body='{}' --max-retry-attempts=0
```

Cloud Scheduler start-time precision must be measured during shadow operation;
no guarantee of sub-minute startup has been established by these templates.

## Protected public ledger

Enable a public GitHub repository with `main` protected by required PRs,
required `pipeline` and `site` checks, no force push, and no branch deletion.
Do not place the runtime token on any bypass list. The publisher creates a
forecast commit A, then a hash-index commit B referencing A. Both go through
the PR checks and an exact-head merge. Any intervening head change requires
fresh checks; no admin merge or direct protected-branch push is permitted.

Required PR CI can consume much of the 40-minute budget. Measure push, queue,
checks, and merge time in staging and record the distribution. If those checks
cannot reliably finish by the deadline, skip/void the run and revise the
architecture prospectively. Never weaken branch protection to make a late
output appear timely.

Read `README.md` for failure reconciliation, post-lock-in retries, correction
workflow, hash verification, and a deliberately failing immutability PR test.

## Cloudflare Pages

Create a git-integrated Cloudflare Pages project for this repository with:

| Setting | Value |
|---|---|
| Production branch | `main` |
| Root directory | `site` |
| Build command | `npm run build` |
| Build output | `dist` |
| Node version | `24` |
| Public origin environment | actual HTTPS `TSFM_PUBLIC_ORIGIN` |

Astro static output and these basic build settings follow
[Cloudflare's Astro integration](https://developers.cloudflare.com/pages/framework-guides/deploy-an-astro-site/).
The pipeline commits generated JSON before the site build; no private source or
model credentials belong in Cloudflare. Configure the custom domain/HTTPS when
the owner chooses it. Keep the current `noindex,nofollow` shadow behavior until
the launch criteria are met. A standalone preview must also use the generated
empty/live data, never an unlabeled fixture ledger.

After the first deployment, verify `/`, `/models`, `/indicators`, all Korean
routes, OG card dimensions/content, public contact, and `/api/v1/status.json`.
Inspect real response headers:

```sh
curl -I https://DOMAIN/api/v1/status.json
```

Require `Access-Control-Allow-Origin: *` and
`Cache-Control: public, max-age=300`. Record the deployed commit, build duration
(target under five minutes), domain, HTTPS, redirects, and header results.
Git integration and these headers have not been verified on a hosted instance
merely by producing a local Astro build.

## Monitoring and staging acceptance

Use the pipeline's owner-authorized webhook for one run summary and its
specified failure conditions. Independently create a small `tsfm-live-status`
Cloud Run job from the same image, overriding command/args to execute
`python /app/ops/status_probe.py`. It needs the public origin only, no repository
token, model buckets, or source secrets. Schedule it at **00:30 UTC / 09:30 KST**.
It exits nonzero when the public status date is stale. A successful Scheduler
API call is not evidence that the daily job itself succeeded.

Resolve `ops/alert-policy.template.json` with the owner's notification channel
and install a Cloud Monitoring log alert for execution/freshness failures.
Also monitor failed/terminated job executions, including those killed before a
structured error could be written. The templates do not create or send to an
unprovided channel. Test source outage, all-indicator model failure, deadline
miss, public push failure, unavailable actual, site build failure, stale status,
lease contention, and OOM/termination in staging. Record delivery and recovery
evidence; none of those external alert drills are implied by unit-test success.

Alert derivation deduplicates manifests by run date. The latest completed
manifest determines deadline status; the first non-resume start determines
scheduler lateness. Three deadline misses in 30 calendar days and two starts
more than 15 minutes late in 14 calendar days raise separate migration-review
alerts. Distinct indicators, not duplicate model rows, determine the three-source
and two-missing-actual thresholds. Actual-unavailability alerts use the recorded
scoring event's KST date within the past seven days.

Notification receipts are private cache files. Each logical run or provider build
has a stable event ID reserved before HTTP delivery. If delivery times out, it
is marked unconfirmed and is not sent again automatically, since the receiver
may already have accepted it. This provides at-most-once attempts, not a claim
of exactly-once remote delivery. Reconcile the destination before manually
retrying. `notify_build_failure` is the callback function for a provider-verified
deployment event; an authenticated provider integration must be configured
before this callback counts as tested end-to-end monitoring.

## Local site audit evidence

The updated black/blue static build was audited locally with Lighthouse 12.6.1,
mobile emulation, and an English browser locale. Each of `/`, `/models/`, and
`/indicators/` completed three runs with **100 performance and 100 accessibility**
in every run. The raw-run summary is in `ops/audit-results.json`. These exceed
the 90/95 acceptance thresholds for this local build; they do not measure hosted
network latency or prove Cloudflare deployment success. Earlier audit evidence
is retained separately in the same file.

The 2026-10-08 npm audit snapshot in `ops/dependency-audit.json` reports **17
findings in the development tooling tree** (11 high, four moderate, two low)
and **zero findings with `--omit=dev`**. The affected tree is rooted at the
Lighthouse CI development dependency; it is not included in the static served
files or the runner's `npm ci --omit=dev` installation. Npm's proposed automatic
fix is an incompatible downgrade of the auditing CLI to 0.1.0. No force fix was
applied. CI has read-only repository permissions and no production secrets;
replacing or updating the audit tool requires a reviewed compatibility change.

## Verified dependency references

Public tag refs were resolved through `api.github.com/repos/<owner>/<repo>/git/ref/tags/<tag>`
on 2026-10-08 and written as full SHAs in `ci.yml`: checkout v4, setup-uv v6,
setup-node v4, and upload-artifact v4. Python/Node manifest digests were read
from the official Docker Hub registry, and the gh archive hash came from the
[official GitHub CLI release](https://github.com/cli/cli/releases/tag/v2.102.0).
The image and action pins are reproducible inputs, not proof that the build or
deployment has run. Track approved updates in the decision log.

# Public ledger verification

This directory starts with schemas and documentation only. There are **no live forecasts yet**. Historical smoke tests and synthetic fixtures are not ledger history.

## Verify a real record from a fresh clone

```sh
git clone https://github.com/jongwonKim-1997/tsfm-live.git
cd tsfm-live
uv sync --project pipeline --frozen --python 3.12
uv run --project pipeline tsfm-live validate
sha256sum ledger/forecasts/YYYY/YYYY-MM-DD.json
```

Replace the date with an actual entry from `HASHES.md`, created on the first live publication. On PowerShell use `Get-FileHash -Algorithm SHA256 -LiteralPath ledger/forecasts/YYYY/YYYY-MM-DD.json`. The digest must match the index and manifest. JSON is UTF-8, sorted by key, compact, finite, with numeric values rounded to six decimal places. Hash the committed bytes directly; formatting a copy changes the hash.

Inspect the index's forecast commit with `git show <commit>:ledger/forecasts/YYYY/YYYY-MM-DD.json`. Forecast commit A contains the forecast; later index commit B references A. A file cannot contain the hash of its own final commit. The manifest records observation of the confirmed public merge and the deadline comparison. Git author/committer dates alone are not independent timestamp evidence and a repository owner can rewrite history.

When an OpenTimestamps proof is available, verify its binding to the exact forecast bytes:

```sh
uv sync --project model_envs/ots --frozen --python 3.11.17
model_envs/ots/.venv/bin/ots --no-cache --no-default-whitelist verify -f ledger/forecasts/YYYY/YYYY-MM-DD.json ledger/ots/YYYY-MM-DD.ots
```

This uses the pinned OpenTimestamps client 0.7.2 and a configured, synchronized Bitcoin Core mainnet node. A successful `stamp` or `upgrade` command alone does **not** establish an independently verified anchor. Only successful `verify` against the exact forecast bytes counts as anchored. Proof verification does not establish that anchoring happened before the forecast deadline; the separate publication receipt supplies that benchmark deadline evidence. Save or mirror the original public bytes for independent preservation.

The optional adapter is enabled by default and runs after lock-in and scoring with a 90-second total budget. Set `TSFM_OTS_EXECUTABLE` to the isolated profile's `ots` executable, or put that executable on `PATH`; `TSFM_OTS_ENABLED=0` disables it. `tsfm-live ots --date YYYY-MM-DD` can retry a genuine live date; omitting the date processes eligible live receipts, newest first. No eligible receipt means no calendar requests. The adapter never stamps dry-run documents.

Unverified proofs are retained under the private cache, marked `pending`, and retried on later runs. Only an independently verified proof is appended as `ledger/ots/YYYY-MM-DD.ots`. Upgrade attempts operate on private copies, so a public proof is never rewritten. The next results publication includes newly appended proofs; the standalone command only prepares the local append. `HASHES.md` keeps its original append-only row, so its initial `pending` entry is not rewritten. A manifest records the current attempt's `ots_status`; subsequent proof availability can be checked directly in `ledger/ots/`.

Missing clients or native libraries are `unavailable`; calendar or client failures are `failed`; an existing proof that cannot yet be verified is `pending`. These states never become a substitute for timely lock-in, never imply a verified Bitcoin anchor, and never invalidate an already locked forecast. The Windows install check found that python-bitcoinlib could not discover a native OpenSSL library; the client is installed but currently unavailable on the measured Windows machine. No real forecast has been stamped or anchored in this deliverable.

Client behavior follows the [official OpenTimestamps documentation](https://github.com/opentimestamps/opentimestamps-client) and the [pinned PyPI release](https://pypi.org/project/opentimestamps-client/0.7.2/). The protocol's [verification explanation](https://opentimestamps.org/) distinguishes a calendar receipt from Bitcoin confirmation.

## Append-only rules

Forecasts, actuals, scores, manifests, snapshots, corrections and published proofs are never edited, renamed or deleted. `HASHES.md` may only grow by appending. CI tests existing-file modifications and prefix changes. Required branch checks are also needed on the hosted repository; local code cannot enforce remote branch settings by itself.

Corrections are new documents under `corrections/YYYY/`. Forecast numeric outputs cannot be replaced. Void/disqualification overlays exclude affected outputs from evaluation. Actual revisions may replace permitted actual fields and are propagated through recomputed scores and generated views. Original records, old scores and snapshots remain inspectable. Use `tsfm-live correction FILE.json` to validate all selectors and replacement fields before creating a local correction, then follow the review/publication procedure in [the runbook](../README.md).

## Confirmed lock-in recovery

After public lock-in, the pipeline immediately closes and checkpoints its confirmed receipt under the private cache's `lockin-receipts/` directory before scoring or card generation. The envelope is authenticated using a separately stored random key in that same private directory. Neither file belongs in Git, the public API, a model-cache bundle or an uploaded diagnostic. This authentication detects altered checkpoints inside the trusted private cache; it is not an independent public timestamp and does not defend against compromise of both the cache and its key.

A retry can restore a missing manifest only when its internal envelope authenticates, its date and SHA-256 bind the already issued forecast, and a fresh remote check confirms that the original forecast commit remains reachable on `origin/main` with exactly those bytes. There is no user-supplied receipt-import or deadline override. Missing, partial or unverifiable evidence stays fail-closed and requires reconciliation; it never triggers a new forecast for the old date. Previously confirmed receipts from earlier dates are recovered after the current day's lock-in, allowing an interruption across midnight to resume scoring without backfilling predictions.

In the Cloud Run template, the receipt directory is linked directly to the private durable cache mount instead of waiting for end-of-job copying. Local execution keeps it in the configured private cache. The Cloud Run mount's close/rename/termination behavior still needs staging validation before cloud activation. A failure publishing later scores or cards appends a failure manifest locally and sends the configured publication-failure alert while preserving the successful lock-in receipt. That failure record reaches the public ledger only when publication is subsequently restored.

The static API has original forecast exports and effective corrected scorecards. A failed or late latest run must remain visible; a previous successful forecast is never presented as today's forecast.

Generated ledger records are licensed under [CC BY 4.0](LICENSE). Upstream data and model licences remain separate.

# Resumable historical model replay

The full 365-day seven-model replay has **not** been run. The existing [365-day report](shadow-backtest.md) covers baselines and calendars, and [integration smoke](integration-smoke.md) covers one date with the seven actual models. This runner provides a controlled way to complete the longer experiment. It cannot create prospective evidence or meet the 90-day live-history requirement.

The module `tsfm_live.replay` uses the same eligibility, transforms, 512-observation context limit, per-date/indicator/model seed, worker isolation, 120-second model timeout and output validation as the live pipeline. It reads a frozen, SHA-256-verified ECB/Treasury raw-response cache and makes no source requests or model downloads. Inference runs on the seven currently enabled TSFMs, two baselines and the eligible ensemble. Disabled source indicators remain explicitly skipped. Local worker paths and model weights must already exist.

Run from the repository directory in PowerShell. All paths below refer to the already prepared local workspace; change the output name for a separate experiment. Start with a bounded slice of the **same 365-day plan**, so later calls resume it:

```powershell
.\pipeline\.venv\Scripts\python.exe -m tsfm_live.replay `
  --root . `
  --cache-dir ..\..\work\tsfm-source-smoke-cache `
  --output-dir ..\..\work\tsfm-historical-replay-365 `
  --runtime-env ..\..\work\model-smoke\runtime.env `
  --end-date 2026-10-07 --days 365 --max-new-days 2
```

Inspect the private `summary.json`, especially failures, skips and missing historical outcomes. Re-run the identical command to process the next two unfinished days, or omit `--max-new-days` to complete the remaining plan. The one-day measured smoke took about 4.24 minutes; a 365-day replay is a many-hour job whose duration varies with eligible sessions and model performance. It is not automatically launched by installation, the live scheduler or the UI. The computer must remain awake while the foreground process runs.

For a short baseline-only diagnostic, choose a different private output directory and add `--baselines-only --days 2`. That is explicitly a baseline experiment and cannot be reported as a seven-model replay.

Each successful model/date/indicator prediction is saved atomically with its context/config binding and payload hash. An interrupted day reuses those predictions. Completed day files are never overwritten or re-inferred. A failed model remains a recorded failure in its completed day; use a fresh output directory for an intentional new attempt. Corrupted checkpoints fail closed. An exclusive process lock prevents two processes from using one output directory concurrently.

The plan binds the date range, configurations, histories, source-response evidence, Python source files, core lockfile and available worker lockfiles. Changing code, configuration, frozen inputs or worker profiles causes resume to refuse the old directory. Keep the raw cache unchanged for the duration, or preserve a private copy before starting. A newly fetched/revised source snapshot requires a separate experiment. Transient `.partial` files from a forced termination are never treated as completed checkpoints.

Artifacts remain outside the application repository and outside any `ledger/` directory:

- `plan.json`: immutable, hash-checked experiment specification and source evidence.
- `predictions/<date>/<indicator>/<entrant>.json`: successful model checkpoints.
- `private/contexts/`: private input arrays and level anchors, including return-only sources.
- `days/<date>.json`: simulated forecasts and retrospectively calculated scores for that day.
- `summary.json`: current completion counts and per-indicator/entrant metrics.
- `aggregates.json`: paired window/regime aggregations, generated only after all planned days complete.

Every result states that it is a hindsight research fixture, not a live record. Actuals are accessed only after each indicator's forecasts complete, but the downloaded history can contain revisions and unknown historical publication times. The output must not be copied into the public live ledger or presented as real-time predictive performance. The runner never publishes, signs a live lock-in, sends notifications or changes the site.

Two-day offline tests validate checkpoint reuse, interruption recovery, unchanged prediction bytes, future-observation exclusion, private path guards, changed-input refusal and corruption detection. They execute the real baselines only; they do not stand in for the long seven-model experiment.

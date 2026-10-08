# Historical integration smoke — 2026-10-07 logical date

**Historical dry-run only. No live ledger or public financial output was created.** Current source histories can contain revisions, and foundation models may have seen historical observations during training. This check establishes wiring, eligibility, execution and serialization; it does not establish prospective performance.

The actual CLI `tsfm-live run --dry-run --as-of 2026-10-07` completed with exit code 0 in **254.2 seconds (4.24 minutes)**. It used the seven pinned local TSFM runtimes, both baselines and the ensemble on three enabled public-source indicators.

Result: **30 successful, 124 explicitly skipped, 0 failed**, across 154 indicator × entrant records. The 124 skips are 121 pairs for 11 explicitly disabled indicators plus three disabled TabPFN entries. The run was below the 20-minute target. All ledger file paths and content hashes matched their pre-run state.

| Indicator | Successful entrants | Context | Transform | All entrant inference (s) |
|---|---:|---:|---|---:|
| eurusd | 10 | 512 | log_return_pct | 77.58 |
| usdjpy | 10 | 512 | log_return_pct | 80.28 |
| ust10y | 10 | 512 | diff_bp | 74.83 |

Each successful record contained all 13 finite, monotone quantiles. Within each indicator, all entrants received the same 512-value context and context hash. Each ensemble includes all seven successful TSFMs, excludes baselines, and uses a quantile-wise median. Toto and Sundial each generated 1000 samples. Forecast seeds were derived independently for each logical date, indicator and entrant.

The three source histories came from two providers: ECB (EUR/USD and the EUR/JPY÷EUR/USD derived USD/JPY reference) and U.S. Treasury (10Y par yield). Raw source responses and private anchors stayed outside the repository. Source fingerprints, response hashes, exact contexts, forecast distributions, model revisions and failures are recorded in [integration-smoke.json](integration-smoke.json). There were no model failures.

Forecast artifact SHA-256: `2e307b6b9e1838e57a7c095a7a7e4fe148afe7d6ef9c87c53135167e0f0a6e31`. Manifest artifact SHA-256: `0a8867513c7f20de28a5efb7871ec2239eaf01b66b930a307480aa0d1f1ca959`.

Scope: the dry-run CLI intentionally ends after ingestion and forecast serialization. It does not push a lock-in, score a prospective outcome, generate live ranks or publish a site. Score/aggregation tests and the 365-day historical backtest are separate; this one-day execution cannot substitute for 14 consecutive timely public runs or 90 days of shadow-live history.

The model runtime evidence and hardware measurements are in [model-smoke.md](model-smoke.md). All launch-ready flags remain false.

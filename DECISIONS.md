# Decisions

Status: implementation and validation, not a completed live launch. Reviewed 2026-10-08.

| Decision | Adopted choice and evidence |
|---|---|
| Product and operator | **TSFM Live**, explicitly selected by the owner. Contact: jdk12987@gmail.com. No university/lab affiliation. Domain remains open. |
| Visual direction | Owner requested black and blue. Default near-black, navy surfaces and restrained blue accents; alternate light theme remains available. Text, labels and interval values accompany colour. This owner preference supersedes automatic OS theme selection. |
| Sources | ECB EUR/USD, derived USD/JPY and US Treasury 10-year enabled. Other 11 indicators explicitly disabled pending verified access/terms/timing. S&P, Nasdaq, WTI and gold are not silently replaced with ETFs or scraped proxies. See [source decisions](docs/data-decisions.md) and [source evidence](docs/data-sources.md). |
| Scheduler | Owner chose local execution first and declined connecting cloud billing. The verified local CPU runner remains available. Cloud Run Jobs templates retain 23:10 UTC / 08:10 KST, a single task and distributed lease for a future migration. Project `tsfm-live-20261008` exists; no paid runner, billing link or cloud schedule is provisioned. See [operations](docs/operations-decisions.md). |
| Models and CPU | Seven pinned TSFMs run in six isolated CPU environments. TiRex included with required attribution. TabPFN-TS disabled until access and licence conditions are resolved. RTX 3070 Ti is available but unnecessary for the verified path. [Model decisions](docs/model-decisions.md). |
| Timing evidence | Actual historical integration over three enabled indicators, seven TSFMs, two baselines and ensemble: 254.18 seconds, 30 successful outputs, 124 explained skips, zero failures. This establishes local feasibility, not Cloud Run timing or the 14-indicator worst case. [Measured integration](docs/integration-smoke.md). |
| Chart library | Observable Plot, rendered to SVG at build time. Per-indicator CRPS plots avoid mixing incompatible units. Interval history separates entrants. No chart runtime required for first paint. |
| Licences | Code Apache-2.0; generated ledger/API data CC BY 4.0. Upstream raw data and model weights retain their own terms. [Compliance](docs/compliance.md). |
| Timestamp evidence | Two Git commits separate forecast bytes from the hash index; observed remote publication receipt is conservative. Git timestamps alone are not independent proof. OpenTimestamps is enabled when its separately installed CLI and valid live receipts are available; pending/anchored proof states must stay distinct. |
| Immutable corrections | Forecast values cannot be rewritten. Void/disqualification overlays are append-only. Actual revisions trigger recomputation in effective views; originals and historical snapshots remain intact. Invalid corrections are rejected before writing. |
| Language | English routes plus Korean `/ko/`. Static hosting has no request-header access: the first visit uses `navigator.languages`, with explicit stored user preference taking precedence. |
| Analytics | None. No account, advertising, cookie, tracking pixel or paid tier. Browser local storage holds only theme/language preferences. |
| PI scale | `PI_SCALE=0.20` remains provisional. Baseline/calendar checks across 365 days and one full TSFM integration are complete; the full 365-day multi-model replay and 90-day prospective review are not complete. No retrospective score is represented as live evidence. |
| Hosting | Cloudflare Pages preferred, connected to `main`, with `noindex` during the shadow period. GitHub repository created at [jongwonKim-1997/tsfm-live](https://github.com/jongwonKim-1997/tsfm-live). Cloudflare login is complete; account email verification and deployment verification remain separate requirements. |

Numerical definitions and edge cases are recorded in [math decisions](docs/math-decisions.md). The source of truth for constants is `pipeline/tsfm_live/config/settings.py`.

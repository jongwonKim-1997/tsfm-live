# Shadow backtest validation

**NOT A LIVE RECORD. Historical observations were downloaded later, may contain
revisions, and do not establish what was available at each historical run time.
Public TSFMs may have seen this history during training.**

## Completed partial validation

The saved [machine-readable result](shadow-backtest-results.json) simulates 365
run dates from **2025-10-08 through 2026-10-07**, using actual cached ECB and US
Treasury histories. It exercises calendars, eligibility, transformations, and
the two deterministic baselines. It writes no live-ledger records.

| Indicator | Eligible dates | Scored dates per baseline | Outside 24-hour horizon | Missing outcome in frozen snapshot |
|---|---:|---:|---:|---:|
| EUR/USD | 255 | 255 | 110 | 0 |
| USD/JPY, derived from ECB reference rates | 255 | 255 | 110 | 0 |
| US Treasury 10-year yield | 250 | 249 | 115 | 1 |

The result contains **1,518 scored baseline outputs**, from 759 indicator dates
times two baselines. The other 11 configured indicators were disabled in this
partial validation and have zero observations. Counts are not filled with
synthetic data.

| Indicator | rw0 mean grid CRPS | volnaive mean grid CRPS | Median RMSE, both baselines | volnaive 80% coverage |
|---|---:|---:|---:|---:|
| EUR/USD | 0.256037 | 0.162914 | 0.345189 | 0.811765 |
| USD/JPY | 0.336432 | 0.222764 | 0.498283 | 0.862745 |
| US Treasury 10-year yield | 3.353414 | 2.015938 | 4.242167 | 0.799197 |

The two FX rows are in log-change percentage units; the yield row is in basis
points. Raw loss magnitudes across these rows are not a common-scale ranking.
The baselines have identical medians, hence identical point RMSE, while their
distribution losses and interval coverage differ.

## Evidence and limits

The JSON records source URLs, UTC retrieval times, raw-response SHA-256 values,
history sizes, and every simulated date's eligibility state. It used 815 rows
for each derived ECB history and 691 Treasury rows. The missing final Treasury
outcome was left unavailable rather than invented or pulled in from a later
snapshot.

No foundation model was executed in this validation. No ensemble PI was
estimated and **PI_SCALE = 0.20 has not been validated**. This is not the complete
365-day, all-entrant end-to-end acceptance test. It does not validate a scheduler,
timely public commits, hosted CI, source availability at historical timestamps,
provider revision behavior, or the 90-day prospective shadow-live requirement.

## Remaining full validation

After the pinned model runtimes and weights pass smoke tests, repeat the
historical exercise with every enabled entrant, fixed history snapshots, source
evidence, seeds, and an external cache. Use only diagnostic output directories.
Report failures and skipped sessions, context/target timestamps, per-entrant
latency and memory, paired skill distributions, and elapsed critical-path time.
Keep its records out of `ledger/` and the live public API.

The production launch evidence must then be collected prospectively: 14
consecutive timely runs and at least 90 calendar days of shadow live. Historical
dates in this report cannot be counted toward either requirement.

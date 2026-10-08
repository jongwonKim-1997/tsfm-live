# Scoring and aggregation decisions

Implemented 2026-10-08. These notes resolve mathematical ambiguities in the
approved specification and are intended for consolidation into DECISIONS.md.

## Quantile CRPS, verified numerically

Every entrant uses `2 / 13 * sum(pinball_loss)` at exactly the 13 published
quantiles, with equal weights. This is the protocol's **quantile approximation**,
not the continuous-distribution CRPS and not quadrature with unequal weights.
Quantiles must be complete, finite, and nondecreasing. Actuals and computed
metrics must be finite. The median supplies point error and direction calls.

The independently generated standard normal quantiles, using `scipy.stats.norm.ppf`,
give **0.21119390132210775** at `y = 0`. The specification's rounded **0.211194**
is correct. The continuous normal CRPS at the same observation is
`(sqrt(2) - 1) / sqrt(pi) = 0.23369497725510913`; it must not replace the shared
quantile approximation for the normal baseline. The continuous formula is
documented in the [scoringrules normal CRPS reference](https://scoringrules.readthedocs.io/en/latest/generated/scoringrules.crps_normal.html).
The grid is symmetric, so a degenerate distribution's grid CRPS equals absolute
error exactly apart from floating point rounding. Both checks are in tests.

## CALL_EPS units

The specification's `0.01` and “1 bp” cannot both be used as raw values in both
target transforms. `CALL_EPS` is **0.01 percentage points of log return**. For
`diff_bp`, targets are already basis points, so the implementation converts the
threshold to **1.0 bp**. The comparison is strictly less than the threshold;
at exactly the threshold a direction call is counted. A zero actual has sign 0,
so a nonzero forecast of either sign is a miss. Baseline zero medians make no call.

## Common session windows and paired samples

For each indicator, select its last N distinct scored forecast run dates across
all entrants, then apply the stored regime filter. Every entrant shares these
window bounds. This prevents an entrant with missing recent forecasts from
silently reaching farther into the past. The intended ledger invariant is one
target per indicator per run. Duplicated score keys or inconsistent regime flags
within one indicator/run are rejected rather than resolved by ordering.

Every reported cell statistic uses the entrant/reference intersection. `n` and
`paired_n` count that intersection; `observed_n` additionally shows all of the
entrant's scored observations within the common window. The matrix contains
null when paired n is below 10, and the parallel `counts` map still exposes n.
This is a conservative clarification of the specification's otherwise ambiguous
mixture of unpaired point metrics and paired relative metrics. Ranking's 60-day
threshold also uses paired n, never an unpaired observation count.

Windows are selected before regime filtering: a 90-session high-volatility view
is the high-volatility subset of the latest 90 sessions, not the latest 90
high-volatility sessions from potentially much older history.

**7d conflict:** a seven-session window cannot satisfy `MIN_N_CELL = 10`.
Therefore its cells, overall skills, and tiers stay null, with available counts
shown. The minimum-sample rule is preserved instead of inventing seven-day tiers.
The 30d window can show tiers, but never rank numbers. Both short windows have
probation status with reason `short_window`.

## Undefined reference losses and zero model losses

A strictly positive reference loss permits the ordinary ratio, including a
genuine zero entrant loss. Any geometric mean containing a valid zero ratio is
zero, yielding skill 1. No arbitrary epsilon is added to either loss or ratio.

When the reference mean loss is zero, both `0/0` and positive/zero are undefined
for the finite JSON interface: the relative metric and its skill are null with
`undefined_*_reason: zero_reference_loss`. Observed statistics and counts remain
available. This applies even to the reference's own row; the usual self-skill
zero anchor exists whenever its denominator is positive. Cells with undefined
CRPS relative score cannot contribute to overall ranking eligibility or skill.
RMSE uses the same policy independently of CRPS.

## Confidence intervals and tiers

The implementation uses **circular moving blocks** of five consecutive entries
on the sorted, observed forecast-run-date axis. It draws 1,000 bootstrap vectors
with seed 7. Each date-weight vector is reused jointly across all enabled
indicators and entrants for a given window and regime. Real gaps stay missing;
missing observations are never encoded as zero loss. An individual cell's
bootstrap uses its paired observations under those same date multiplicities.

The originally eligible set of cells is fixed throughout resampling; eligibility
is not selected again inside each replicate. Weighted entrant/reference loss
sums recompute each relative loss; the overall score recomputes the geometric
mean across cells. Its 2.5th and 97.5th empirical percentiles form the CI.
The ensemble's indicator-level CI and PI significance use these same bootstrap
replicates. The API exposes `bootstrap_valid` and `bootstrap_requested`.

A replicate with a zero denominator or no sampled paired observations is
undefined. CIs are null unless at least 95% of requested replicates are finite,
preventing heavy conditioning on successful replicates. When sufficiently
complete, percentiles use the finite replicates. With no usable CI, tier and
significance are null rather than implying a middle tier. Otherwise A means
strictly positive lower bound, C means strictly negative upper bound, B includes
zero. Baseline self-skill is identically zero on positive-loss samples.

## Eligibility, pooled extras, history, and exact live-day counts

Numeric ranks require 60 paired sessions in at least `ceil(0.75 * enabled indicators)`
cells, on 90d/all windows. The overall geometric mean uses all cells with at
least ten paired observations and defined CRPS ratios, as specified. Extra hit
and coverage statistics pool those same eligible cells; the API exposes their
total `n`, called `hit_n`, `min_cell_n`, and `n_cells`. Exact-score ties use the
pooled paired strict-win rate, then stable entrant ID for deterministic output.
Baselines and the ensemble are always included, even with no data.
Leaderboard `n` (also `n_eligible`) counts observations contributing to valid
scored cells. Separate `paired_n_total` and `observed_n_total` retain the complete
window's counts across enabled indicators, including cells below the ten-pair
threshold. Thus three indicators with seven pairs each show 21 pairs even
though the seven-session overall score is null and its contributing `n` is zero.

PI uses the ensemble's 90d skill, clipped to [0,100]. At fewer than 30 paired
observations it is labeled `insufficient data`; if a ten-session cell is
available its numeric PI may still be shown greyed out. Regime PI is null below
30. `best_entrant` is a TSFM only, requires 60 pairs, and is marked post-hoc.
The published PI is rounded to 12 decimal places before labeling, preventing
floating arithmetic for an exact 10% improvement from showing 50 with a
below-50 label. Losses, ratios, skills, and confidence bounds are not rounded.

Snapshots provide rank change as current rank minus rank seven recorded runs
earlier. They are sorted by as-of date and duplicate dates are rejected.
PI history retains 180 daily entries including the current run, preserving null
PI values. The 30-day change requires the snapshot on the exact calendar date
30 days before as-of; no nearest-date substitution is made.

Scores alone cannot establish the date of an entrant's first successful
forecast (unscored forecasts may precede all observations). `scored_live_days`
therefore counts distinct scored run dates, and `live_days` is null unless the
caller supplies either exact `live_days` in entrant metadata, or both
`first_ok_run_date` and the complete `run_dates` list. The root pipeline can
derive that metadata from committed forecast/manifests.

## Integration

`score_forecast(y, q, target_transform='log_return_pct')` returns plain metric
dictionaries. `build_aggregates(scores, indicators, entrants, as_of, snapshots=None)`
returns `matrices`, `leaderboards`, `predictability`, and `snapshot`; it performs
no filesystem writes. Corrected ledger records must be resolved by the caller
before aggregation. Unscorable and non-ok records are also defensively excluded.

Matrix: `matrices[window].regimes[regime][indicator_id][entrant_id]` is a cell or
null; `.counts` mirrors the layout with counts, and `.window_dates` exposes the
actual date selection. Leaderboards have `.entrants` for all days and `.regimes`
for all/normal/high_vol. Predictability has `.indicators`, with uppercase `PI`
as specified, `regime_pi` values and parallel `regime_n` counts. Snapshots use
`.windows[window].entrants` and `.predictability.indicators`. Root owns JSON
serialization and append-only writes.

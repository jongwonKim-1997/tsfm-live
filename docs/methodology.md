# Methodology

TSFM Live compares outputs from publicly available time-series models with two
transparent baselines. Every valid output must be publicly committed before its
outcome is known. An empty table means no qualifying live evidence exists.
Historical simulations are kept separate from the prospective ledger.

## Targets and eligibility

The horizon is the next confirmed session close, no more than 24 hours after the
run. Models receive up to 512 transformed historical changes and no future data.
At least 300 history sessions are required. Prices and indices use
`y = 100 × ln(next / last)`; percentage-quoted yields use
`y = 100 × (next − last)` in basis points. Displays convert quantiles back to
levels only where the data provider permits it.

The run begins every day at 08:10 Asia/Seoul (23:10 UTC the preceding date).
Public lock-in is due at 08:50 Asia/Seoul. Source lags, non-session days, too-distant
next closes, invalid histories, model failures, and late publication are recorded
explicitly. They cannot be repaired by creating a retrospectively valid output.
Bitcoin uses the hourly candle ending at 23:00 UTC. Market calendars determine
other sessions, including holidays, early closes, and daylight-saving changes.

## Entrants and uncertainty

Foundation models use pinned package versions and pinned weight revisions.
They operate without fitting to this benchmark's realised outcomes. A failed
model is never replaced by a baseline under the model's name. A model version
change is a visible protocol change, with its prior history preserved.

`rw0` has all quantiles at zero. `volnaive`, the reference entrant, has a normal
distribution centered at zero with EWMA volatility (`lambda = 0.94`) estimated
only from available context. The ensemble is the quantile-wise median of the
foundation model outputs available on that day and requires at least three
successful models. Its displayed name includes that day's model count.

The common quantiles are
`0.025, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 0.975`.
Native, sampled, and interpolated quantiles are distinguished in the record.
Quantiles must be finite and monotone. An 80% interval uses the 0.10 and 0.90
quantiles; a 95% interval uses 0.025 and 0.975. These are distribution intervals,
not confidence intervals for an aggregate skill statistic.

## Per-output scores

The median is the point output. Squared error is `(median − actual)^2`; absolute
error is `abs(median − actual)`. For quantile probability `tau`, pinball loss is
`tau × (actual − quantile)` when the actual is at or above the quantile, otherwise
`(1 − tau) × (quantile − actual)`.

The primary score is the **quantile approximation of CRPS**:
`2 / 13 × sum(pinball losses on the published grid)`. Every entrant uses this
same approximation, including the normal baseline. Lower loss is better. A
standard normal distribution at actual zero scores 0.2111939013 on this grid;
its continuous analytical CRPS is a different quantity. See the mathematical
implementation notes for the numerical checks.

Direction hit compares the signs of the median and actual. A median magnitude
below 0.01 percentage points for log changes, or below 1 basis point for yield
changes, makes no call and receives a null hit. A magnitude exactly at the
threshold makes a call. A zero actual does not match a nonzero median. Baselines
with median zero therefore have no hit rate. Call rate and called sample size
are shown beside hit rate; its p-value is a two-sided binomial test against 0.5.

Interval coverage includes both endpoints. Width is upper minus lower quantile.
Coverage and width are displayed together; a wide interval alone does not imply
accurate probabilistic output.

## Windows, paired skill, and ranking

The 7d, 30d, and 90d windows count scored sessions of an indicator, not calendar
days. Each indicator's most recent N scored run dates are selected once for all
entrants, before any regime filter. A cell uses only dates shared with the
reference. Its `n` is the paired count; `observed_n` shows the entrant's count
before pairing. At fewer than ten pairs the cell is unavailable. Consequently,
the seven-session view exposes counts but cannot yet have valid cells or tiers.

CRPS relative loss is the entrant's mean loss divided by the reference mean on
the same dates; skill is one minus this ratio. RMSE skill follows the same
paired comparison using square roots of mean squared errors. A positive skill
means lower loss than the reference; zero means equal loss; a negative value
means higher loss. A zero reference denominator is undefined and shown as null.
A valid zero entrant loss remains zero without adding a smoothing constant.

Overall relative CRPS is the geometric mean of the eligible indicator relative
losses. Overall skill is one minus that geometric mean. Each eligible indicator
has equal influence on the geometric mean, independent of target scale.
Numeric ranks require at least 60 paired sessions in each of at least 75% of
enabled indicators, on the 90d or all-history view. Other entrants remain on
probation. Baselines and the ensemble are always visible. The 7d and 30d views
never display rank numbers.

Uncertainty uses 1,000 circular moving-block bootstrap draws with block length
five and seed seven. Dates are sampled jointly across indicators, preserving
cross-indicator dependence and actual missingness. Original cell eligibility
is fixed during resampling. The 2.5th and 97.5th percentiles form the 95%
confidence interval. If fewer than 95% of draws are defined, no interval or tier
is reported. A positive lower bound is tier A, a negative upper bound is tier C,
and an interval including zero is tier B. These are marginal intervals, not
multiple-comparison-adjusted claims that one model beats every other model.

Ranks sort by overall skill, then paired CRPS win rate. Rank change compares
with seven recorded runs earlier and is current rank minus earlier rank.
Regime views restrict the same window to its stored normal/high-volatility
labels. The labels use only information available at issuance: current EWMA
volatility compared with its prior 250-session distribution's 80th percentile.

## Indicator predictability

The Predictability Index uses the ensemble, preventing selection of whichever
single model looked best after seeing the outcomes. On the 90d window,
`PI = 100 × clip(ensemble CRPS skill / 0.20, 0, 1)`. Negative skill maps to zero;
20% or greater improvement maps to 100. The scale is fixed during the initial
shadow period and any later permitted revision requires a public decision.

Labels are: below 5, unpredictable; 5 to below 20, weak; 20 to below 50,
moderate; 50 or above, strong. Fewer than 30 paired observations receives
“insufficient data”, with any available numeric PI visually muted. Regime PI
requires 30 pairs within that regime. Significance is the ensemble skill CI's
lower bound above zero. The best individual model, when shown, requires 60
pairs and is explicitly marked as a post-hoc comparison.

Snapshots preserve daily ranks and PI history without rewriting old results.
PI history shows up to 180 daily observations, including nulls. The 30-day
change requires a snapshot on the exact earlier calendar date.

## Public record and limitations

Forecast files have canonical UTF-8 JSON bytes and SHA-256 hashes. The public
hash index refers to the commit containing those forecast bytes. Actuals,
scores, run manifests, corrections, and aggregate snapshots are append-only.
Corrections add a linked record; they never modify the original. The reader
applies accepted corrections when regenerating aggregates.

Outcomes are scored only after their target close and confirmed availability.
An outcome still unavailable five calendar days after the target is marked
unscorable with null metrics. The site renders generated JSON rather than
computing statistics in the browser. Public API responses expose the same
values and sample sizes.

The initial release must first establish at least 90 calendar days of live
shadow history. A historical simulation cannot establish a live record and
may be contaminated by model pretraining. Model failures, data revisions,
calendar definitions, and small samples remain visible limitations. A PI or a
rank describes this benchmark's observed one-session evaluation, not certainty
about future observations.

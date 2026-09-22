# Data card: synthetic historical borrowers

**Everything in this file describes 100% SYNTHETIC data.** No real applicant,
bureau or lender record was used to produce it. Numbers below are computed
directly from `data/synth/history.parquet` by `datagen/synthgen/data_card.py`
(re-run via `make datagen`) -- nothing here is hand-typed.

## Generation method
Each row draws a latent creditworthiness variable `z ~ N(0,1)` and an
UNOBSERVED shock `u ~ N(0,1)`, independently. Every canonical feature is a
noisy function of `z` plus a cohort-specific baseline and its own independent
noise term. `defaulted` is a separate noisy function of `z` **and** `u` (never
of the features directly). Because `u` never enters any feature, a scorecard
trained purely on the features can carry real signal about `defaulted`
(through the shared `z`) without the outcome being *derived* from the
features -- avoiding circular validation when Phase 5/8 score this same
history. `group_label` (A/B) is drawn independently of `z`, `u` and cohort,
and exists ONLY for the Phase 8 fairness audit; the scorecard never sees it.

## Summary statistics (computed, not asserted)
- Rows: 2000
- Overall default rate: 12.5% (target band: 10-14%)
- Split sizes: {'train': 1190, 'test': 418, 'val': 392}
- Cohort sizes: {'urban_ride': 610, 'urban_food': 487, 'semiurban_mixed': 451, 'rural_mixed': 193, 'resilient': 142, 'blind_spot': 117}
- Missing utility_* features (no utility bill on file): 7.0%
- Missing gig_* features (no gig payout on file): 7.0%
- Largest |correlation| between any feature and the synthetic `group_label`: 0.039
  (expected to be small since `group_label` is drawn independently; see table below)

## Feature vs. group_label correlation (leakage check)
| feature | point-biserial r vs group_label |
|---|---|
| utility_tenure_months | -0.012 |
| utility_on_time_ratio | -0.023 |
| weekly_inflow_cv | +0.007 |
| avg_daily_balance_inr | -0.023 |
| low_balance_day_ratio | -0.012 |
| gig_active_days_per_week | +0.018 |
| gig_weekly_earnings_cv | -0.001 |
| gig_tenure_weeks | +0.007 |
| income_reconciliation_ratio | -0.039 |
| verified_monthly_income_inr | -0.015 |

## Planted Stress-Test Cohorts (Two-Signal Calibration)
This dataset includes two designed stress-test cohorts (~7% of rows each) specifically
constructed to test the two-signal decision mechanism (transparent additive scorecard
versus pgvector precedent matching over the 10-dimensional signal embedding). These are
by-design synthetic stress-test cohorts, not "discovered" real-world phenomena:
- `blind_spot` (~7% of rows): High scores on scorecard-weighted factors (utility tenure >= 16mo,
  on-time ratio > 0.90, low weekly inflow CV) but brittle cashflow visible only in unweighted
  embedding dimensions (short gig tenure < 10 weeks, high earnings CV > 0.50, high low-balance day ratio > 0.45).
  These borrowers default at an elevated rate (30-40%) because their underlying cashflow is fragile.
- `resilient` (~7% of rows): Low or thin scores on scorecard-weighted factors (utility tenure <= 5mo,
  moderate balance, lower on-time ratio) landing in DECLINE or low REFER score bands, but stable
  operational health visible in unweighted embedding dimensions (long gig tenure > 50 weeks,
  low earnings CV < 0.20, near-zero low-balance days). These borrowers default at a very low rate (3-5%).

## Known limitations
- This is a synthetic generative model, not a fit to real bureau data. Default
  rates, correlations and score bands demonstrate the PIPELINE, not real-world
  predictive accuracy. Never quote these numbers as production credit-risk
  statistics.
- The archetype/cohort baselines were chosen for plausibility and deliberate stress-testing,
  not calibrated against external population statistics.

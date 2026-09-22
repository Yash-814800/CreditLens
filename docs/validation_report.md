# Scorecard validation report

**SYNTHETIC DATA.** Every number below is computed by `scripts/validate_scorecard.py` against `data/synth/history.parquet`'s held-out TEST split (never touched during Phase 5's calibration, which used the VALIDATION split only -- see `scripts/tier_distribution.py`). This is a pipeline-correctness demonstration on synthetic, latent-variable-generated data, **not a claim of real-world predictive accuracy** on real applicants, per CLAUDE.md rule 4.

TEST split size: n=418

## Tier mix and default rate by tier

| Tier | Share | n | Default rate |
|---|---|---|---|
| APPROVE | 35.2% | 147 | 0.143 |
| REFER | 18.4% | 77 | 0.117 |
| DECLINE | 46.4% | 194 | 0.175 |

**Monotonic (APPROVE <= REFER <= DECLINE default rate): False**

## Default rate by score decile

| Score decile | Default rate | n |
|---|---|---|
| (-0.001, 7.4] | 0.214 | 84 |
| (7.4, 24.0] | 0.186 | 43 |
| (24.0, 37.0] | 0.098 | 41 |
| (37.0, 49.0] | 0.190 | 42 |
| (49.0, 64.0] | 0.047 | 43 |
| (64.0, 73.0] | 0.075 | 40 |
| (73.0, 81.0] | 0.152 | 46 |
| (81.0, 90.0] | 0.200 | 40 |
| (90.0, 100.0] | 0.154 | 39 |

## Discrimination metrics

AUC is computed here as `P(score_nondefaulter > score_defaulter)` via the Mann-Whitney rank-sum identity (equivalent to `sklearn.metrics.roc_auc_score`, reimplemented with `pandas`/`numpy` rank statistics to avoid adding scikit-learn as a dependency for one script).

- **AUC**: 0.553
- **Gini** (2*AUC - 1): 0.106
- **KS statistic**: 0.148

## Agreement with the pgvector two-signal precedent rule

Offline replay of `app/services/scoring/decision.py`'s `_apply_two_signal` rule: for every TEST-split applicant, a real k=25 cosine-similarity peer lookup is run against the TRAIN split's embeddings only (never TEST/VAL rows, and never the applicant's own row -- unlike a live query against the fully-seeded `historical_borrowers` table, which currently holds every split at once). REFER-tier applicants are excluded (the real rule never touches a REFER outcome), matching `decision.py`'s own logic exactly.

- Checked (APPROVE/DECLINE with a large-enough peer group): 341
- Agree: 260
- Disagree (would be downgraded/upgraded to REFER): 81
- Skipped (REFER tier, or peer group below `min_sample_size`): 77
- **Agreement rate: 76.2%**

## Weight-sensitivity (stretch item): +/-20% perturbation of every factor's points

Every bin's points in a copy of the frozen `scorecard_v1.yaml` are scaled by the given factor (base points unaffected), the TEST split is re-scored, and the fraction of applicants whose tier changes as a result is reported.

- All points x1.20: 12.4% of TEST-split applicants flip tier
- All points x0.80: 24.4% of TEST-split applicants flip tier

## Limitations

- This history dataset is synthetic: `defaulted` is generated from a latent creditworthiness variable plus an independent unobserved shock (see `docs/data_card.md`), deliberately NOT derived from the scorecard's own features, specifically to avoid circular validation -- but it is still a simulation, not observed real-world repayment behaviour.
- `authenticity_score` has no history-dataset column (the synthetic history has no fraud simulation) and is fixed at 0.95 for every row here, same as `scripts/tier_distribution.py` -- this validation exercises the other 6 factors only.
- The two-signal agreement check is an offline reimplementation for validation purposes (TRAIN-only peer pool), not a call to the live `/api/v1` precedent-matching endpoint, which is exercised separately by `backend/tests/integration/test_pipeline_full.py`.


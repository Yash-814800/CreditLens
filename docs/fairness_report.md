# Fairness audit and adverse-impact evaluation

**SYNTHETIC DATA.** Every number below comes from re-scoring the held-out `data/synth/history.parquet` **TEST split** (n=418) with the real, frozen `scorecard_v1.yaml` and `policy_v1.yaml` via `scripts/fairness_audit.py`. Inspiration: Upstart's 2017 CFPB no-action letter, which came with periodic adverse-impact and access-to-credit testing by demographic group (see claude_code_prompt_pack.md's references).

## 1. Adverse-impact (four-fifths) test by synthetic `group_label`

`group_label` (A/B) is generated independently of every scoring feature, latent variable, and `defaulted` status (measured max correlation <= 0.041 in `docs/data_card.md`). By construction, this synthetic population has no baked-in structural disparities. **A pass is therefore expected; the primary engineering and governance value here is demonstrating the audit harness, not asserting real-world demographic fairness.** Evaluating this harness against held-out TEST rows verifies that the statistical measurement pipeline functions soundly.

### Overall approval rate by group (`test` split, n=418)

| Group | Approval rate | Approved | Total (n) | 95% Wilson confidence interval |
|---|---|---|---|---|
| Group `A` | 37.1% | 85 | 229 | [0.311, 0.435] |
| Group `B` | 32.8% | 62 | 189 | [0.265, 0.398] |

- **Adverse-impact ratio (AIR):** `32.8%` / `37.1%` = **0.884** (threshold >= 0.80 -> **PASS**).
- **Conclusion:** Overall disparity does not violate the four-fifths rule on the clean test split.

### Per-cohort approval rates and adverse-impact ratios

To ensure fairness is not masking localized subgroup imbalances, we evaluate approval rates across all synthetic cohorts, specifically tracking the **blind-spot** and **resilient** cohorts.

| Cohort | Total (n) | Group A approval | Group B approval | AIR | 4/5ths Rule | Notes |
|---|---|---|---|---|---|---|
| `blind_spot` | 32 | 100.0% (n=16) | 100.0% (n=16) | 1.000 | **PASS** | Blind-spot cohort (scorecard approves 100% due to pristine utility file) |
| `resilient` | 31 | 0.0% (n=20) | 0.0% (n=11) | 1.000 | **PASS** | Resilient cohort (scorecard declines 100% due to thin utility file) |
| `urban_ride` | 105 | 49.2% (n=59) | 34.8% (n=46) | 0.708 | **FLAG** | Core gig demographic cohort |
| `urban_food` | 117 | 35.3% (n=68) | 38.8% (n=49) | 0.910 | **PASS** | Core gig demographic cohort |
| `semiurban_mixed` | 92 | 24.4% (n=45) | 19.1% (n=47) | 0.783 | **FLAG** | Core gig demographic cohort |
| `rural_mixed` | 41 | 23.8% (n=21) | 10.0% (n=20) | 0.420 | **FLAG** | Small sample (n=41); binomial noise dominates |

> [!NOTE]
> **Key Cohort Invariants:**
> 1. **`blind_spot` cohort:** Reaches 100.0% scorecard approval for both Group A and Group B (AIR = 1.000). The scorecard alone is blind to their unweighted volatility features, approving all applicants equally.
> 2. **`resilient` cohort:** Has 0.0% scorecard approval for both Group A and Group B (AIR = 1.000). Their thin utility history pushes them to decline across both groups equally before precedent review.
> 3. **Sub-cohort sample size notice:** In smaller cohorts such as `rural_mixed` (n=41, with 21 in A and 20 in B), a swing of just 2-3 approvals shifts the approval rate by >10 percentage points, leading to a sample-induced AIR fluctuation. This demonstrates why sub-cohort analysis must be reported with sample sizes and confidence intervals.

## 2. Access-to-credit vs. a bureau-only baseline

### Transparent baseline definition
Traditional credit underwriting relies on established credit bureau history (e.g. CIBIL score >= 650, >= 2 seasoned credit trade lines). Under this standard policy:
- All new-to-credit (NTC) / thin-file applicants lack traditional credit bureau trade lines.
- Because a bureau-only policy has zero signal for 100% of this population, it declines (or turns away) every applicant without a bureau record: **0.0% approval rate, 0.0% refer rate, 100.0% decline rate**.

> [!IMPORTANT]
> **Strawman Baseline Notice:** The 0.0% bureau-only baseline is a **strawman by construction**. Because this entire synthetic population represents thin-file gig workers with no bureau records, the measured uplift is a **demonstration of the alternative-data mechanism** (enabling underwriting where none was possible), not an empirical real-world claim about real applicants' credit access.

### Access-to-credit uplift on held-out TEST split (n=418)

| Decision tier | Bureau-only strawman baseline | CreditLens alternative-data engine | Net access uplift |
|---|---|---|---|
| **Approved (outright)** | 0.0% (0) | **35.2%** (147) | +35.2% |
| **Referred (manual review)** | 0.0% (0) | **18.4%** (77) | +18.4% |
| **Total credit access / review** | 0.0% (0) | **53.6%** (224) | +53.6% |
| **Declined** | 100.0% (418) | **46.4%** (194) | -53.6% |

- **Outright approval uplift:** **+35.2%** (147/418) of NTC applicants gain immediate unsecured credit lines based on alternative data (verified gig earnings, utility timeliness, cash-flow buffers) without a traditional bureau record.
- **Opportunity recovery:** An additional **+18.4%** (77/418) receive a starter limit or human underwriter review rather than being rejected outright for lack of bureau data.

## 3. Proxy feature test & production sanitizer defense

A central risk in alternative-data credit scoring is **redlining-by-proxy**: an algorithm might exclude explicit protected attributes (such as religion, caste, or gender), but incorporate a seemingly neutral proxy feature (such as a pincode-derived risk index or regional cost-of-living factor) that strongly correlates with demographics, resulting in severe disparate impact.

### Experimental setup
1. **Synthetic proxy feature:** On a copy of the TEST split, we introduce `pincode_zone_risk`, strongly correlated with `group_label`:
   - Group A applicants have an 85% probability of `ZONE_LOW_RISK` (+15 points in scoring) and 15% `ZONE_MEDIUM_RISK` (0 points).
   - Group B applicants have an 85% probability of `ZONE_HIGH_RISK` (-25 points in scoring) and 15% `ZONE_LOW_RISK` (+15 points).
2. **Unprincipled strawman model:** We simulate an unprincipled scorecard that incorporates this proxy factor into the total score.
3. **Production allowlist defense:** We pass the exact same profile through CreditLens's production `app.services.guardrails.sanitizer.sanitize()` gate before scoring.

### Results: proxy vulnerability vs. allowlist immunity

| Architecture mode | Group A approval | Group B approval | Adverse-impact ratio (AIR) | Four-fifths rule | Disparity status |
|---|---|---|---|---|---|
| **Clean baseline** (canonical features only) | 37.1% (85) | 32.8% (62) | **0.884** | **PASS** | Compliant (AIR >= 0.80) |
| **Unprincipled strawman model** (includes proxy) | 47.2% (108) | 11.1% (21) | **0.236** | **FAIL** | **Severe disparate impact detected** |
| **Production CreditLens** (with allowlist sanitizer) | 37.1% (85) | 32.8% (62) | **0.884** | **PASS** | **Sanitizer drops proxy; 100% clean** |

### Key findings from the proxy test:
1. **Audit harness sensitivity:** When an unprincipled feature is included, the adverse-impact ratio plummets from `0.884` to **`0.236`**, causing an immediate **FAIL** on the four-fifths rule. This proves the audit harness is not decorative -- it decisively flags disparate impact when present.
2. **Allowlist defense in depth:** Under `app/services/guardrails/sanitizer.py` (CLAUDE.md rule 7), only `CANONICAL_FEATURE_NAMES` are permitted through. When `pincode_zone_risk` is present in the intake context, the sanitizer drops it unconditionally with reason: `field is not on the scoring allowlist; dropped by default`. Because the allowlist is fail-closed, no engineer has to anticipate or maintain a list of forbidden proxy names. The production pipeline remains mathematically invariant to proxy injection.

## 4. Limitations and real-world audit requirements

1. **Synthetic group labels:** `group_label` is synthetic and generated independently of creditworthiness (max feature correlation <= 0.041). In real-world lending, socioeconomic factors frequently correlate with protected attributes due to historical systemic disparities. A synthetic pass does not guarantee fairness on real populations.
2. **Small groups and sub-cohort variance:** With n=418 in the TEST split, smaller cohorts (such as `rural_mixed` at n=41) suffer from statistical instability in four-fifths calculations. Subgroup metrics must always be interpreted alongside sample sizes and confidence intervals.
3. **Absence of intersectional analysis:** This audit measures a single binary demographic dimension (A vs. B). A comprehensive audit must assess multi-axis intersectionality (e.g. gender x caste x geography x age cohorts).
4. **What a production compliance audit would add:**
   - **Real demographic data & outcome tracking:** Periodic post-issuance monitoring tracking default and repayment rates by protected group.
   - **Cadence & drift monitoring:** Automated quarterly adverse-impact re-testing alongside Population Stability Index (PSI) tracking.
   - **Less-Discriminatory-Alternative (LDA) search:** Systematic search across alternative feature weightings, bin thresholds, and alternative data sources to identify candidate models that achieve equal or superior predictive accuracy with reduced demographic disparity, in compliance with regulatory fair lending mandates.


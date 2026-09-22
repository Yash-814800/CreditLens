# CreditLens — Known Limitations

> [!IMPORTANT]
> This document is an honest, comprehensive inventory of the gaps and assumptions present in the CreditLens prototype as submitted for the hackathon. Every number quoted here is drawn directly from internal evaluation runs; none are estimated or extrapolated.

---

## 1. Data

### 1.1 Synthetic training corpus
The scorecard and all ML components were developed on a corpus of **2,000 synthetic borrowers** whose features were generated from latent-variable models, not sampled from real loan books. The synthetic generation process captures broad statistical structure (income-to-debt ratios, repayment trajectories) but it **cannot reproduce the tail distributions, regional biases, or macroeconomic correlations** found in production lending data. No number in this repo demonstrates real-world predictive accuracy.

### 1.2 No real bureau data
CreditLens has **no integration with CIBIL, Experian, or Equifax**. All creditworthiness signals are derived from self-reported documents and extracted transaction history. Bureau-tradeline depth, derogatory marks, and enquiry counts — the backbone of any real scoring model — are entirely absent.

### 1.3 No real default observations
Because the dataset is synthetic, there are **no observed defaults**. The binary outcome used for scorecard training is a simulated label derived from the same latent variables that generated the features, creating an optimistic closed loop. The `defaulted` label is a reasonable stand-in for demonstrating a scoring *pipeline*, not a substitute for real outcome data.

### 1.4 AUC caveat
The logistic scorecard achieves **AUC = 0.553** on the held-out synthetic test set. This is modest discrimination only marginally better than random (0.50) and is almost certainly inflated relative to what the same model would achieve on real-world heterogeneous applicants. **Real-world calibration against actual defaults is required before any production deployment.**

### 1.5 Planted two-signal stress cohorts
The blind-spot cohort (6.5% prevalence, n=134) and resilient cohort (7.4% prevalence, n=154) in the synthetic history dataset were **explicitly designed and planted** to stress-test and prove the pgvector two-signal override rule. While the **68.8% blind-spot catch rate** and **82.8% resilient recovery rate** demonstrate that 10-dimensional nearest-precedent intervals reliably catch what the 7-factor scorecard ignores, they reflect an engineered stress fixture rather than the natural incidence of these archetypes in a live applicant population.

### 1.6 Strawman bureau-only fairness baseline
In `docs/fairness_report.md`, the bureau-only comparison baseline has a **0.0% approval rate by construction**, because the entire synthetic population was defined as thin-file gig workers without bureau trade lines. The reported **+53.6% credit access expansion (+35.2% outright approve, +18.4% refer)** is a conceptual demonstration of the alternative-data underwriting mechanism, not an empirical market uplift measurement against existing lender underwriting funnels.

---

## 2. Document Forensics

### 2.1 ELA (Error Level Analysis) — what it cannot detect

ELA is effective at identifying JPEG re-compression artifacts from localized pixel edits. It has a confirmed blind spot:

- **`consistent_edit` (full-document coherent compression):** If an adversary re-saves an entirely altered document at a uniform quality level, ELA sees no differential artifact and the tamper goes undetected. There is no local compression-mismatch signal for this attack class; it is not flagged by the current implementation.
- **`crop_2pct` and `rotate_1deg`:** A 2 % crop or 1-degree rotation is sufficient to defeat perceptual hash matching (at threshold T = 6) and can also distort ELA energy maps enough to suppress detection.

### 2.2 pHash — threshold tuning and false-positive rate

The perceptual hash threshold **T = 6** was tuned on a **single utility-bill template** and **two gig-payout statement templates** — the three document types present in the demo pack. Generalisation to other document templates has **not been validated**.

Known failure modes:
- **Crop / rotate attacks** (see §2.1) defeat the current T = 6 threshold.
- On the demo-pack cross-persona benchmark, the raw **false-positive rate (FPR) is 3.41 %** before the corroboration gate is applied. The gate reduces operational FPR substantially, but the underlying hash is not discriminative enough to stand alone.

### 2.3 Bank statement forensics

Bank statement verification is **arithmetic-based, not ELA-based**. The chain-balance verification (running balance ≡ prior balance + credit − debit) is what drives detection:

- The attack `inserted_fake_credit_with_rebalanced_chain` achieves **F1 = 1.00** for detection *only because* the inserted row breaks the running-balance chain — i.e., the detector is catching an arithmetic inconsistency, not a visual one.
- **Consistent multi-row edits that happen to balance** — for example, proportionally scaling every row — could theoretically pass the chain verification. This is noted in the codebase but no countermeasure is currently implemented.

### 2.4 Self-consistency checks

The self-consistency module re-submits the same document under differently ordered prompts and compares Gemini's extractions. Because **Gemini at temperature = 0 is deterministic across prompt orderings**, this check yields **0.0 % detection on visual tampers**: the model returns the identical extraction or hallucination every time, and variance never surfaces.

Self-consistency is only useful here for catching prompt-sensitivity in *unstable* extractions (e.g., ambiguous layout), not for adversarial robustness.

### 2.5 Adversarial document injection

Guardrail patterns and model-reported flags defend against prompt-injection attempts embedded in document content. However, **very small or very low-contrast injected text** partially depends on the model's visual resolution limit. If injected text falls below the effective OCR resolution of the vision model, the guardrail may not trigger.

### 2.6 Metadata forensics

Metadata checks (EXIF Software / PDF Producer tags) carry an acknowledged false-positive risk: many legitimate scanning apps also stamp an editor tag, so this signal alone never drives a HIGH-severity finding. It is a corroborating indicator only.

---

## 3. Infrastructure

### 3.1 Background task queue

Document processing pipelines are dispatched via **FastAPI `BackgroundTasks`**, which run in the same process as the API server. This is not a durable task queue:

- Tasks are **lost on process crash or restart** — there is no persistence, retry logic, or dead-letter handling. (Every pipeline stage is atomic and idempotent, so a restarted run never leaves a half-written decision — but the trigger itself is lost.)
- **Connection count is uncontrolled at scale**: each background task may open its own database or storage connection without back-pressure, risking connection exhaustion under concurrent load.

A production system would require a proper queue (e.g., Celery + Redis, or a managed queue service) with worker autoscaling.

### 3.2 Single-node deployment

The prototype runs on a **single-node deployment**:

- **No load balancer** — all traffic hits one instance; there is no horizontal scaling or failover.
- **Single RDS-equivalent database** — no read replicas, no standby; any instance failure takes down the entire service.
- No connection pooling layer (e.g., PgBouncer) in front of the database.
- The extraction cache is a local JSON file, adequate for a single-node hackathon deployment but not a shared cache across multiple backend instances.

This architecture is acceptable for a hackathon demo but is not suitable for any production or even staging traffic.

---

## 4. Language & Document Variety

### 4.1 English-only extraction prompts

All LLM extraction prompts are written in English. Documents containing **non-Latin scripts** (Devanagari, Tamil, Telugu, Bengali, etc.) or **regional-language text** may extract poorly or return empty fields. India's lending market is deeply multilingual; this is a significant coverage gap for real deployment.

### 4.2 Narrow template coverage

pHash tuning and ELA calibration were performed against:
- One utility-bill template
- Two gig-payout statement templates

**No other document types** (rent agreements, GST filings, ITRs, salary slips from diverse payroll vendors) have been validated. Detection performance on unseen templates is unknown.

---

## 5. Privacy & Compliance

### 5.1 Consent and data retention

Consent withdrawal and retention purge flows are implemented and functional. However:

- **Data residency is single-region: `ap-south-1` (Mumbai) only.** Cross-region replication, disaster-recovery failover to a second region, and multi-region data sovereignty controls are not in place.
- There is no automated audit trail of all data access events — only application-level logs.

### 5.2 Aadhaar handling

Raw Aadhaar numbers are **never persisted**. The system stores an **HMAC-SHA256 hash with a server-side pepper**, which is the correct approach for deduplication without retaining PII.

Caveat: **deduplication accuracy depends entirely on Aadhaar number validity**. If a borrower supplies an incorrect, cancelled, or fictitious Aadhaar number at enrolment, the hash will not match a legitimate existing record, and the deduplication gate will pass silently.

### 5.3 Legal compliance scope

No claim of legal compliance is made anywhere in this repo (DPDP Act alignment, FCRA/ECOA-shaped adverse-action notice content, RBI digital-lending wording). These are design-alignment statements made to illustrate architectural intent, not the product of a legal review.

---

## 6. ML / AI

### 6.1 No retraining loop

There is **no feedback pipeline** connecting loan-officer decisions or eventual repayment outcomes back into the model. The scorecard weights are frozen at the values learned from synthetic data. Model staleness will grow immediately from day one of any real deployment.

### 6.2 No drift monitoring

There is no mechanism to detect **feature drift** (changes in the distribution of incoming applicant features) or **concept drift** (changes in the relationship between features and default risk). A model trained in one economic cycle can silently degrade in another without any alerting.

### 6.3 pgvector approximate search

The pgvector index is built with **HNSW (Hierarchical Navigable Small World)**, which provides approximate nearest-neighbour search, not exact k-NN. For small populations this approximation is negligible. For **large populations**, recall can drop below 100 %, meaning some genuinely similar applicant vectors may be missed during corroboration or deduplication queries. The HNSW parameters (`m`, `ef_construction`) have not been tuned beyond defaults.

### 6.4 Model catalog instability

The Gemini model catalog drifted during this project's own development (two candidate model IDs 404'd mid-build). The live-discovery design in `scripts/pick_gemini_models.py` exists specifically because model IDs are not a stable long-term constant — but this also means the exact model version evaluated in `docs/fraud_eval.md` and `docs/extraction_eval.md` may differ from the model served at review time.

---

## 7. Recourse

### 7.1 Advice is gameable

The recourse module explains which scorecard factors are dragging an applicant's score down and suggests steps to improve them (e.g., reduce utilisation, add a co-applicant). Because the scorecard logic is deterministic and partially transparent, a sophisticated applicant can **reverse-engineer the advice to game the score** without genuinely improving creditworthiness.

### 7.2 Advice is not grounded in bureau data

Recourse tips are derived from **scorecard feature weights on synthetic data**, not from actual bureau tradeline logic. Advice such as "your repayment history is the primary drag" is computed from extracted transaction history — not from CIBIL bureau records that a real lender would consult. The guidance may therefore be **directionally correct but calibratively wrong** relative to what a bureau-integrated system would recommend.

---

## Summary Table

| Area | Key Limitation | Severity |
|---|---|---|
| Data | 2,000 synthetic borrowers; no real defaults; AUC = 0.553 | High |
| Forensics — ELA | Blind to `consistent_edit`; `crop_2pct` / `rotate_1deg` bypass | High |
| Forensics — pHash | T = 6 tuned on 3 templates; raw cross-persona FPR = 3.41 % | Medium |
| Forensics — Bank stmt | Balanced multi-row edits could pass chain verification | Medium |
| Forensics — Self-consistency | 0.0 % detection on visual tampers (deterministic model at temp = 0) | Medium |
| Infrastructure | `BackgroundTasks` not a queue; single-node; no load balancer | High |
| Language | English-only prompts; non-Latin scripts extract poorly | High |
| Privacy | Single-region (`ap-south-1`) data residency only | Medium |
| Aadhaar | Dedup accuracy depends on Aadhaar validity | Low–Medium |
| ML/AI | No retraining, no drift monitoring; HNSW approximate k-NN | High |
| Recourse | Gameable; not grounded in real bureau data | Medium |

---

*Last updated: 2026-09-22 · CreditLens Hackathon Submission*

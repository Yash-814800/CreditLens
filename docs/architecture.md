# Architecture

The Mermaid source for every diagram in the README, kept here as the canonical copy so it can be
exported to static images (`docs/diagrams/`) without editing the README's prose around it. See
[`README.md`](../README.md) for the same diagrams in context, and `docs/deployment.md` (Phase 9,
once built) for the deployment runbook this AWS diagram's target shape belongs to.

## System flow

```mermaid
flowchart LR
    subgraph Intake["Multi-modal intake"]
        U1[Gig payout screenshot]
        U2[Utility bill]
        U3[Bank / UPI CSV]
    end

    subgraph Engine["Dual-layer decision engine"]
        EX[Extraction service<br/>Gemini vision, strict schema]
        FR[Fraud & integrity layer<br/>pHash, ELA, arithmetic checks]
        SA[Allowlist sanitizer]
        SC[Transparent scorecard]
        PR[pgvector precedents<br/>k-NN + Wilson CI]
        DC[Policy engine<br/>two-signal decision]
        SU[Grounded summary<br/>+ verifier]
    end

    subgraph Out["Underwriter cockpit"]
        WB[Two-panel workbench]
        AU[Hash-chained audit log]
    end

    U1 --> EX
    U2 --> EX
    U3 --> EX
    EX --> FR
    EX --> SA
    FR --> DC
    SA --> SC
    SC --> DC
    SC --> PR
    PR --> DC
    DC --> SU
    DC --> WB
    SU --> WB
    FR --> WB
    EX -. every stage .-> AU
    DC -. every stage .-> AU
    AU --> WB
```

## Pipeline sequence

```mermaid
sequenceDiagram
    participant UW as Underwriter (browser)
    participant API as FastAPI /api/v1
    participant PIPE as pipeline.py
    participant LLM as Gemini (extraction + summary)
    participant DB as Postgres + pgvector
    participant AUDIT as audit_log (hash-chained)

    UW->>API: POST /applications (KYC + consent + 3 files)
    API->>DB: create application (stage=UPLOADED)
    API-->>UW: 202 Accepted {id}
    API->>PIPE: process_application(id) [BackgroundTasks]

    PIPE->>LLM: extract each document (untrusted-data prompt, schema-locked)
    LLM-->>PIPE: extracted fields + confidence
    PIPE->>AUDIT: DOCUMENT_EXTRACTED

    PIPE->>PIPE: fraud & integrity checks (pHash, ELA, arithmetic, cross-field)
    PIPE->>AUDIT: FRAUD_CHECKED

    PIPE->>PIPE: allowlist sanitizer -> ScoringInput
    PIPE->>AUDIT: GUARDRAIL_APPLIED

    PIPE->>PIPE: compute_score() (versioned scorecard YAML)
    PIPE->>AUDIT: SCORED

    PIPE->>DB: k-NN precedent match (cosine, HNSW)
    DB-->>PIPE: peer default rate + Wilson CI
    PIPE->>AUDIT: PRECEDENTS_MATCHED

    PIPE->>PIPE: decide() -- fraud gate, completeness gate, tiers, two-signal rule
    PIPE->>AUDIT: DECISION_MADE

    PIPE->>LLM: grounded summary (computed values only)
    LLM-->>PIPE: summary text
    PIPE->>PIPE: grounding verifier (retry once, else template)
    PIPE->>AUDIT: SUMMARY_GENERATED

    PIPE->>DB: stage=COMPLETE
    UW->>API: GET /applications/{id} (polls stage)
    API-->>UW: full result: score, decision, precedents, recourse, notice
```

## Data model

```mermaid
erDiagram
    APPLICANTS ||--o{ APPLICATIONS : submits
    APPLICATIONS ||--o{ DOCUMENTS : has
    APPLICATIONS ||--o{ FRAUD_FINDINGS : has
    APPLICATIONS ||--o{ SCORECARD_RESULTS : has
    APPLICATIONS ||--o{ PRECEDENT_MATCHES : has
    APPLICATIONS ||--o{ DECISION_ARTIFACTS : has
    HISTORICAL_BORROWERS ||--o{ PRECEDENT_MATCHES : "matched by"
    USERS ||--o{ AUDIT_LOG : "acts in"

    APPLICANTS {
        uuid id PK
        text phone_hash
        text pan_masked
        text aadhaar_hash
        timestamptz consent_at
    }
    APPLICATIONS {
        uuid id PK
        uuid applicant_id FK
        numeric requested_line_inr
        text stage
        text outcome
        text final_outcome
        int score
        text fraud_severity
        numeric eligible_line_inr
    }
    DOCUMENTS {
        uuid id PK
        uuid application_id FK
        text doc_type
        text sha256
        bit phash
        jsonb extracted
    }
    FRAUD_FINDINGS {
        bigint id PK
        uuid application_id FK
        text check_name
        text severity
    }
    SCORECARD_RESULTS {
        uuid id PK
        uuid application_id FK
        jsonb factors
        int total
    }
    HISTORICAL_BORROWERS {
        uuid id PK
        vector signal_vector
        bool defaulted
        bool synthetic
    }
    PRECEDENT_MATCHES {
        uuid id PK
        uuid application_id FK
        uuid historical_id FK
        float similarity
    }
    DECISION_ARTIFACTS {
        uuid id PK
        uuid application_id FK
        text kind
        jsonb content
    }
    AUDIT_LOG {
        bigserial id PK
        text event_type
        text actor
        text prev_hash
        text row_hash
    }
    USERS {
        uuid id PK
        text email
        text role
    }
```

## AWS deployment (target shape — Terraform + runbook land in Phase 9)

```mermaid
flowchart TB
    subgraph Internet
        Browser
    end
    subgraph AWS["AWS (ap-south-1)"]
        subgraph EC2["EC2 (t3.medium, IMDSv2, encrypted gp3)"]
            Caddy["Caddy (HTTPS, only public listener)"]
            FE[Frontend container]
            BE[Backend container]
            PG["Postgres + pgvector container"]
        end
        S3["S3 (private, SSE, no public access)"]
        SSM["SSM Parameter Store (secrets)"]
        CW["CloudWatch (logs + alarms)"]
    end
    Browser -->|HTTPS| Caddy
    Caddy --> FE
    Caddy --> BE
    BE --> PG
    BE -->|documents| S3
    BE -->|reads secrets at boot| SSM
    BE -->|logs| CW
```

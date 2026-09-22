"""Domain contract constants from CLAUDE.md's "Domain contracts" section.

Single source of truth: every other module (DB constraints, API schemas, services)
imports these instead of re-declaring the string values, so the contract cannot drift.
"""

DOC_TYPES = ("GIG_PAYOUT", "UTILITY_BILL", "BANK_STATEMENT")
OUTCOMES = ("APPROVE", "REFER", "DECLINE")
FRAUD_SEVERITIES = ("NONE", "LOW", "MEDIUM", "HIGH")
STAGES = (
    "UPLOADED",
    "EXTRACTING",
    "FRAUD_CHECK",
    "SANITIZING",
    "SCORING",
    "PRECEDENT_MATCH",
    "DECIDING",
    "SUMMARIZING",
    "COMPLETE",
    "FAILED",
)
ROLES = ("underwriter", "auditor", "admin")
AUDIT_EVENT_TYPES = (
    "APPLICATION_SUBMITTED",
    "DOCUMENT_EXTRACTED",
    "FRAUD_CHECKED",
    "GUARDRAIL_APPLIED",
    "SCORED",
    "PRECEDENTS_MATCHED",
    "DECISION_MADE",
    "SUMMARY_GENERATED",
    "NOTICE_GENERATED",
    "DECISION_OVERRIDDEN",
    "LOGIN",
    "CONSENT_WITHDRAWN",
    "RETENTION_PURGE",
)


def sql_in_list(values: tuple[str, ...]) -> str:
    """Render a tuple of identifiers as a SQL `'a','b','c'` literal list for CHECK constraints."""
    return ",".join(f"'{v}'" for v in values)

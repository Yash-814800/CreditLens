"""Responsible-AI guardrail sanitizer (CLAUDE.md rule 7): an ALLOWLIST, not a
denylist. `sanitize()` is the single gate between "everything we know about an
application" and "what the scorecard is allowed to see" -- Phase 6's pipeline
must call this before app/services/scoring/scorecard.py ever runs, and nothing
else in the codebase is allowed to hand raw application context to the
scorecard.

Design: allowlist-by-construction, not "remove the bad stuff". Only the 11
canonical CLAUDE.md features (app.services.scoring.features.CANONICAL_FEATURE_NAMES)
are ever copied into the output. Every other key present in the input --
whether it's a known PII field we can name a reason for, or something nobody
anticipated -- is dropped and recorded. A new field added anywhere else in the
codebase without also being added to CANONICAL_FEATURE_NAMES is therefore
*sanitized out by default*, which is the point: CLAUDE.md rule 7 requires this
to fail closed, not rely on someone remembering to denylist it.

A second, independent layer of defense: even a key that IS on the allowlist is
only kept if its value is actually numeric (int/float/None). This stops a bug
or a malicious caller from smuggling a non-numeric payload in under a
legitimate feature name -- the sanitizer doesn't just check the label, it
checks the shape.
"""

from __future__ import annotations

from typing import Any

from app.schemas.scoring import RemovedField, SanitizationReport
from app.services.scoring.features import CANONICAL_FEATURE_NAMES

ScoringInput = dict[str, float | None]

# Fields we can name a specific reason for. This is documentation/UX only --
# removal itself is driven entirely by "not in CANONICAL_FEATURE_NAMES" above,
# so leaving a field out of this dict does not let it through; it just falls
# back to the generic "not on the scoring allowlist" reason below.
_KNOWN_BLOCKED_REASONS: dict[str, str] = {
    "full_name": "personally identifying name is never used as a scoring feature",
    "applicant_name": "personally identifying name is never used as a scoring feature",
    "phone": "phone number is PII and never used as a scoring feature",
    "phone_hash": "phone (even hashed) is used only for identity/dedup, never scoring",
    "phone_last4": "phone (even partial) is used only for identity/dedup, never scoring",
    "pan": "PAN is used only for identity verification, never scoring",
    "pan_masked": "PAN is used only for identity verification, never scoring",
    "aadhaar": "Aadhaar is never stored or scored, only HMAC-hashed for dedup",
    "aadhaar_hash": "Aadhaar hash is used only for identity/dedup, never scoring",
    "declared_address": "address/pincode is a protected-attribute proxy and never scored",
    "service_address": "address/pincode is a protected-attribute proxy and never scored",
    "pincode": "pincode is a protected-attribute proxy and never scored",
    "gender": "protected attribute; never used as a scoring feature",
    "age": "protected attribute; never used as a scoring feature",
    "date_of_birth": "protected attribute (age proxy); never used as a scoring feature",
    "religion": "protected attribute; never used as a scoring feature",
    "caste": "protected attribute; never used as a scoring feature",
    "marital_status": "protected attribute; never used as a scoring feature",
    "stated_vocation": (
        "free-text vocation could encode protected-attribute-correlated signals; "
        "never used as a scoring feature"
    ),
    "requested_line_inr": (
        "handled directly by the policy layer's limit-sizing step, never passed "
        "through the scorecard"
    ),
}

_DEFAULT_REASON = (
    "field is not on the scoring allowlist; dropped by default "
    "(CLAUDE.md rule 7: allowlist, not denylist)"
)
_NON_NUMERIC_REASON = (
    "field name is on the allowlist but its value was not numeric; dropped as a "
    "defense-in-depth measure against a non-numeric value being smuggled in "
    "under a legitimate feature name"
)


def sanitize(application_context: dict[str, Any]) -> tuple[ScoringInput, SanitizationReport]:
    """Split `application_context` (everything Phase 6's pipeline has
    assembled about one application -- applicant PII, declared fields, and the
    computed canonical features) into (ScoringInput, SanitizationReport).

    ScoringInput contains ONLY keys in CANONICAL_FEATURE_NAMES with a numeric
    (or None) value. Every other key is recorded as removed, with a reason.
    """
    scoring_input: ScoringInput = {}
    removed: list[RemovedField] = []

    for key, value in application_context.items():
        if key not in CANONICAL_FEATURE_NAMES:
            removed.append(
                RemovedField(field=key, reason=_KNOWN_BLOCKED_REASONS.get(key, _DEFAULT_REASON))
            )
            continue
        if value is not None and not isinstance(value, int | float):
            removed.append(RemovedField(field=key, reason=_NON_NUMERIC_REASON))
            continue
        scoring_input[key] = float(value) if value is not None else None

    # Any canonical feature absent from the input entirely is simply missing
    # (None), not "removed" -- there was nothing to remove. The scorecard
    # already treats a missing factor as 0 points / lower completeness.
    for name in CANONICAL_FEATURE_NAMES:
        scoring_input.setdefault(name, None)

    report = SanitizationReport(
        removed=removed, allowed=[n for n in CANONICAL_FEATURE_NAMES if n in application_context]
    )
    return scoring_input, report

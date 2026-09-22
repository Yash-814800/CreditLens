"""Deterministic Jinja2-templated adverse-action notice (CLAUDE.md rule 3/4):
built entirely from already-computed Decision + RecourseAction values, filled
into a JSON template via Jinja2's `tojson` filter -- every value is JSON-
string-escaped by the templating engine itself, so no submitted text, however
adversarial, can break out of its JSON string context or inject markup (Phase
7's frontend renders this as structured data, never via
`dangerouslySetInnerHTML`).

The reason/appeal wording below is deliberately modelled on US FCRA/ECOA
adverse-action notice content, because CLAUDE.md's Phase 5 spec explicitly
asks for that shape. This is NOT a compliance claim for an India deployment:
RBI's digital-lending guidelines and Fair Practices Code have their own
disclosure requirements (a Key Fact Statement, a named grievance-redressal
officer, specific language mandates) that a real deployment would need
reviewed by counsel and mapped separately -- see the README's "production
path" section (Phase 8).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.schemas.scoring import AdverseActionNotice, Decision, RecourseAction

_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
)

NON_DISCRIMINATION_STATEMENT = (
    "This decision was made without regard to race, color, religion, national origin, "
    "sex, marital status, age, or receipt of public assistance income. The reasons and "
    "recourse actions above reflect only the financial signals described in this notice."
)
BASIS_STATEMENT = (
    "This decision was based solely on the information contained in the documents you "
    "submitted with this application, evaluated against a published, versioned scoring "
    "policy. No external credit bureau data was used."
)
APPEAL_CONTACT_PLACEHOLDER = (
    "[Underwriting team contact / appeal process to be inserted by the deploying "
    "institution -- e.g. a grievance-redressal officer contact per RBI's Fair Practices "
    "Code for an India deployment.]"
)


def _mask_reference(applicant_id: str) -> str:
    if len(applicant_id) <= 8:
        return f"APP-{applicant_id}"
    return f"APP-{applicant_id[:4]}...{applicant_id[-4:]}"


def build_adverse_action_notice(
    *,
    applicant_id: str,
    decision: Decision,
    reason_code_text: dict[str, str],
    recourse_actions: list[RecourseAction],
) -> AdverseActionNotice:
    """Renders a notice for any decision (callers -- Phase 6's pipeline --
    are expected to only surface this to the applicant for REFER/DECLINE,
    since an APPROVE has no adverse reasons to disclose; this function has no
    opinion on that gate, only on how to render the notice once asked)."""
    principal_reasons = [
        {"code": code, "text": reason_code_text[code]} for code in decision.reason_codes
    ]
    what_you_can_do = [action.text for action in recourse_actions]

    template = _env.get_template("adverse_action_notice.v1.json.j2")
    rendered = template.render(
        decision=decision.outcome,
        generated_at=datetime.now(UTC).isoformat(),
        applicant_reference=_mask_reference(applicant_id),
        principal_reasons=principal_reasons,
        what_you_can_do=what_you_can_do,
        basis_statement=BASIS_STATEMENT,
        appeal_contact_placeholder=APPEAL_CONTACT_PLACEHOLDER,
        non_discrimination_statement=NON_DISCRIMINATION_STATEMENT,
    )
    payload = json.loads(rendered)
    return AdverseActionNotice(**payload)

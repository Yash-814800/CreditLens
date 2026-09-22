import json

import pytest

from app.schemas.scoring import Decision, RecourseAction
from app.services.explain.adverse_action import build_adverse_action_notice
from app.services.scoring.decision import load_policy

pytestmark = pytest.mark.unit


def _decline_decision() -> Decision:
    return Decision(
        outcome="DECLINE",
        tier="Declined",
        eligible_line_inr=0,
        reason_codes=["RC03", "RC04"],
        rules_fired=["score_tier: score=30 -> DECLINE"],
        score=30,
        fraud_severity="NONE",
        data_completeness=1.0,
    )


def test_notice_is_valid_json_with_all_required_fields():
    reason_text = load_policy()["reason_code_text"]
    notice = build_adverse_action_notice(
        applicant_id="11111111-2222-3333-4444-555555555555",
        decision=_decline_decision(),
        reason_code_text=reason_text,
        recourse_actions=[],
    )
    assert notice.decision == "DECLINE"
    assert len(notice.principal_reasons) == 2
    assert notice.principal_reasons[0]["code"] == "RC03"
    assert notice.basis_statement
    assert notice.non_discrimination_statement
    assert "credit bureau" in notice.basis_statement.lower()


def test_applicant_reference_is_masked_not_raw_id():
    reason_text = load_policy()["reason_code_text"]
    applicant_id = "11111111-2222-3333-4444-555555555555"
    notice = build_adverse_action_notice(
        applicant_id=applicant_id,
        decision=_decline_decision(),
        reason_code_text=reason_text,
        recourse_actions=[],
    )
    assert applicant_id not in notice.applicant_reference
    assert notice.applicant_reference.startswith("APP-")


def test_recourse_actions_become_what_you_can_do_text():
    reason_text = load_policy()["reason_code_text"]
    action = RecourseAction(
        feature="avg_daily_balance_inr",
        current=2000,
        target=3500,
        points_gain=8,
        resulting_score=53,
        horizon_days=30,
        text="Maintain an average daily balance of at least Rs 3,500: +8 points.",
    )
    notice = build_adverse_action_notice(
        applicant_id="abc",
        decision=_decline_decision(),
        reason_code_text=reason_text,
        recourse_actions=[action],
    )
    assert notice.what_you_can_do == [action.text]


def test_adversarial_text_in_reason_cannot_break_json_structure():
    """A reason-code text dict is normally static config, but this proves the
    Jinja `tojson` filter genuinely escapes arbitrary content rather than
    relying on the specific strings we happen to ship -- defense in depth
    against a future reason-text edit introducing a quote/backslash/newline."""
    adversarial_text = load_policy()["reason_code_text"] | {
        "RC03": 'Contains "quotes", \\ backslashes, and \n newlines.',
    }
    notice = build_adverse_action_notice(
        applicant_id="abc",
        decision=_decline_decision(),
        reason_code_text=adversarial_text,
        recourse_actions=[],
    )
    # If this constructed without raising, json.loads inside the builder
    # already proved the template produced valid JSON despite the content.
    assert "quotes" in notice.principal_reasons[0]["text"]
    # Round-trip through the pydantic model's own JSON dump as a second check.
    json.loads(notice.model_dump_json())

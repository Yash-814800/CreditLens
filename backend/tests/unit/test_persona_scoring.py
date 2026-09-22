"""End-to-end sanity check for Phase 5's decision core against the REAL
demo-pack personas (CLAUDE.md Phase 5's own "DONE WHEN": P01 -> APPROVE,
P02 -> REFER, P03 -> DECLINE with a recourse path), built from the same
sidecar truth.json ground truth Phase 2 generated and the same feature-
builder/bank-parser Phase 3 shipped -- not hand-copied numbers, so this stays
correct if the synthetic corpus is ever regenerated.

Fraud/authenticity is stubbed at a fixed "no findings" value here (0.95):
wiring the REAL async fraud service (Phase 4, needs a DB session for the
pHash cross-applicant lookup) into one request is Phase 6's pipeline's job,
not Phase 5's pure decision core. P01/P02/P03 are not the fraud personas
(that's P04-P07); this test's job is the scorecard/policy/recourse path.
"""

from __future__ import annotations

import json

import pytest

from app.services.extraction.llm_client import build_extraction_from_truth
from app.services.guardrails.sanitizer import sanitize
from app.services.ingestion.bank_parser import analyze_bank_statement, parse_bank_csv
from app.services.scoring.decision import decide
from app.services.scoring.features import build_features
from app.services.scoring.recourse import recommend_recourse
from app.services.scoring.scorecard import compute_score
from tests.paths import DEMO_PACK

pytestmark = pytest.mark.unit

_STUB_AUTHENTICITY_SCORE = 0.95  # stands in for Phase 4's real fraud report


def _load_persona_features(persona_id: str) -> dict[str, float | None]:
    pdir = DEMO_PACK / persona_id

    gig = None
    gig_truth = pdir / "gig_payout.png.truth.json"
    if gig_truth.exists():
        gig = build_extraction_from_truth(
            "GIG_PAYOUT", json.loads(gig_truth.read_text())["visible_fields"]
        )

    util = None
    util_truths = list(pdir.glob("utility_bill.*.truth.json"))
    if util_truths:
        util = build_extraction_from_truth(
            "UTILITY_BILL", json.loads(util_truths[0].read_text())["visible_fields"]
        )

    bank_metrics = None
    bank_days = None
    bank_path = pdir / "bank_statement.csv"
    if bank_path.exists():
        stmt = parse_bank_csv(bank_path.read_text())
        platform_name = gig.platform_name.value if gig else None
        bank_metrics = analyze_bank_statement(stmt, gig_platform_name=platform_name)
        bank_days = (stmt.period_to - stmt.period_from).days + 1

    features = build_features(
        gig_payout=gig, utility_bill=util, bank_metrics=bank_metrics, bank_period_days=bank_days
    )
    features["authenticity_score"] = _STUB_AUTHENTICITY_SCORE
    return features


def _decide_for_persona(persona_id: str, requested_line_inr: float):
    raw_context = _load_persona_features(persona_id)
    scoring_input, sanitization_report = sanitize(raw_context)
    breakdown = compute_score(scoring_input)
    decision = decide(
        score_breakdown=breakdown,
        fraud_severity="NONE",
        identity_check_status="PASS",
        suspected_instruction_text=False,
        requested_line_inr=requested_line_inr,
        verified_monthly_income_inr=scoring_input["verified_monthly_income_inr"],
    )
    return scoring_input, breakdown, decision, sanitization_report


@pytest.mark.skipif(
    not DEMO_PACK.exists(), reason="data/demo_pack not generated (run `make datagen`)"
)
def test_p01_strong_stable_profile_approves():
    # This fixture's raw_context is already just the 11 canonical features
    # (build_features()'s own output) with no PII mixed in, so there is
    # nothing for the sanitizer to strip here -- its PII-removal behaviour
    # is covered directly in test_sanitizer.py and the hypothesis property
    # test instead. This test's job is only the score/decision path.
    _, breakdown, decision, report = _decide_for_persona("P01", requested_line_inr=25000)
    assert decision.outcome == "APPROVE", (
        f"P01 expected APPROVE, got {decision.outcome} (score={breakdown.total}, "
        f"rules_fired={decision.rules_fired})"
    )
    assert report.removed == []


@pytest.mark.skipif(
    not DEMO_PACK.exists(), reason="data/demo_pack not generated (run `make datagen`)"
)
def test_p02_moderate_profile_refers():
    _, breakdown, decision, _ = _decide_for_persona("P02", requested_line_inr=20000)
    assert decision.outcome == "REFER", (
        f"P02 expected REFER, got {decision.outcome} (score={breakdown.total}, "
        f"rules_fired={decision.rules_fired})"
    )


@pytest.mark.skipif(
    not DEMO_PACK.exists(), reason="data/demo_pack not generated (run `make datagen`)"
)
def test_p03_weak_profile_declines_with_a_recourse_path():
    scoring_input, breakdown, decision, _ = _decide_for_persona("P03", requested_line_inr=30000)
    assert decision.outcome == "DECLINE", (
        f"P03 expected DECLINE, got {decision.outcome} (score={breakdown.total}, "
        f"rules_fired={decision.rules_fired})"
    )
    actions = recommend_recourse(scoring_input, breakdown)
    assert actions, "P03 should have at least one actionable recourse path toward REFER"
    for a in actions:
        assert a.points_gain > 0

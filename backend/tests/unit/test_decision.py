import pytest

from app.schemas.scoring import PrecedentSignal, ScoreBreakdown, ScoreFactor
from app.services.scoring.decision import decide, load_policy

pytestmark = pytest.mark.unit


def _breakdown(total: int, data_completeness: float = 1.0, factors=None) -> ScoreBreakdown:
    return ScoreBreakdown(
        version="v1",
        base=15,
        total=total,
        data_completeness=data_completeness,
        factors=factors
        or [
            ScoreFactor(
                name="utility_tenure_months",
                value=20,
                bin_label="ok",
                points=10,
                max_up=25,
                max_down=-10,
                direction="higher_is_better",
                reason_code="RC01",
            )
        ],
    )


def _decide(**overrides):
    kwargs = dict(
        score_breakdown=_breakdown(80),
        fraud_severity="NONE",
        identity_check_status="PASS",
        suspected_instruction_text=False,
        requested_line_inr=20000,
        verified_monthly_income_inr=15000,
    )
    kwargs.update(overrides)
    return decide(**kwargs)


def test_high_score_clean_application_approves():
    d = _decide()
    assert d.outcome == "APPROVE"
    assert d.eligible_line_inr > 0


def test_fraud_high_declines_regardless_of_score():
    d = _decide(score_breakdown=_breakdown(95), fraud_severity="HIGH")
    assert d.outcome == "DECLINE"
    assert "RC07" in d.reason_codes


def test_fraud_medium_caps_at_refer_even_with_high_score():
    d = _decide(score_breakdown=_breakdown(95), fraud_severity="MEDIUM")
    assert d.outcome == "REFER"


def test_identity_mismatch_fail_caps_at_refer():
    d = _decide(score_breakdown=_breakdown(95), identity_check_status="FAIL")
    assert d.outcome == "REFER"
    assert "RC08" in d.reason_codes


def test_suspected_injection_caps_at_refer():
    d = _decide(score_breakdown=_breakdown(95), suspected_instruction_text=True)
    assert d.outcome == "REFER"


def test_incomplete_application_never_declines_for_thin_data_alone():
    # Low score AND low completeness would naturally DECLINE by score tier
    # alone, but CLAUDE.md requires thin files to cap at REFER, never DECLINE.
    d = _decide(score_breakdown=_breakdown(20, data_completeness=0.2))
    assert d.outcome == "REFER"
    assert "RC09" in d.reason_codes


def test_low_confidence_treated_like_missing_data_caps_at_refer():
    d = _decide(
        score_breakdown=_breakdown(20, data_completeness=1.0), min_extraction_confidence=0.1
    )
    assert d.outcome == "REFER"


def test_real_fraud_decline_not_undone_by_incompleteness():
    """A HIGH fraud finding is a real, separate reason to decline -- the
    "never decline for thin data alone" rule must not accidentally soften
    a fraud-caused decline just because the file also happens to be thin."""
    d = _decide(score_breakdown=_breakdown(20, data_completeness=0.1), fraud_severity="HIGH")
    assert d.outcome == "DECLINE"


def test_two_signal_downgrades_approve_when_precedents_disagree():
    signal = PrecedentSignal(peer_default_rate=0.30, ci_lower=0.20, ci_upper=0.40, sample_size=25)
    d = _decide(score_breakdown=_breakdown(90), precedent_signal=signal)
    assert d.outcome == "REFER"
    assert any("two_signal" in r for r in d.rules_fired)


def test_two_signal_upgrades_decline_when_precedents_disagree():
    signal = PrecedentSignal(peer_default_rate=0.02, ci_lower=0.0, ci_upper=0.03, sample_size=25)
    d = _decide(score_breakdown=_breakdown(20), precedent_signal=signal)
    assert d.outcome == "REFER"


def test_two_signal_ignored_below_min_sample_size():
    signal = PrecedentSignal(peer_default_rate=0.30, ci_lower=0.20, ci_upper=0.40, sample_size=2)
    d = _decide(score_breakdown=_breakdown(90), precedent_signal=signal)
    assert d.outcome == "APPROVE"


def test_two_signal_agreement_leaves_outcome_unchanged():
    signal = PrecedentSignal(peer_default_rate=0.05, ci_lower=0.01, ci_upper=0.08, sample_size=25)
    d = _decide(score_breakdown=_breakdown(90), precedent_signal=signal)
    assert d.outcome == "APPROVE"


def test_decline_never_gets_a_credit_line():
    d = _decide(score_breakdown=_breakdown(10))
    assert d.outcome == "DECLINE"
    assert d.eligible_line_inr == 0


def test_refer_gets_starter_tier_fraction_of_full_limit():
    policy = load_policy()
    income = 15000
    d = _decide(
        score_breakdown=_breakdown(50),
        verified_monthly_income_inr=income,
        requested_line_inr=1_000_000,
    )
    full_multiplier = policy["limit_sizing"]["multiplier_by_outcome"]["REFER"]
    starter_fraction = policy["limit_sizing"]["starter_tier_fraction_for_refer"]
    absolute_cap = policy["limit_sizing"]["absolute_cap_inr"]
    expected = min(1_000_000, full_multiplier * income, absolute_cap) * starter_fraction
    assert d.eligible_line_inr == pytest.approx(expected, rel=1e-6)


def test_rc10_added_when_requested_exceeds_verified_capacity():
    d = _decide(
        score_breakdown=_breakdown(90),
        requested_line_inr=10_000_000,
        verified_monthly_income_inr=5000,
    )
    assert "RC10" in d.reason_codes
    assert d.eligible_line_inr < 10_000_000


def test_no_income_signal_gives_small_fixed_floor_for_refer():
    d = _decide(score_breakdown=_breakdown(50), verified_monthly_income_inr=None)
    policy = load_policy()
    assert d.outcome == "REFER"
    assert d.eligible_line_inr == policy["limit_sizing"]["no_income_signal_floor_inr"]


def test_reason_codes_capped_at_policy_max():
    policy = load_policy()
    many_bad_factors = [
        ScoreFactor(
            name=f"factor_{i}",
            value=0,
            bin_label="bad",
            points=-10,
            max_up=10,
            max_down=-10,
            direction="higher_is_better",
            reason_code=f"RC0{i}",
        )
        for i in range(1, 8)
    ]
    d = _decide(
        score_breakdown=_breakdown(10, factors=many_bad_factors),
        fraud_severity="HIGH",
        identity_check_status="FAIL",
        suspected_instruction_text=True,
    )
    assert len(d.reason_codes) <= policy["principal_reasons_max"]


def test_rules_fired_trace_is_non_empty_and_ordered():
    d = _decide()
    assert len(d.rules_fired) >= 5
    assert d.rules_fired[0].startswith("score_tier")

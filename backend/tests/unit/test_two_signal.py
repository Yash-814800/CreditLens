"""Unit tests for Phase 11: Two-Signal Decision (Scorecard + Precedents) logic,
Wilson score interval edge cases, Decision schema outputs, and seed idempotency.
"""

from __future__ import annotations

from app.schemas.scoring import PrecedentSignal, ScoreBreakdown, ScoreFactor
from app.services.scoring.decision import decide
from app.services.vectors.precedents import wilson_score_interval


def _dummy_breakdown(score: int) -> ScoreBreakdown:
    return ScoreBreakdown(
        version="v1",
        base=15,
        total=score,
        factors=[
            ScoreFactor(
                name="utility_tenure_months",
                value=12.0,
                bin_label="12+ months",
                points=score - 15,
                max_up=25,
                max_down=-10,
                direction="higher_is_better",
                reason_code="RC01",
            )
        ],
        data_completeness=1.0,
    )


# 1. Wilson score interval edge cases
def test_wilson_score_interval_n_zero_is_maximally_uninformative():
    lower, upper = wilson_score_interval(0, 0)
    assert lower == 0.0
    assert upper == 1.0


def test_wilson_score_interval_zero_successes_upper_bound_decreases_with_n():
    # Demonstrates why k=25 with legacy threshold 0.05 could never fire for upgrades:
    _, upper_25 = wilson_score_interval(0, 25)
    _, upper_35 = wilson_score_interval(0, 35)
    _, upper_50 = wilson_score_interval(0, 50)

    assert round(upper_25, 3) == 0.133  # > 0.05, impossible to upgrade under legacy threshold
    assert round(upper_35, 3) == 0.099  # < 0.15 threshold!
    assert round(upper_50, 3) == 0.071  # < 0.15 threshold!
    assert upper_50 < upper_35 < upper_25


def test_wilson_score_interval_all_successes():
    lower, upper = wilson_score_interval(35, 35)
    assert upper == 1.0
    assert lower > 0.85


def test_wilson_score_interval_monotonicity():
    for x in range(35):
        lo1, hi1 = wilson_score_interval(x, 35)
        lo2, hi2 = wilson_score_interval(x + 1, 35)
        assert lo1 <= lo2
        assert hi1 <= hi2


# 2. Two-signal policy logic & Decision schema fields
def test_two_signal_downgrade_fires_and_populates_decision_fields():
    # Scorecard alone: score 85 -> APPROVE
    # Precedent signal: peer default rate 0.35, ci_lower 0.22 > 0.18 threshold
    breakdown = _dummy_breakdown(85)
    signal = PrecedentSignal(peer_default_rate=0.35, ci_lower=0.22, ci_upper=0.52, sample_size=35)

    decision = decide(
        score_breakdown=breakdown,
        fraud_severity="NONE",
        identity_check_status="PASS",
        suspected_instruction_text=False,
        requested_line_inr=20000.0,
        verified_monthly_income_inr=15000.0,
        precedent_signal=signal,
    )

    assert decision.scorecard_outcome == "APPROVE"
    assert decision.precedent_outcome == "REFER"
    assert decision.outcome == "REFER"
    assert decision.final_outcome == "REFER"
    assert decision.precedent_peer_count == 35
    assert decision.precedent_default_rate == 0.35
    assert decision.precedent_wilson_ci == (0.22, 0.52)
    assert any("TWO_SIGNAL_DOWNGRADE" in r for r in decision.rules_fired)


def test_two_signal_upgrade_fires_and_populates_decision_fields():
    # Scorecard alone: score 30 -> DECLINE
    # Precedent signal: peer default rate 0.028, ci_upper 0.14 < 0.15 threshold
    breakdown = _dummy_breakdown(30)
    signal = PrecedentSignal(peer_default_rate=0.028, ci_lower=0.005, ci_upper=0.14, sample_size=35)

    decision = decide(
        score_breakdown=breakdown,
        fraud_severity="NONE",
        identity_check_status="PASS",
        suspected_instruction_text=False,
        requested_line_inr=15000.0,
        verified_monthly_income_inr=12000.0,
        precedent_signal=signal,
    )

    assert decision.scorecard_outcome == "DECLINE"
    assert decision.precedent_outcome == "REFER"
    assert decision.outcome == "REFER"
    assert decision.final_outcome == "REFER"
    assert decision.precedent_peer_count == 35
    assert decision.precedent_default_rate == 0.028
    assert decision.precedent_wilson_ci == (0.005, 0.14)
    assert any("TWO_SIGNAL_UPGRADE" in r for r in decision.rules_fired)


def test_two_signal_agreement_leaves_precedent_outcome_none():
    # Normal borrower: score 80 -> APPROVE
    # Precedent signal: peer default rate 0.10, ci_lower 0.04, ci_upper 0.22
    breakdown = _dummy_breakdown(80)
    signal = PrecedentSignal(peer_default_rate=0.10, ci_lower=0.04, ci_upper=0.22, sample_size=35)

    decision = decide(
        score_breakdown=breakdown,
        fraud_severity="NONE",
        identity_check_status="PASS",
        suspected_instruction_text=False,
        requested_line_inr=20000.0,
        verified_monthly_income_inr=15000.0,
        precedent_signal=signal,
    )

    assert decision.scorecard_outcome == "APPROVE"
    assert decision.precedent_outcome is None
    assert decision.outcome == "APPROVE"
    assert decision.final_outcome == "APPROVE"
    assert any("agrees with the scorecard outcome" in r for r in decision.rules_fired)


def test_two_signal_sample_size_below_threshold_is_skipped():
    breakdown = _dummy_breakdown(85)
    signal = PrecedentSignal(peer_default_rate=0.50, ci_lower=0.30, ci_upper=0.70, sample_size=10)

    decision = decide(
        score_breakdown=breakdown,
        fraud_severity="NONE",
        identity_check_status="PASS",
        suspected_instruction_text=False,
        requested_line_inr=20000.0,
        verified_monthly_income_inr=15000.0,
        precedent_signal=signal,
    )

    assert decision.scorecard_outcome == "APPROVE"
    assert decision.outcome == "APPROVE"
    assert any("min_sample_size" in r for r in decision.rules_fired)

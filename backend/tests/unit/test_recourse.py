import pytest

from app.services.scoring.decision import load_policy
from app.services.scoring.recourse import ACTIONABLE_FEATURES, recommend_recourse
from app.services.scoring.scorecard import compute_score, load_scorecard

pytestmark = pytest.mark.unit


def test_already_approved_gets_no_recourse():
    cfg = load_scorecard()
    strong = {
        "utility_tenure_months": 24,
        "weekly_inflow_cv": 0.10,
        "utility_on_time_ratio": 1.0,
        "avg_daily_balance_inr": 20000,
        "gig_active_days_per_week": 7,
        "income_reconciliation_ratio": 1.5,
        "authenticity_score": 1.0,
    }
    breakdown = compute_score(strong, cfg)
    assert recommend_recourse(strong, breakdown) == []


def test_refer_gets_actionable_recourse_reaching_approve():
    cfg = load_scorecard()
    policy = load_policy()
    borderline = {
        "utility_tenure_months": 24,  # already maxed, no candidate from this one
        "weekly_inflow_cv": 0.50,  # non-actionable, fixed as-is
        "utility_on_time_ratio": 0.70,  # room to improve
        "avg_daily_balance_inr": 3400,  # room to improve
        "gig_active_days_per_week": 4.5,  # room to improve
        "income_reconciliation_ratio": 0.85,  # room to improve
        "authenticity_score": 0.95,  # non-actionable, fixed as-is
    }
    breakdown = compute_score(borderline, cfg)
    assert (
        policy["score_tiers"]["refer_min"] <= breakdown.total < policy["score_tiers"]["approve_min"]
    )

    actions = recommend_recourse(borderline, breakdown)
    assert actions, "expected at least one recourse action for a borderline profile"

    # Verify the claim: applying every recommended change actually reaches APPROVE.
    counterfactual = dict(borderline)
    for a in actions:
        counterfactual[a.feature] = a.target
    reverified = compute_score(counterfactual, cfg)
    assert reverified.total >= policy["score_tiers"]["approve_min"]


def test_recourse_never_suggests_non_actionable_features():
    cfg = load_scorecard()
    weak_everywhere = {
        "utility_tenure_months": 1,
        "weekly_inflow_cv": 0.95,
        "utility_on_time_ratio": 0.2,
        "avg_daily_balance_inr": 500,
        "gig_active_days_per_week": 1,
        "income_reconciliation_ratio": 0.3,
        "authenticity_score": 0.2,  # deliberately terrible -- must NEVER be suggested
    }
    breakdown = compute_score(weak_everywhere, cfg)
    actions = recommend_recourse(weak_everywhere, breakdown)
    for a in actions:
        assert a.feature in ACTIONABLE_FEATURES
        assert a.feature != "authenticity_score"
        assert a.feature != "weekly_inflow_cv"


def test_recourse_skipped_for_missing_actionable_feature():
    cfg = load_scorecard()
    missing_balance = {
        "utility_tenure_months": 6,
        "weekly_inflow_cv": 0.5,
        "utility_on_time_ratio": 0.6,
        "avg_daily_balance_inr": None,  # missing document
        "gig_active_days_per_week": 3.5,
        "income_reconciliation_ratio": 0.7,
        "authenticity_score": 0.9,
    }
    breakdown = compute_score(missing_balance, cfg)
    actions = recommend_recourse(missing_balance, breakdown)
    assert all(a.feature != "avg_daily_balance_inr" for a in actions)


def test_every_recourse_action_has_a_horizon_or_is_immediate():
    cfg = load_scorecard()
    borderline = {
        "utility_tenure_months": 24,
        "weekly_inflow_cv": 0.50,
        "utility_on_time_ratio": 0.70,
        "avg_daily_balance_inr": 3400,
        "gig_active_days_per_week": 4.5,
        "income_reconciliation_ratio": 0.85,
        "authenticity_score": 0.95,
    }
    breakdown = compute_score(borderline, cfg)
    actions = recommend_recourse(borderline, breakdown)
    assert actions, "expected at least one recourse action for this fixture"
    for a in actions:
        assert a.horizon_days is None or a.horizon_days > 0
        assert a.points_gain > 0
        assert a.text  # human-readable, non-empty


def test_no_recourse_returned_when_gap_is_unreachable():
    """Every ACTIONABLE feature is already at its own best bin (so
    `recommend_recourse` has zero candidates to offer from them), while the
    two NON-actionable factors (weekly_inflow_cv, authenticity_score) are
    both pinned at their worst bin, keeping the total below REFER. There is
    no combination of actionable changes that can close this gap -- the
    engine must say so honestly (empty list) rather than fabricate a path."""
    cfg = load_scorecard()
    maxed_actionable_but_bad_non_actionable = {
        "utility_tenure_months": 24,
        "utility_on_time_ratio": 1.0,
        "avg_daily_balance_inr": 50000,
        "gig_active_days_per_week": 7,
        "income_reconciliation_ratio": 1.5,
        "weekly_inflow_cv": 5.0,  # non-actionable, worst bin
        "authenticity_score": 0.0,  # non-actionable, worst bin
    }
    breakdown = compute_score(maxed_actionable_but_bad_non_actionable, cfg)
    assert breakdown.total < load_policy()["score_tiers"]["refer_min"]
    actions = recommend_recourse(maxed_actionable_but_bad_non_actionable, breakdown)
    assert actions == []

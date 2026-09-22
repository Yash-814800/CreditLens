import pytest

from app.services.scoring.scorecard import compute_score, load_scorecard

pytestmark = pytest.mark.unit


def _cfg():
    return load_scorecard()


def _empty_input():
    return dict.fromkeys(load_scorecard()["factors"].keys())


def test_perfect_profile_scores_100():
    cfg = _cfg()
    perfect = {
        "utility_tenure_months": 24,
        "weekly_inflow_cv": 0.10,
        "utility_on_time_ratio": 1.0,
        "avg_daily_balance_inr": 20000,
        "gig_active_days_per_week": 7,
        "income_reconciliation_ratio": 1.5,
        "authenticity_score": 1.0,
    }
    breakdown = compute_score(perfect, cfg)
    assert breakdown.total == 100
    assert breakdown.data_completeness == 1.0


def test_worst_profile_clamps_to_zero_not_negative():
    cfg = _cfg()
    worst = {
        "utility_tenure_months": 0,
        "weekly_inflow_cv": 5.0,
        "utility_on_time_ratio": 0.0,
        "avg_daily_balance_inr": 0,
        "gig_active_days_per_week": 0,
        "income_reconciliation_ratio": 0.0,
        "authenticity_score": 0.0,
    }
    breakdown = compute_score(worst, cfg)
    assert breakdown.total == 0


def test_all_missing_gives_base_score_and_zero_completeness():
    breakdown = compute_score(_empty_input())
    cfg = _cfg()
    assert breakdown.total == cfg["base"]
    assert breakdown.data_completeness == 0.0
    assert all(f.points == 0 for f in breakdown.factors)


def test_missing_factor_is_neutral_not_penalized():
    cfg = _cfg()
    baseline = _empty_input()
    baseline["utility_tenure_months"] = 24  # best bin
    with_missing_balance = dict(baseline)
    breakdown = compute_score(with_missing_balance, cfg)

    balance_factor = next(f for f in breakdown.factors if f.name == "avg_daily_balance_inr")
    assert balance_factor.points == 0
    assert balance_factor.value is None


def test_partial_completeness_computed_correctly():
    cfg = _cfg()
    partial = _empty_input()
    partial["utility_tenure_months"] = 24
    partial["avg_daily_balance_inr"] = 20000
    breakdown = compute_score(partial, cfg)
    # 2 of 7 factors present
    assert breakdown.data_completeness == pytest.approx(2 / 7, abs=1e-4)


def test_score_never_exceeds_bounds_across_extreme_values():
    cfg = _cfg()
    extreme_high = {
        "utility_tenure_months": 1000,
        "weekly_inflow_cv": -5,
        "utility_on_time_ratio": 100,
        "avg_daily_balance_inr": 1e9,
        "gig_active_days_per_week": 1000,
        "income_reconciliation_ratio": 100,
        "authenticity_score": 100,
    }
    breakdown = compute_score(extreme_high, cfg)
    assert 0 <= breakdown.total <= 100


def test_malformed_config_fails_fast(tmp_path):
    bad_yaml = tmp_path / "bad_scorecard.yaml"
    bad_yaml.write_text("not: [valid, scorecard, shape}")
    import yaml

    with pytest.raises(yaml.YAMLError):
        load_scorecard(bad_yaml)


def test_scorecard_bins_are_internally_monotonic_by_construction():
    """A structural snapshot check on the shipped YAML itself (independent of
    the hypothesis-based property test in test_scoring_properties.py): every
    factor's bin points must move consistently with `direction` as
    upper_bound increases."""
    cfg = _cfg()
    for name, factor in cfg["factors"].items():
        points_sequence = [b["points"] for b in factor["bins"]]
        if factor["direction"] == "higher_is_better":
            assert points_sequence == sorted(points_sequence), name
        else:
            assert points_sequence == sorted(points_sequence, reverse=True), name
        assert max(points_sequence) == factor["max_up"], name
        assert min(points_sequence) == factor["max_down"], name

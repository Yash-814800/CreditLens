"""Historical borrowers (feature-level only, no documents/images).

Generation model, so later scoring/validation is not circular: every row
carries a latent creditworthiness `z` and an UNOBSERVED shock `u` (both
dropped from the final output -- they never leave this function). Every
canonical feature is an independent noisy function of `z` (plus a cohort
baseline and its own noise), and `defaulted` is a separate noisy function of
`z` AND `u`. Because `u` never touches the features, a scorecard built purely
from the features can be informative about default risk (through the shared
`z`) without the features *determining* the outcome -- which is what would
make later validation of the scorecard against this history meaningless.

`group_label` is drawn independently of `z`/`u`/cohort and is used ONLY by the
Phase 8 fairness audit -- never by the scorecard itself.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from synthgen.rng import rng_for

N_ROWS = 2000
FEATURE_COLS = [
    "utility_tenure_months",
    "utility_on_time_ratio",
    "weekly_inflow_cv",
    "avg_daily_balance_inr",
    "low_balance_day_ratio",
    "gig_active_days_per_week",
    "gig_weekly_earnings_cv",
    "gig_tenure_weeks",
    "income_reconciliation_ratio",
    "verified_monthly_income_inr",
]
COHORTS = [
    "urban_ride",
    "urban_food",
    "semiurban_mixed",
    "rural_mixed",
    "blind_spot",
    "resilient",
]
COHORT_P = [0.301, 0.258, 0.215, 0.086, 0.07, 0.07]
COHORT_BASE = {
    # tenure_months, balance_inr, income_inr, gig_tenure_weeks
    "urban_ride": (16, 3200, 15000, 45),
    "urban_food": (14, 2800, 13000, 40),
    "semiurban_mixed": (10, 2200, 10500, 30),
    "rural_mixed": (7, 1600, 8500, 22),
    "blind_spot": (18, 4200, 16000, 6),
    "resilient": (2.5, 1600, 11000, 70),
}


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _calibrate_intercept(z: np.ndarray, u: np.ndarray, target_rate: float, b: float = 1.1, c: float = 0.6) -> float:
    """Bisection search for the intercept that makes mean(sigmoid(a - b*z - c*u)) == target_rate."""
    lo, hi = -6.0, 6.0
    for _ in range(60):
        mid = (lo + hi) / 2
        rate = float(np.mean(_sigmoid(mid - b * z - c * u)))
        if rate > target_rate:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def generate_history(n_rows: int = N_ROWS, target_default_rate: float = 0.12) -> pd.DataFrame:
    rng = rng_for("history", "main")

    cohort = rng.choice(COHORTS, size=n_rows, p=COHORT_P)
    z = rng.normal(0, 1, n_rows)
    u = rng.normal(0, 1, n_rows)  # unobserved shock: never used below except for `defaulted`
    group_label = rng.choice(["A", "B"], size=n_rows, p=[0.5, 0.5])  # independent of z, u, cohort
    split = rng.choice(["train", "val", "test"], size=n_rows, p=[0.6, 0.2, 0.2])

    base = np.array([COHORT_BASE[c] for c in cohort])
    tenure_base, balance_base, income_base, gig_tenure_base = (base[:, i] for i in range(4))

    def noisy(mean, sd):
        return rng.normal(0, sd, n_rows) + mean

    utility_tenure_months = np.clip(tenure_base + z * 6 + noisy(0, 3.5), 0, 60)
    utility_on_time_ratio = np.clip(0.72 + 0.14 * z + noisy(0, 0.07), 0.0, 1.0)
    weekly_inflow_cv = np.clip(0.45 - 0.13 * z + noisy(0, 0.09), 0.03, 1.5)
    avg_daily_balance_inr = np.clip(balance_base * np.exp(0.35 * z + noisy(0, 0.25)), 100, None)
    low_balance_day_ratio = np.clip(0.32 - 0.09 * z - 0.15 * (weekly_inflow_cv - 0.45) + noisy(0, 0.06), 0.0, 1.0)
    gig_active_days_per_week = np.clip(4.4 + 0.65 * z + noisy(0, 0.6), 0.0, 7.0)
    gig_weekly_earnings_cv = np.clip(0.38 - 0.09 * z + noisy(0, 0.08), 0.03, 1.2)
    gig_tenure_weeks = np.clip(gig_tenure_base + z * 7 + noisy(0, 6), 0, 260)
    income_reconciliation_ratio = np.clip(0.88 + 0.13 * z + noisy(0, 0.12), 0.0, 1.5)
    verified_monthly_income_inr = np.clip(income_base * np.exp(0.28 * z + noisy(0, 0.22)), 1000, None)

    is_blind = cohort == "blind_spot"
    is_resilient = cohort == "resilient"
    is_std = ~(is_blind | is_resilient)

    # Blind-spot cohort: strong scorecard-weighted signals (utility tenure, on-time,
    # low inflow CV), but unweighted signals reveal brittle cashflow (short gig tenure,
    # high gig earnings CV, frequent low-balance days).
    n_blind = int(is_blind.sum())
    if n_blind > 0:
        utility_tenure_months[is_blind] = np.clip(18.0 + z[is_blind] * 3 + rng.normal(0, 2.0, n_blind), 12, 40)
        utility_on_time_ratio[is_blind] = np.clip(0.92 + 0.04 * z[is_blind] + rng.normal(0, 0.03, n_blind), 0.84, 1.0)
        weekly_inflow_cv[is_blind] = np.clip(0.27 - 0.05 * z[is_blind] + rng.normal(0, 0.04, n_blind), 0.10, 0.40)
        avg_daily_balance_inr[is_blind] = np.clip(
            4200 * np.exp(0.2 * z[is_blind] + rng.normal(0, 0.15, n_blind)), 2500, 12000
        )
        gig_active_days_per_week[is_blind] = np.clip(5.2 + 0.3 * z[is_blind] + rng.normal(0, 0.4, n_blind), 4.0, 7.0)
        income_reconciliation_ratio[is_blind] = np.clip(
            0.98 + 0.05 * z[is_blind] + rng.normal(0, 0.05, n_blind), 0.85, 1.2
        )
        gig_tenure_weeks[is_blind] = np.clip(6.0 + rng.normal(0, 1.5, n_blind), 2.0, 10.0)
        gig_weekly_earnings_cv[is_blind] = np.clip(0.68 + rng.normal(0, 0.08, n_blind), 0.50, 0.95)
        low_balance_day_ratio[is_blind] = np.clip(0.62 + rng.normal(0, 0.08, n_blind), 0.45, 0.85)

    # Resilient cohort: thin/young utility tenure and modest bank balance (scorecard rates
    # them DECLINE or low tier), but unweighted signals show career stability and consistent
    # positive cashflow (long steady gig tenure, low earnings CV, near-zero low balance days).
    n_resilient = int(is_resilient.sum())
    if n_resilient > 0:
        utility_tenure_months[is_resilient] = np.clip(2.5 + rng.normal(0, 1.0, n_resilient), 0.0, 5.0)
        utility_on_time_ratio[is_resilient] = np.clip(0.72 + rng.normal(0, 0.05, n_resilient), 0.55, 0.80)
        weekly_inflow_cv[is_resilient] = np.clip(0.55 + rng.normal(0, 0.07, n_resilient), 0.40, 0.75)
        avg_daily_balance_inr[is_resilient] = np.clip(
            1600 * np.exp(0.2 * z[is_resilient] + rng.normal(0, 0.15, n_resilient)), 800, 2800
        )
        gig_active_days_per_week[is_resilient] = np.clip(4.2 + rng.normal(0, 0.5, n_resilient), 3.0, 5.5)
        income_reconciliation_ratio[is_resilient] = np.clip(0.85 + rng.normal(0, 0.06, n_resilient), 0.70, 1.0)
        gig_tenure_weeks[is_resilient] = np.clip(
            70.0 + z[is_resilient] * 8 + rng.normal(0, 7.0, n_resilient), 45.0, 130.0
        )
        gig_weekly_earnings_cv[is_resilient] = np.clip(
            0.14 - 0.03 * z[is_resilient] + rng.normal(0, 0.03, n_resilient), 0.05, 0.24
        )
        low_balance_day_ratio[is_resilient] = np.clip(0.02 + rng.normal(0, 0.015, n_resilient), 0.0, 0.06)

    # Outcomes: generated via latent creditworthiness z and unobserved shock u.
    # Blind-spot borrowers default at 30-40% (~35%) due to cashflow fragility.
    # Resilient borrowers default at 3-5% (~4%) due to steady operational cashflow.
    # Standard cohorts' intercept is calibrated so the total population default rate hits target_default_rate (~12%).
    target_blind = 0.35
    target_resilient = 0.04
    n_std = int(is_std.sum())
    target_std = (target_default_rate * n_rows - target_blind * n_blind - target_resilient * n_resilient) / max(
        1, n_std
    )

    intercept_blind = _calibrate_intercept(z[is_blind], u[is_blind], target_blind, b=0.5, c=0.8)
    intercept_resilient = _calibrate_intercept(z[is_resilient], u[is_resilient], target_resilient, b=0.8, c=0.6)
    intercept_std = _calibrate_intercept(z[is_std], u[is_std], target_std, b=1.1, c=0.6)

    default_prob = np.zeros(n_rows)
    if n_blind > 0:
        default_prob[is_blind] = _sigmoid(intercept_blind - 0.5 * z[is_blind] - 0.8 * u[is_blind])
    if n_resilient > 0:
        default_prob[is_resilient] = _sigmoid(intercept_resilient - 0.8 * z[is_resilient] - 0.6 * u[is_resilient])
    if n_std > 0:
        default_prob[is_std] = _sigmoid(intercept_std - 1.1 * z[is_std] - 0.6 * u[is_std])

    defaulted = rng.random(n_rows) < default_prob

    df = pd.DataFrame(
        {
            "row_id": [f"HIST-{i:05d}" for i in range(n_rows)],
            "cohort": cohort,
            "split": split,
            "group_label": group_label,
            "utility_tenure_months": utility_tenure_months.round(1),
            "utility_on_time_ratio": utility_on_time_ratio.round(3),
            "weekly_inflow_cv": weekly_inflow_cv.round(3),
            "avg_daily_balance_inr": avg_daily_balance_inr.round(2),
            "low_balance_day_ratio": low_balance_day_ratio.round(3),
            "gig_active_days_per_week": gig_active_days_per_week.round(2),
            "gig_weekly_earnings_cv": gig_weekly_earnings_cv.round(3),
            "gig_tenure_weeks": gig_tenure_weeks.round(1),
            "income_reconciliation_ratio": income_reconciliation_ratio.round(3),
            "verified_monthly_income_inr": verified_monthly_income_inr.round(2),
            "defaulted": defaulted,
        }
    )

    # Thin files: some standard rows are missing a whole document family's features, matching
    # the real world (an applicant with no utility bill on file has NO utility_* signal
    # at all, not merely a noisy one). Missingness is independent of z/u so it doesn't
    # itself encode risk.
    miss_rng = rng_for("history", "missingness")
    utility_cols = ["utility_tenure_months", "utility_on_time_ratio"]
    gig_cols = ["gig_active_days_per_week", "gig_weekly_earnings_cv", "gig_tenure_weeks"]
    no_utility = (miss_rng.random(n_rows) < 0.08) & is_std
    no_gig = (miss_rng.random(n_rows) < 0.08) & is_std
    df.loc[no_utility, utility_cols] = np.nan
    df.loc[no_gig, gig_cols] = np.nan

    return df

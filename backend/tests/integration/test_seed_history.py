"""Integration test verifying seed_history replaces rather than appends synthetic rows."""

from __future__ import annotations

import pandas as pd
import pytest
from scripts.seed_history import HISTORY_PATH, seed
from sqlalchemy import func, select

from app.db.models import HistoricalBorrower

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_seed_history_replaces_rather_than_appends(db_session):
    # Create a small dummy synthetic dataframe
    df = pd.DataFrame(
        [
            {
                "row_id": "TEST-00001",
                "cohort": "blind_spot",
                "defaulted": False,
                "utility_tenure_months": 18.0,
                "utility_on_time_ratio": 0.95,
                "weekly_inflow_cv": 0.28,
                "avg_daily_balance_inr": 4500.0,
                "low_balance_day_ratio": 0.60,
                "gig_active_days_per_week": 5.5,
                "gig_weekly_earnings_cv": 0.65,
                "gig_tenure_weeks": 5.0,
                "income_reconciliation_ratio": 1.0,
                "verified_monthly_income_inr": 18000.0,
            },
            {
                "row_id": "TEST-00002",
                "cohort": "resilient",
                "defaulted": False,
                "utility_tenure_months": 2.0,
                "utility_on_time_ratio": 0.70,
                "weekly_inflow_cv": 0.55,
                "avg_daily_balance_inr": 1500.0,
                "low_balance_day_ratio": 0.02,
                "gig_active_days_per_week": 4.2,
                "gig_weekly_earnings_cv": 0.12,
                "gig_tenure_weeks": 75.0,
                "income_reconciliation_ratio": 0.85,
                "verified_monthly_income_inr": 12000.0,
            },
        ]
    )

    try:
        # First seed: inserts 2 rows
        inserted_1 = await seed(df, session=db_session)
        assert inserted_1 == 2

        count_1 = await db_session.scalar(
            select(func.count())
            .select_from(HistoricalBorrower)
            .where(HistoricalBorrower.synthetic.is_(True))
        )
        assert count_1 == 2

        # Second seed with same dataframe: replaces, does not append (count remains 2, not 4)
        inserted_2 = await seed(df, session=db_session)
        assert inserted_2 == 2

        count_2 = await db_session.scalar(
            select(func.count())
            .select_from(HistoricalBorrower)
            .where(HistoricalBorrower.synthetic.is_(True))
        )
        assert count_2 == 2
    finally:
        if HISTORY_PATH.exists():
            orig_df = pd.read_parquet(HISTORY_PATH)
            await seed(orig_df, session=db_session)

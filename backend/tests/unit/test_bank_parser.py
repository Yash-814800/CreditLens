import pytest

from app.services.ingestion.bank_parser import (
    account_last4,
    analyze_bank_statement,
    compute_avg_daily_balance,
    compute_weekly_inflow_cv,
    find_platform_credits,
    parse_bank_csv,
    verify_running_balance,
)
from app.services.ingestion.validation import UploadValidationError
from tests.paths import DEMO_PACK

pytestmark = pytest.mark.unit


def _hand_built_csv() -> str:
    return (
        "account_holder,Test User\n"
        "account_number_masked,XXXXXXXX4321\n"
        "bank,Demo Sahakari Bank\n"
        "period_from,2026-01-01\n"
        "period_to,2026-01-14\n"
        "\n"
        "date,narration,ref,debit,credit,balance\n"
        "2026-01-01,ATM CASH WDL,1,100.00,,900.00\n"
        "2026-01-03,UPI/ZIPRIDEPARTNER PAYOUT/1,2,,1000.00,1900.00\n"
        "2026-01-05,GROCERY,3,200.00,,1700.00\n"
        "2026-01-08,UPI/ZIPRIDEPARTNER PAYOUT/2,4,,1200.00,2900.00\n"
        "2026-01-10,RENT,5,300.00,,2600.00\n"
        "2026-01-12,UPI/ZIPRIDEPARTNER PAYOUT/3,6,,900.00,3500.00\n"
    )


class TestParsing:
    def test_hand_built_csv_parses(self):
        stmt = parse_bank_csv(_hand_built_csv())
        assert stmt.account_holder == "Test User"
        assert len(stmt.transactions) == 6
        assert stmt.transactions[0].debit == 100.00
        assert stmt.transactions[1].credit == 1000.00

    def test_missing_metadata_field_rejected(self):
        bad = _hand_built_csv().replace("bank,Demo Sahakari Bank\n", "")
        with pytest.raises(UploadValidationError):
            parse_bank_csv(bad)

    def test_bad_date_rejected(self):
        bad = _hand_built_csv().replace("2026-01-01,ATM", "not-a-date,ATM")
        with pytest.raises(UploadValidationError):
            parse_bank_csv(bad)


class TestAccountLast4:
    def test_extracts_last_four_digits(self):
        assert account_last4("XXXXXXXX4321") == "4321"

    def test_short_masked_number(self):
        assert account_last4("12") == "12"


class TestRunningBalance:
    def test_clean_chain_has_no_issues(self):
        stmt = parse_bank_csv(_hand_built_csv())
        assert verify_running_balance(stmt) == []

    def test_tampered_balance_detected(self):
        tampered = _hand_built_csv().replace(",1700.00\n", ",9999.00\n")
        stmt = parse_bank_csv(tampered)
        issues = verify_running_balance(stmt)
        # The tamper produces exactly 2 issues, not a cascade through the rest
        # of the statement: row N's own mismatch (its real balance vs. what
        # row N-1's real balance implied), then row N+1's mismatch (its real,
        # untouched balance vs. what row N's now-wrong balance implied) --
        # after that, row N+1's own real stated balance re-anchors the replay
        # and the (untouched) remainder of the file is internally consistent
        # with itself again.
        assert len(issues) == 2
        assert issues[0].actual_balance == 9999.00
        assert issues[1].actual_balance == 2900.00


class TestAvgDailyBalance:
    def test_hand_computed_forward_fill(self):
        # 14-day period; balances forward-filled from the last known EOD value.
        stmt = parse_bank_csv(_hand_built_csv())
        avg, low_ratio = compute_avg_daily_balance(stmt)
        # Manually replay the day-by-day forward fill to get an independent expectation.
        expected_by_day = {
            1: 900.00,
            2: 900.00,
            3: 1900.00,
            4: 1900.00,
            5: 1700.00,
            6: 1700.00,
            7: 1700.00,
            8: 2900.00,
            9: 2900.00,
            10: 2600.00,
            11: 2600.00,
            12: 3500.00,
            13: 3500.00,
            14: 3500.00,
        }
        expected_avg = round(sum(expected_by_day.values()) / len(expected_by_day), 2)
        assert avg == expected_avg
        assert low_ratio == 0.0  # every day is well above 500


class TestWeeklyInflowCv:
    def test_needs_at_least_two_complete_weeks(self):
        stmt = parse_bank_csv(_hand_built_csv())
        # 14-day Jan 1-14 2026 period: Jan 1 is a Thursday, so there is no
        # complete Mon-Sun week fully inside the period -> None.
        assert compute_weekly_inflow_cv(stmt) is None

    def test_two_complete_weeks_hand_computed(self):
        csv_text = (
            "account_holder,Test User\n"
            "account_number_masked,XXXXXXXX0001\n"
            "bank,Demo Sahakari Bank\n"
            "period_from,2026-01-05\n"
            "period_to,2026-01-18\n"
            "\n"
            "date,narration,ref,debit,credit,balance\n"
            # Week 1: Mon 2026-01-05 .. Sun 2026-01-11, total credit 1000
            "2026-01-05,CREDIT A,1,,1000.00,1000.00\n"
            # Week 2: Mon 2026-01-12 .. Sun 2026-01-18, total credit 500 + 500 = 1000
            "2026-01-12,CREDIT B,2,,500.00,1500.00\n"
            "2026-01-13,CREDIT C,3,,500.00,2000.00\n"
        )
        stmt = parse_bank_csv(csv_text)
        cv = compute_weekly_inflow_cv(stmt)
        # Both weeks total 1000 -> stdev 0 -> cv 0.0
        assert cv == 0.0


class TestPlatformCredits:
    def test_matches_spaceless_narration(self):
        stmt = parse_bank_csv(_hand_built_csv())
        total, count = find_platform_credits(stmt, "ZipRide Partner")
        assert count == 3
        assert total == 1000.00 + 1200.00 + 900.00

    def test_no_match_for_unrelated_platform(self):
        stmt = parse_bank_csv(_hand_built_csv())
        total, count = find_platform_credits(stmt, "FoodDash Partner")
        assert count == 0
        assert total == 0.0


class TestAnalyzeIntegration:
    def test_full_metrics_on_hand_built_statement(self):
        stmt = parse_bank_csv(_hand_built_csv())
        metrics = analyze_bank_statement(stmt, gig_platform_name="ZipRide Partner")
        assert metrics.running_balance_is_consistent
        assert metrics.account_last4 == "4321"
        assert metrics.platform_credit_count == 3

    @pytest.mark.parametrize("persona", ["P01", "P02", "P03"])
    def test_real_persona_statements_are_arithmetically_consistent(self, persona):
        csv_path = DEMO_PACK / persona / "bank_statement.csv"
        stmt = parse_bank_csv(csv_path.read_text())
        assert verify_running_balance(stmt) == [], f"{persona} bank statement failed to reconcile"

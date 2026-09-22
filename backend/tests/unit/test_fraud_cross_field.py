import pytest

from app.services.fraud import cross_field
from app.services.fraud.policy import load_fraud_policy

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def policy():
    return load_fraud_policy()


class TestNameSimilarity:
    def test_matching_names_pass(self, policy):
        assert (
            cross_field.name_similarity_finding(
                label="x", name_a="Aarav Mehta", name_b="Aarav Mehta", policy=policy
            )
            is None
        )

    def test_reordered_name_passes(self, policy):
        # token_sort_ratio ignores word order.
        assert (
            cross_field.name_similarity_finding(
                label="x", name_a="Mehta Aarav", name_b="Aarav Mehta", policy=policy
            )
            is None
        )

    def test_completely_different_names_fail(self, policy):
        finding = cross_field.name_similarity_finding(
            label="x", name_a="Aarav Mehta", name_b="Farhan Sheikh", policy=policy
        )
        assert finding is not None
        assert finding.severity == "MEDIUM"

    def test_missing_name_is_skipped_not_flagged(self, policy):
        assert (
            cross_field.name_similarity_finding(
                label="x", name_a=None, name_b="Aarav Mehta", policy=policy
            )
            is None
        )


class TestVocationPlatform:
    def test_matching_vocation_and_platform_passes(self, policy):
        finding = cross_field.vocation_platform_finding(
            stated_vocation="ride-hailing driver", platform_names=["ZipRide Partner"], policy=policy
        )
        assert finding is None

    def test_mismatched_vocation_and_platform_is_flagged(self, policy):
        finding = cross_field.vocation_platform_finding(
            stated_vocation="ride-hailing driver",
            platform_names=["FoodDash Partner"],
            policy=policy,
        )
        assert finding is not None

    def test_unmapped_vocation_is_not_flagged(self, policy):
        # An unrecognised free-text vocation is not itself evidence of anything.
        finding = cross_field.vocation_platform_finding(
            stated_vocation="freelance photographer",
            platform_names=["ZipRide Partner"],
            policy=policy,
        )
        assert finding is None


class TestPayoutAccountMismatch:
    def test_matching_last4_passes(self, policy):
        assert (
            cross_field.payout_account_mismatch_finding(
                payout_account_last4="1234", bank_account_last4="1234", policy=policy
            )
            is None
        )

    def test_mismatched_last4_is_flagged(self, policy):
        finding = cross_field.payout_account_mismatch_finding(
            payout_account_last4="1234", bank_account_last4="5678", policy=policy
        )
        assert finding is not None
        assert finding.severity == "MEDIUM"


class TestIncomeReconciliation:
    def test_well_reconciled_income_passes(self, policy):
        assert (
            cross_field.income_reconciliation_finding(
                income_reconciliation_ratio=0.95, policy=policy
            )
            is None
        )

    def test_poorly_reconciled_income_is_flagged(self, policy):
        finding = cross_field.income_reconciliation_finding(
            income_reconciliation_ratio=0.2, policy=policy
        )
        assert finding is not None

    def test_missing_ratio_is_skipped(self, policy):
        assert (
            cross_field.income_reconciliation_finding(
                income_reconciliation_ratio=None, policy=policy
            )
            is None
        )

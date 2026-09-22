import pytest

from app.services.extraction.call_budget import CallBudget, CallBudgetExceeded

pytestmark = pytest.mark.unit


class TestCallBudget:
    def test_consume_within_budget_ok(self):
        budget = CallBudget(max_calls=3)
        budget.consume()
        budget.consume()
        assert budget.used == 2
        assert budget.remaining == 1

    def test_exceeding_budget_raises(self):
        budget = CallBudget(max_calls=1)
        budget.consume()
        with pytest.raises(CallBudgetExceeded):
            budget.consume()

    def test_used_count_unaffected_by_failed_consume(self):
        budget = CallBudget(max_calls=1)
        budget.consume()
        with pytest.raises(CallBudgetExceeded):
            budget.consume()
        assert budget.used == 1

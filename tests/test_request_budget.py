import pytest
from nordtrace.core.budget import RequestBudget, RuntimeBudget, CostTracker


def test_request_limit():
    budget = RequestBudget(global_limit=5)
    assert budget.can_request()
    budget.record(success=True)
    budget.record(success=True)
    budget.record(success=True)
    budget.record(success=True)
    budget.record(success=True)
    assert not budget.can_request()


def test_cost_tracker():
    tracker = CostTracker(global_limit=2.0)
    tracker.add("openai", "gpt-4o-mini", 100, 50, 0.01)
    assert tracker.remaining() == 1.99

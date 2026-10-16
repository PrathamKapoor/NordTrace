"""Synthetic invalid-input scale checks, not researched companies or recall evidence."""

import asyncio

import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.contracts import batch_payload, write_json_atomic
from nordtrace.core.repository import Repository
from nordtrace.engine.runner import BatchRunner


@pytest.mark.parametrize("size", [100, 1000])
def test_all_invalid_inputs_have_complete_terminal_envelopes_at_scale(size, tmp_path):
    supplied = [f"invalid-input-{index}" for index in range(size)]
    repo = Repository(tmp_path / "scale.db")
    budget = BudgetManager(max_requests=0, max_runtime_sec=120, max_cost=0)
    run = asyncio.run(BatchRunner(repo, budget).run_batch(supplied, requested_by="contract-test"))
    payload = batch_payload(run, repo.get_results(run.run_id), repo.get_run_inputs(run.run_id))
    assert payload["completion"] == {"complete": True, "input_count": size, "result_count": size}
    assert [result["organisation_number"] for result in payload["results"]] == supplied
    assert all(result["status"] == "not_applicable" for result in payload["results"])
    assert all(result["errors"][0]["code"] == "invalid_organisation_number" for result in payload["results"])
    assert budget.requests.total_used == 0
    assert budget.cost.total_used == 0
    write_json_atomic(tmp_path / "results.json", payload)
    assert not list(tmp_path.glob("results.json.*.tmp"))
    repo.close()

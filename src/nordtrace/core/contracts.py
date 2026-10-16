"""Versioned local evaluator adapter and the authoritative result serializer.

This is NordTrace's format. Organizer-schema acceptance is unverified.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from nordtrace.core.budget import BudgetManager
from nordtrace.core.models import CompanyProfile, ResearchError, ResearchMetadata, utcnow
from nordtrace.core.orgnr import validate_orgnr


class RunConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    max_requests: int = Field(ge=0)
    max_runtime_sec: float = Field(gt=0)
    max_cost_usd: float = Field(ge=0)
    per_company_sec: float = Field(default=90, gt=0)
    finalization_reserve_sec: float = Field(default=1, ge=0)


class InputMapping(BaseModel):
    index: int = Field(ge=0)
    supplied: str
    result_key: str


def map_inputs(values: list[str]) -> list[InputMapping]:
    return [
        InputMapping(index=index, supplied=value, result_key=check.value if check.valid else value)
        for index, value in enumerate(values)
        for check in [validate_orgnr(value)]
    ]


def build_result(outcome: Any, run_id: str, budget: BudgetManager, started_at: str) -> CompanyProfile:
    """Serialize the actual outcome, never infer it from a claim count."""
    completed = utcnow().isoformat()
    errors = []
    if getattr(outcome, "error", None):
        errors.append(ResearchError(
            code=getattr(outcome, "error_code", None) or "research_failed",
            message=outcome.error,
            stage=outcome.stages[-1] if outcome.stages else None,
        ))
    return CompanyProfile(
        run_id=run_id, organisation_number=outcome.org_number, status=outcome.terminal_state,
        company=outcome.identity, facts=outcome.facts, evidence=outcome.evidence,
        changes=outcome.changes, summary=outcome.summary, unknowns=outcome.unknowns,
        sources=outcome.sources, rejected_sources=outcome.rejected, coverage=outcome.coverage,
        errors=errors, refresh_metadata={"observed_at": completed},
        research_metadata=ResearchMetadata(
            started_at=started_at, completed_at=completed,
            duration_sec=getattr(outcome, "duration_sec", None),
            request_count=budget.requests.total_used, request_budget=budget.requests.global_limit,
            estimated_cost_usd=round(budget.cost.total_used, 6), cost_budget_usd=budget.cost.limit,
            time_remaining_sec=round(budget.runtime.time_remaining(), 3),
            stages_executed=outcome.stages, llm_calls=budget.cost.calls,
        ),
        last_researched_at=completed,
    )


def batch_payload(run: Any, results: list[CompanyProfile], inputs: list[dict]) -> dict:
    keys = [result.organisation_number for result in results]
    if len(keys) != len(set(keys)) or set(keys) != set(run.companies):
        raise ValueError("batch results do not correspond exactly to run inputs")
    if {item["result_key"] for item in inputs} != set(keys):
        raise ValueError("input mapping does not correspond to batch results")
    return {
        "schema_version": "1.1", "run_id": run.run_id, "state": run.state,
        "inputs": inputs, "results": [result.model_dump(mode="json") for result in results],
        "completion": {"complete": True, "input_count": len(inputs), "result_count": len(results)},
        "request_count": run.request_count, "estimated_cost_usd": run.estimated_cost_usd,
    }


def write_json_atomic(path: str | Path, payload: dict) -> None:
    """Flush a sibling temporary file before atomically making it visible."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=destination.name + ".", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, destination)
    finally:
        if os.path.exists(name):
            os.unlink(name)

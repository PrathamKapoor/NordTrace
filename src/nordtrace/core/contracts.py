"""Versioned local evaluator adapter and the authoritative result serializer.

This is NordTrace's format. Organizer-schema acceptance is unverified.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from nordtrace.core.budget import BudgetManager
from nordtrace.core.models import (
    CompanyIdentity,
    CompanyProfile,
    Fact,
    HtmlJsonLdLocator,
    JsonNumberLocator,
    ResearchError,
    ResearchMetadata,
    utcnow,
)
from nordtrace.core.models import RunConfiguration as RunConfiguration
from nordtrace.core.orgnr import validate_orgnr


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


def project_identity(
    identity: CompanyIdentity | None, conflicts: list[Fact], facts: list[Fact] | None = None,
) -> CompanyIdentity | None:
    """Expose supported structured values without changing the acquisition anchor.

    The required legacy legal_name string uses empty string for unresolved names.
    unresolved_fields distinguishes this from a successfully verified blank value.
    """
    if identity is None:
        return None
    fields = set(identity.unresolved_fields)
    updates: dict[str, Any] = {}
    if facts is not None:
        observations = [fact for fact in facts
                        if fact.org_number == identity.organisation_number and fact.category == "identity"
                        and fact.status == "PUBLISHED" and fact.subject_scope == "legal_entity"
                        and fact.item_key is None]
        supported = {fact.field: fact for fact in observations}
        metadata = {"organisation_number", "last_verified_at", "unresolved_fields"}
        for field in CompanyIdentity.model_fields.keys() - metadata:
            if field in supported:
                updates[field] = supported[field].value
                fields.discard(field)
            else:
                previous = getattr(identity, field)
                if previous is not None and previous != "" and previous != "unknown":
                    fields.add(field)
                updates[field] = "" if field == "legal_name" else "unknown" if field == "status" else None
        timestamps = []
        for fact in observations:
            if fact.retrieved_at:
                try:
                    observed_at = datetime.fromisoformat(fact.retrieved_at)
                except ValueError:
                    continue
                if observed_at.tzinfo is not None:
                    timestamps.append((observed_at, fact.retrieved_at))
        updates["last_verified_at"] = max(timestamps, key=lambda item: item[0])[1] if timestamps else None
    disputed_fields = set()
    for fact in conflicts:
        if fact.org_number == identity.organisation_number and fact.category == "identity":
            if fact.field in CompanyIdentity.model_fields and fact.field != "organisation_number":
                fields.add(fact.field)
                disputed_fields.add(fact.field)
    dependencies = fields if facts is None else disputed_fields
    if "registered_address" in dependencies:
        fields.update(("municipality", "postal_code"))
    if "status" in dependencies:
        fields.update(("bankrupt", "under_liquidation", "deleted_date"))
    updates.update(dict.fromkeys(fields))
    if "legal_name" in fields:
        updates["legal_name"] = ""
    if "status" in fields:
        updates["status"] = "unknown"
    updates["unresolved_fields"] = sorted(fields)
    return CompanyIdentity.model_validate(identity.model_dump() | updates)


def result_version(evidence: Any) -> Literal["1.1", "1.2", "1.3"]:
    """Smallest frozen contract able to represent every locator kind present."""
    if any(isinstance(item.locator, JsonNumberLocator) for item in evidence):
        return "1.3"
    return "1.2" if any(isinstance(item.locator, HtmlJsonLdLocator) for item in evidence) else "1.1"


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
        schema_version=result_version(outcome.evidence),
        run_id=run_id, organisation_number=outcome.org_number, status=outcome.terminal_state,
        status_reason=(getattr(outcome, "error_code", None) or getattr(outcome, "status_reason", None) or {
            "available": "research_completed", "not_available": "information_not_available",
            "blocked": "research_blocked", "not_applicable": "research_not_applicable",
            "ambiguous": "research_ambiguous", "failed": "research_failed",
        }.get(outcome.terminal_state, "unrecognized_terminal_outcome")),
        company=project_identity(outcome.identity, getattr(outcome, "conflicts", []), outcome.facts),
        facts=outcome.facts, evidence=outcome.evidence,
        conflicts=getattr(outcome, "conflicts", []),
        last_known=getattr(outcome, "last_known", []),
        refresh_outcomes=getattr(outcome, "refresh_outcomes", []),
        previous_run_id=getattr(outcome, "previous_run_id", None),
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
            run_configuration=budget.configuration,
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
        "schema_version": max((result.schema_version for result in results), default="1.1",
                              key=("1.1", "1.2", "1.3").index),
        "run_id": run.run_id, "state": run.state,
        "inputs": inputs, "results": [result.model_dump(mode="json") for result in results],
        "completion": {"complete": True, "input_count": len(inputs), "result_count": len(results)},
        "request_count": run.request_count, "estimated_cost_usd": run.estimated_cost_usd,
    }


def write_json_atomic(path: str | Path, payload: dict) -> None:
    body = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    write_bytes_atomic(path, body)


def write_bytes_atomic(path: str | Path, body: bytes) -> None:
    """Flush a sibling temporary file before atomically making it visible."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=destination.name + ".", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, destination)
    finally:
        if os.path.exists(name):
            os.unlink(name)

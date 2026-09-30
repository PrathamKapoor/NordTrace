"""Result schema validation for research/benchmark output files."""
from __future__ import annotations

import re
from typing import Any, Dict, List

_REQUIRED_TOP = ["run_id", "organisation_number", "status"]
_VALID_STATUS = {"available", "not_available", "blocked", "not_applicable", "ambiguous", "failed"}
_ORGNR_RE = re.compile(r"^\d{9}$")


def validate_result(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    for k in _REQUIRED_TOP:
        if k not in data:
            errors.append(f"missing required field: {k}")
    status = data.get("status")
    if status is not None and status not in _VALID_STATUS:
        errors.append(f"invalid status: {status!r} (expected one of {sorted(_VALID_STATUS)})")
    orgnr = data.get("organisation_number")
    if orgnr is not None and not _ORGNR_RE.match(str(orgnr).replace(" ", "")):
        errors.append(f"invalid organisation_number format: {orgnr!r}")
    # metadata sanity
    meta = data.get("research_metadata") or {}
    rc = meta.get("request_count")
    if rc is not None and (not isinstance(rc, int) or rc < 0):
        errors.append("research_metadata.request_count must be a non-negative integer")
    cost = meta.get("estimated_cost_usd")
    if cost is not None and (not isinstance(cost, (int, float)) or cost < 0):
        errors.append("research_metadata.estimated_cost_usd must be a non-negative number")
    # facts structure
    facts = data.get("facts")
    if facts is not None:
        if not isinstance(facts, list):
            errors.append("facts must be a list")
        else:
            for i, f in enumerate(facts):
                if not isinstance(f, dict):
                    errors.append(f"facts[{i}] must be an object")
                    continue
                for req in ("fact_id", "org_number", "category", "field", "source_id", "evidence_id"):
                    if req not in f:
                        errors.append(f"facts[{i}] missing {req}")
    # changes structure
    changes = data.get("changes")
    if changes is not None and not isinstance(changes, list):
        errors.append("changes must be a list")
    return errors

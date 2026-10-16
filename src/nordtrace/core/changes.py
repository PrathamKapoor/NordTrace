"""Change detection: fact-level diff between runs.

Compare previous verified facts (from an earlier run) with current facts.
Detect NEW / CHANGED / RETRACTED / UNCHANGED / SOURCE_UNAVAILABLE per fact
slot, with explanations. Preserves history (previous values stay in the ledger).
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional

from nordtrace.core.models import ChangeRecord, Fact, utcnow

_CHANGE_EXPLANATIONS = {
    "NEW": "New verified fact not present in the previous run.",
    "CHANGED": "Value changed since the previous run.",
    "RETRACTED": "Fact present in the previous run but not found in this run.",
    "SOURCE_UNAVAILABLE": "Previous observation was not reconfirmed; absence is not evidence of removal.",
    "UNCHANGED": "Value confirmed by this run.",
}


def detect_changes(
    org_number: str,
    run_id: str,
    previous_facts: List[Fact],
    current_facts: List[Fact],
    current_sources_ok: bool = True,
) -> List[ChangeRecord]:
    """Diff logical claims, preserving period/item/scope distinctions.

    current_facts should contain only PUBLISHED (verified) facts of this run.
    previous_facts are the latest PUBLISHED facts from earlier runs.
    current_sources_ok is retained for call compatibility; successful transport
    cannot establish source/extraction completeness or affirmative removal.
    No producer currently provides verified removal proof, so missing claims
    always remain unconfirmed, never RETRACTED.
    """
    now = utcnow().isoformat()
    prev_by_slot: Dict[str, Fact] = {}
    for f in previous_facts:
        prev_by_slot[f.fact_key()] = f
    curr_by_slot: Dict[str, Fact] = {}
    for f in current_facts:
        curr_by_slot[f.fact_key()] = f

    changes: List[ChangeRecord] = []
    for slot, prev in prev_by_slot.items():
        cur = curr_by_slot.get(slot)
        if cur is None:
            changes.append(_mk(org_number, run_id, slot, prev, None, "SOURCE_UNAVAILABLE", now))
            continue
        if assertions_differ(prev, cur):
            changes.append(_mk(org_number, run_id, slot, prev, cur, "CHANGED", now))
        else:
            changes.append(_mk(org_number, run_id, slot, prev, cur, "UNCHANGED", now))
    for slot, cur in curr_by_slot.items():
        if slot not in prev_by_slot:
            changes.append(_mk(org_number, run_id, slot, None, cur, "NEW", now))
    # order: changes first, then new, then unchanged
    order = {"CHANGED": 0, "SOURCE_UNAVAILABLE": 1, "RETRACTED": 2, "NEW": 3, "UNCHANGED": 4}
    changes.sort(key=lambda c: order.get(c.change_type, 9))
    return changes


def _mk(
    org_number: str, run_id: str, slot: str, prev: Optional[Fact], cur: Optional[Fact], ctype: str, now: str
) -> ChangeRecord:
    representative = cur or prev
    assert representative is not None
    return ChangeRecord(
        org_number=org_number,
        run_id=run_id,
        change_type=ctype,
        field=representative.field,
        category=representative.category,
        reporting_period=representative.reporting_period,
        claim_id=representative.claim_id,
        item_key=representative.item_key,
        subject_scope=representative.subject_scope,
        previous_value=prev.value if prev else None,
        current_value=cur.value if cur else None,
        previous_source_id=prev.source_id if prev else None,
        current_source_id=cur.source_id if cur else None,
        previous_evidence_id=prev.evidence_id if prev else None,
        current_evidence_id=cur.evidence_id if cur else None,
        previous_observation_id=prev.fact_id if prev else None,
        current_observation_id=cur.fact_id if cur else None,
        detected_at=now,
        explanation=_CHANGE_EXPLANATIONS.get(ctype, ctype),
    )


def assertions_differ(a: Fact, b: Fact) -> bool:
    """Compare published values/qualifiers, not a shortened extraction label."""
    for field in ("currency", "unit", "valid_from", "valid_to"):
        if getattr(a, field) != getattr(b, field):
            return True
    if (
        a.category == b.category == "financials"
        and not isinstance(a.value, bool) and not isinstance(b.value, bool)
    ):
        try:
            va, vb = Decimal(str(a.value)), Decimal(str(b.value))
            if va.is_finite() and vb.is_finite():
                return va != vb  # Exact numeric equality, without a float epsilon.
        except InvalidOperation:
            pass
    before = json.dumps(a.model_dump(mode="json", include={"value"}), sort_keys=True, allow_nan=False)
    after = json.dumps(b.model_dump(mode="json", include={"value"}), sort_keys=True, allow_nan=False)
    return before != after

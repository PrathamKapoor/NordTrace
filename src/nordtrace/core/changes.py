"""Change detection: fact-level diff between runs.

Compare previous verified facts (from an earlier run) with current facts.
Detect NEW / CHANGED / RETRACTED / UNCHANGED / SOURCE_UNAVAILABLE per fact
slot, with explanations. Preserves history (previous values stay in the ledger).
"""
from __future__ import annotations

from typing import Dict, List, Optional

from nordtrace.core.models import ChangeRecord, Fact, FactStatus, utcnow

_CHANGE_EXPLANATIONS = {
    "NEW": "New verified fact not present in the previous run.",
    "CHANGED": "Value changed since the previous run.",
    "RETRACTED": "Fact present in the previous run but not found in this run.",
    "SOURCE_UNAVAILABLE": "Source was unavailable in this run; previous value retained but marked unverified.",
    "UNCHANGED": "Value confirmed by this run.",
}


def detect_changes(
    org_number: str,
    run_id: str,
    previous_facts: List[Fact],
    current_facts: List[Fact],
    current_sources_ok: bool = True,
) -> List[ChangeRecord]:
    """Fact-slot-level diff. A fact slot is (category, field, reporting_period).

    current_facts should contain only PUBLISHED (verified) facts of this run.
    previous_facts are the latest PUBLISHED facts from earlier runs.
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
        if prev.status == FactStatus.SOURCE_UNAVAILABLE.value and not current_sources_ok:
            changes.append(_mk(org_number, run_id, slot, prev, None, "SOURCE_UNAVAILABLE", now))
            continue
        cur = curr_by_slot.get(slot)
        if cur is None:
            changes.append(_mk(org_number, run_id, slot, prev, None, "RETRACTED", now))
            continue
        if _differs(prev, cur):
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


def _mk(org_number: str, run_id: str, slot: str, prev: Optional[Fact], cur: Optional[Fact],
        ctype: str, now: str) -> ChangeRecord:
    category, field, period = (slot.split("|") + ["", ""])[:3]
    return ChangeRecord(
        org_number=org_number,
        run_id=run_id,
        change_type=ctype,
        field=field,
        category=category,
        reporting_period=period or None,
        previous_value=prev.value if prev else None,
        current_value=cur.value if cur else None,
        previous_source_id=prev.source_id if prev else None,
        current_source_id=cur.source_id if cur else None,
        detected_at=now,
        explanation=_CHANGE_EXPLANATIONS.get(ctype, ctype),
    )


def _differs(a: Fact, b: Fact) -> bool:
    va, vb = a.normalized_value, b.normalized_value
    if va is None and vb is None:
        return False
    if isinstance(va, float) and isinstance(vb, float):
        return abs(va - vb) > 1e-9
    if isinstance(va, dict) and isinstance(vb, dict):
        return va != vb
    return va != vb

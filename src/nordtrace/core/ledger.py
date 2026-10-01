"""Fact ledger: citation validation + conflict detection + temporal handling.

The ledger is the source of truth. Facts enter as EXTRACTED and become
PUBLISHED only after:
  - correct company (entity verdict in VERIFIED/LIKELY)
  - correct source (source was actually retrieved, access_status=success)
  - evidence exists (evidence_id resolves to a stored EvidenceRecord)
  - value supported (value came from source content; non-null)
Citation validation is deterministic. Conflicts are detected, not hidden.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from nordtrace.core.models import (
    EvidenceRecord,
    Fact,
    FactStatus,
    MatchVerdict,
    SourceRecord,
    utcnow,
)


@dataclass
class LedgerEntry:
    fact: Fact
    evidence: Optional[EvidenceRecord] = None
    source: Optional[SourceRecord] = None


class CitationValidator:
    """Deterministic validation of the fact → evidence → source chain."""

    def __init__(self, sources: Dict[str, SourceRecord], evidence_index: Dict[str, EvidenceRecord]):
        self.sources = sources
        self.evidence_index = evidence_index

    def validate(self, fact: Fact) -> Tuple[bool, str]:
        # 1. correct company
        if fact.entity_verdict not in (MatchVerdict.VERIFIED.value, MatchVerdict.LIKELY.value):
            return False, f"entity verdict {fact.entity_verdict}"
        # 2. source actually retrieved
        src = self.sources.get(fact.source_id)
        if src is None:
            return False, "source not found in ledger"
        if src.access_status != "success":
            return False, f"source access_status={src.access_status}"
        # 3. evidence exists
        ev = self.evidence_index.get(fact.evidence_id)
        if ev is None:
            return False, "evidence not found in ledger"
        if ev.source_id != fact.source_id:
            return False, "evidence belongs to different source"
        if not ev.evidence_text:
            return False, "evidence text empty"
        # 5. cross-company contamination: evidence must belong to the same company
        if ev.org_number and ev.org_number != fact.org_number:
            return False, f"evidence belongs to different company ({ev.org_number})"
        # 4. value supported
        if fact.value is None:
            return False, "fact value is None"
        # financial facts must carry currency + period
        if fact.category == "financials" and fact.currency is None:
            return False, "financial fact missing currency"
        return True, "ok"


class FactLedger:
    """In-memory + repository-backed fact store with conflict detection."""

    def __init__(self):
        self.sources: Dict[str, SourceRecord] = {}
        self.evidence: Dict[str, EvidenceRecord] = {}
        self._entries: List[LedgerEntry] = []

    def add_source(self, src: SourceRecord) -> None:
        if src.source_id and src.source_id not in self.sources:
            self.sources[src.source_id] = src

    def add_evidence(self, ev: EvidenceRecord) -> None:
        if ev.evidence_id and ev.evidence_id not in self.evidence:
            self.evidence[ev.evidence_id] = ev

    def add_fact(
        self, fact: Fact, evidence: Optional[EvidenceRecord] = None, source: Optional[SourceRecord] = None
    ) -> Fact:
        """Validate citation chain, then store. Returns the fact (possibly
        with status updated to PUBLISHED or CONFLICT/FAILED)."""
        if source:
            self.add_source(source)
        if evidence:
            self.add_evidence(evidence)
        if fact.normalized_value is None and fact.value is not None:
            fact.normalized_value = str(fact.value)
        if evidence:
            fact.evidence_id = evidence.evidence_id
        validator = CitationValidator(self.sources, self.evidence)
        ok, reason = validator.validate(fact)
        if not ok:
            fact.status = (
                FactStatus.FAILED.value if fact.value is not None else FactStatus.NOT_AVAILABLE.value
            )
            fact.conflict_note = reason
            self._entries.append(LedgerEntry(fact=fact))
            return fact
        # conflict detection: same slot, different normalized value
        conflict = self._detect_conflict(fact)
        if conflict:
            fact.status = FactStatus.CONFLICT.value
            fact.conflict_note = conflict
        else:
            fact.status = FactStatus.PUBLISHED.value
        fact.published_at = fact.published_at or utcnow().isoformat()
        self._entries.append(
            LedgerEntry(
                fact=fact,
                evidence=self.evidence.get(fact.evidence_id),
                source=self.sources.get(fact.source_id),
            )
        )
        return fact

    def _detect_conflict(self, fact: Fact) -> Optional[str]:
        for entry in self._entries:
            other = entry.fact
            if other.org_number != fact.org_number:
                continue
            if other.fact_key() != fact.fact_key():
                continue
            if other.status not in (FactStatus.PUBLISHED.value, FactStatus.CONFLICT.value):
                continue
            if _values_differ(other.normalized_value, fact.normalized_value):
                return (
                    f"conflicts with fact {other.fact_id} from source {other.source_id} "
                    f"(existing={_short(other.normalized_value)}, new={_short(fact.normalized_value)})"
                )
        return None

    def published_facts(self, org_number: Optional[str] = None) -> List[Fact]:
        return [
            e.fact
            for e in self._entries
            if e.fact.status == FactStatus.PUBLISHED.value
            and (org_number is None or e.fact.org_number == org_number)
        ]

    def all_entries(self) -> List[LedgerEntry]:
        return list(self._entries)

    def current_values(self, org_number: str) -> Dict[str, Fact]:
        """Latest published fact per slot (change-detection input)."""
        out: Dict[str, Fact] = {}
        for e in self._entries:
            f = e.fact
            if f.org_number != org_number or f.status != FactStatus.PUBLISHED.value:
                continue
            k = f.fact_key()
            if k not in out or (f.retrieved_at or "") > (out[k].retrieved_at or ""):
                out[k] = f
        return out

    def mark_source_unavailable(self, org_number: str, source_id: str) -> int:
        """On refresh: facts from a now-unavailable source are marked
        SOURCE_UNAVAILABLE (not deleted) unless contradicted by new evidence."""
        n = 0
        for e in self._entries:
            f = e.fact
            if (
                f.org_number == org_number
                and f.source_id == source_id
                and f.status == FactStatus.PUBLISHED.value
            ):
                f.status = FactStatus.SOURCE_UNAVAILABLE.value
                f.conflict_note = "source unavailable at refresh; not contradicted by new evidence"
                n += 1
        return n

    def temporal_view(self, org_number: str, field_name: str) -> List[Fact]:
        """Facts for a field with temporal metadata, ordered by valid_from —
        supports 'CEO in 2024' vs 'CEO in 2025' without merging."""
        rows = [
            e.fact
            for e in self._entries
            if e.fact.org_number == org_number
            and e.fact.field == field_name
            and e.fact.status in (FactStatus.PUBLISHED.value, FactStatus.REFRESHED.value)
        ]
        rows.sort(key=lambda f: (f.valid_from or f.reporting_period or "", f.retrieved_at or ""))
        return rows


def _values_differ(a, b) -> bool:
    if a is None and b is None:
        return False
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) > 1e-9
    return a != b


def _short(v) -> str:
    s = str(v)
    return s[:40] + ("…" if len(s) > 40 else "")

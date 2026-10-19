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

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

from nordtrace.core.changes import assertions_differ
from nordtrace.core.evidence import SnapshotReader, verify_snapshot_support
from nordtrace.core.models import (
    EvidenceRecord,
    Fact,
    FactStatus,
    HtmlJsonLdLocator,
    MatchVerdict,
    SourceRecord,
    utcnow,
)
from nordtrace.core.repository import Repository


@dataclass
class LedgerEntry:
    fact: Fact
    evidence: Optional[EvidenceRecord] = None
    source: Optional[SourceRecord] = None


class CitationValidator:
    """Deterministic validation of the fact → evidence → source chain."""

    def __init__(
        self, sources: Dict[str, SourceRecord], evidence_index: Dict[str, EvidenceRecord],
        repository: Optional[SnapshotReader] = None,
    ):
        self.sources = sources
        self.evidence_index = evidence_index
        self.repository = repository

    def validate(self, fact: Fact) -> Tuple[bool, str]:
        # 1. correct company
        if fact.entity_verdict not in (MatchVerdict.VERIFIED.value, MatchVerdict.LIKELY.value):
            return False, f"entity verdict {fact.entity_verdict}"
        if (fact.category, fact.field) in (("jobs", "job_posting"), ("locations", "branch")):
            if not fact.item_key or not fact.item_key.strip():
                return False, "collection claim requires a stable source item key"
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
        if (src.source_type == "company_website"
                or (src.content_type or "").lower().split(";", 1)[0].strip() == "text/html"):
            if not isinstance(ev.locator, HtmlJsonLdLocator):
                return False, "HTML publication requires a typed retained-content locator"
        if not ev.evidence_text:
            return False, "evidence text empty"
        if ev.entity_verdict != fact.entity_verdict:
            return False, "claim and evidence identity verdicts disagree"
        if src.org_number and src.org_number != fact.org_number:
            return False, "source belongs to different company"
        if ev.content_hash and src.content_hash != ev.content_hash:
            return False, "source and evidence hashes disagree"
        # 5. cross-company contamination: evidence must belong to the same company
        if ev.org_number and ev.org_number != fact.org_number:
            return False, f"evidence belongs to different company ({ev.org_number})"
        # 4. value supported
        if fact.value is None:
            return False, "fact value is None"
        # financial facts must carry currency + period
        if fact.category == "financials":
            if not fact.currency:
                return False, "financial fact missing currency"
            if not fact.reporting_period:
                return False, "financial fact missing reporting period"
            if not re.search(r"\b" + re.escape(fact.currency) + r"\b", ev.evidence_text):
                return False, "financial currency absent from evidence"
            year = re.search(r"(?:19|20)[0-9]{2}", fact.reporting_period)
            if not year or year[0] not in ev.evidence_text:
                return False, "financial reporting year absent from evidence"
            if not _quoted_number(fact.value, ev.evidence_text):
                return False, "financial value absent from evidence"
            if self.repository is None:
                return False, "financial support requires retained snapshots"
        if isinstance(ev.locator, HtmlJsonLdLocator):
            if self.repository is None:
                return False, "HTML support requires retained snapshots"
            anchor = self.sources.get(ev.locator.identity_source_id)
            if anchor is None:
                return False, "HTML identity anchor missing from ledger"
            try:
                from nordtrace.core.evidence import verify_capture_metadata
                captured, _ = self.repository.read_capture(anchor.source_id)
                verify_capture_metadata(captured, anchor)
            except (ValueError, KeyError, TypeError) as error:
                return False, f"HTML anchor: {error}"
        if self.repository is not None:
            try:
                verify_snapshot_support(self.repository, fact, src, ev)
            except (ValueError, KeyError, TypeError, RecursionError) as error:
                return False, f"snapshot support: {error}"
        return True, "ok"


def _quoted_number(value, text: str) -> bool:
    """Necessary numeric support check; does not establish table/column semantics.

    Until snapshot-backed locators and table scope are implemented, this is a
    conservative extra rejection gate, not a complete evidence verifier.
    """
    if isinstance(value, bool):
        return False
    try:
        expected = Decimal(str(value))
    except InvalidOperation:
        return False
    if not expected.is_finite():
        return False
    digits = r"(?:[0-9]{1,3}(?:[ \u00a0][0-9]{3})+|[0-9]+)(?:[.,][0-9]+)?"
    tokens = re.findall(r"(?<![\w.,(])(?:\(" + digits + r"\)|[-+]?" + digits + r")(?![\w.,)])", text)
    for token in tokens:
        cleaned = token.replace(" ", "").replace("\u00a0", "").replace(",", ".")
        number = -Decimal(cleaned[1:-1]) if cleaned.startswith("(") else Decimal(cleaned)
        if number == expected:
            return True
    return False


class FactLedger:
    """In-memory + repository-backed fact store with conflict detection."""

    def __init__(self, repository: Optional[Repository] = None):
        self.repository = repository
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
        validator = CitationValidator(self.sources, self.evidence, self.repository)
        ok, reason = validator.validate(fact)
        if not ok:
            fact.status = (
                FactStatus.FAILED.value if fact.value is not None else FactStatus.NOT_AVAILABLE.value
            )
            fact.conflict_note = reason
            self._entries.append(LedgerEntry(fact=fact))
            return fact
        source_record = self.sources[fact.source_id]
        for entry in self._entries:
            existing = entry.fact
            if existing is fact:
                return existing
            prior_source = self.sources.get(existing.source_id)
            if (
                existing.status == FactStatus.PUBLISHED.value and existing.fact_key() == fact.fact_key()
                and prior_source and source_record.content_hash
                and prior_source.content_hash == source_record.content_hash
                and existing.value == fact.value and existing.normalized_value == fact.normalized_value
                and existing.unit == fact.unit and existing.currency == fact.currency
                and existing.valid_from == fact.valid_from and existing.valid_to == fact.valid_to
            ):
                fact.status = FactStatus.DUPLICATE.value
                fact.conflict_note = f"same claim and snapshot as observation {existing.fact_id}"
                return existing
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
        competing = []
        for entry in self._entries:
            other = entry.fact
            if other.org_number != fact.org_number:
                continue
            if other.fact_key() != fact.fact_key():
                continue
            if other.status not in (FactStatus.PUBLISHED.value, FactStatus.CONFLICT.value):
                continue
            competing.append(other)
        if competing and (
            any(other.status == FactStatus.CONFLICT.value for other in competing)
            or any(assertions_differ(other, fact) for other in competing)
        ):
            note = f"unresolved conflict for {fact.claim_id}; competing observations withheld"
            for other in competing:
                other.status = FactStatus.CONFLICT.value
                other.conflict_note = note
            return note
        return None

    def conflicting_facts(self, org_number: Optional[str] = None) -> List[Fact]:
        return [
            entry.fact for entry in self._entries if entry.fact.status == FactStatus.CONFLICT.value
            and (org_number is None or entry.fact.org_number == org_number)
        ]

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

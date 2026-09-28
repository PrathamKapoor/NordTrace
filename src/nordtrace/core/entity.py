from __future__ import annotations

from typing import Optional, Dict, List, Any
from .models import CompanyIdentity, Source, Evidence, Fact

ENTITY_MATCH_CLASS = ["VERIFIED", "LIKELY", "AMBIGUOUS", "REJECTED"]


class EntityResolver:
    def __init__(self):
        pass

    def match(self, candidate_text: str, company_identity: CompanyIdentity) -> str:
        import re
        # Simple deterministic checks
        if not candidate_text:
            return "REJECTED"
        # Check for contradictory org numbers (any 9-digit number that isn't ours)
        digits_found = re.findall(r"\b\d{9}\b", candidate_text)
        for d in digits_found:
            if d != company_identity.organisation_number:
                return "REJECTED"
        # Check org number presence
        if company_identity.organisation_number in candidate_text:
            return "VERIFIED"


class PublicationFirewall:
    def __init__(self):
        self.rejected_candidates: List[Dict[str, Any]] = []

    def allow(self, source: Source, company_identity: CompanyIdentity, extract_text: str) -> bool:
        match_result = EntityResolver().match(extract_text or "", company_identity)
        if match_result == "REJECTED":
            self.rejected_candidates.append({
                "source_id": source.source_id,
                "reason": "REJECTED",
                "match_result": match_result,
                "text_snippet": extract_text[:200] if extract_text else None,
            })
            return False
        if match_result in ("VERIFIED", "LIKELY"):
            return True
        # Ambiguous requires manual review or stronger evidence
        return False

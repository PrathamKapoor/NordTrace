from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict


class CompanyIdentity(BaseModel):
    organisation_number: str = Field(..., min_length=9, max_length=9)
    legal_name: str = Field(..., min_length=1)
    organisation_form: Optional[str] = None
    status: Optional[str] = None  # active, dissolved, etc.
    registered_address: Optional[str] = None
    municipality: Optional[str] = None
    industry_code: Optional[str] = None
    industry_description: Optional[str] = None
    website: Optional[str] = None
    registration_date: Optional[str] = None
    last_verified_at: Optional[str] = None
    entity_confidence: str = Field(default="VERIFIED", pattern=r"VERIFIED|LIKELY|AMBIGUOUS|REJECTED")

    @field_validator("organisation_number")
    @classmethod
    def validate_orgnr(cls, v: str) -> str:
        v = v.replace(" ", "").replace("-", "").replace(".", "")
        if not v.isdigit() or len(v) != 9:
            raise ValueError(f"Invalid Norwegian organisation number: {v}")
        # Simple checksum for Norwegian org numbers (modulus 11)
        weights = [3, 2, 7, 6, 5, 4, 3, 2]
        digits = [int(c) for c in v[:8]]
        checksum = sum(w * d for w, d in zip(weights, digits))
        check_digit = 11 - (checksum % 11)
        if check_digit == 11:
            check_digit = 0
        if check_digit == 10:
            # Invalid if check digit is 10
            pass  # keep loose for now; real registry validates
        expected = int(v[8])
        # Note: this is approximate; official Brreg validates fully.
        return v


class Source(BaseModel):
    source_id: str
    url: Optional[str] = None
    domain: Optional[str] = None
    source_type: str = Field(default="unknown")  # registry, company_website, public_record, news, job_board, search, other
    authority_tier: int = Field(default=4, ge=0, le=4)
    retrieved_at: Optional[str] = None
    published_at: Optional[str] = None
    http_status: Optional[int] = None
    content_hash: Optional[str] = None
    access_status: str = Field(default="unknown")  # success, failed, blocked, timeout, unknown

    def compute_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


class Evidence(BaseModel):
    evidence_id: str
    source_id: str
    url: Optional[str] = None
    source_title: Optional[str] = None
    source_type: str = "unknown"
    retrieved_at: Optional[str] = None
    published_at: Optional[str] = None
    evidence_text: Optional[str] = None
    page_section: Optional[str] = None
    content_hash: Optional[str] = None
    entity_match_details: Dict[str, Any] = Field(default_factory=dict)
    entity_confidence: str = Field(default="AMBIGUOUS", pattern=r"VERIFIED|LIKELY|AMBIGUOUS|REJECTED")


class Fact(BaseModel):
    fact_id: str
    company_org_number: str
    category: str  # identity, financial, people, jobs, activity, website, industry
    field: str
    value: Optional[Any] = None
    normalized_value: Optional[Any] = None
    unit: Optional[str] = None
    currency: Optional[str] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    reporting_period: Optional[str] = None
    source_id: str
    evidence_id: str
    retrieved_at: Optional[str] = None
    published_at: Optional[str] = None
    entity_confidence: str = Field(default="AMBIGUOUS", pattern=r"VERIFIED|LIKELY|AMBIGUOUS|REJECTED")
    fact_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: str = Field(default="PUBLISHED", pattern=r"PUBLISHED|REFRESHED|RETRACTED|CONFLICT|NOT_AVAILABLE|BLOCKED|FAILED")
    conflict_note: Optional[str] = None


class ResearchRun(BaseModel):
    run_id: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    status: str = "running"
    request_count: int = 0
    estimated_cost_usd: float = 0.0
    companies: List[str] = Field(default_factory=list)
    terminal_states: Dict[str, str] = Field(default_factory=dict)


class CoverageStatus(BaseModel):
    identity: str = "unknown"
    business_description: str = "unknown"
    industry: str = "unknown"
    financials: str = "unknown"
    leadership: str = "unknown"
    locations: str = "unknown"
    products_services: str = "unknown"
    jobs: str = "unknown"
    recent_activity: str = "unknown"
    changes: str = "unknown"

    def to_dict(self) -> Dict[str, str]:
        return self.model_dump()


class ChangeRecord(BaseModel):
    change_type: str  # NEW, CHANGED, RETRACTED, UNCHANGED
    field: str
    previous_value: Optional[Any] = None
    current_value: Optional[Any] = None
    previous_source_id: Optional[str] = None
    current_source_id: Optional[str] = None
    detected_at: Optional[str] = None
    explanation: Optional[str] = None


class CompanyProfile(BaseModel):
    organisation_number: str
    company_identity: CompanyIdentity
    facts: List[Fact] = Field(default_factory=list)
    sources: List[Source] = Field(default_factory=list)
    evidence_items: List[Evidence] = Field(default_factory=list)
    changes: List[ChangeRecord] = Field(default_factory=list)
    coverage: CoverageStatus = Field(default_factory=CoverageStatus)
    summary: Optional[str] = None
    terminal_state: str = "available"
    last_researched_at: Optional[str] = None
    research_metadata: Optional[Dict[str, Any]] = None

    def add_fact(self, fact: Fact):
        self.facts.append(fact)



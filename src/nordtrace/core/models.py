"""Domain models: Company, Fact, Evidence, Source, Changes, Coverage, Run.

The fact ledger is the source of truth: profiles are derived from facts,
never the other way around.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from nordtrace.core.orgnr import validate_orgnr

# ---------------------------------------------------------------------------
# Enums / vocabularies
# ---------------------------------------------------------------------------


class MatchVerdict(str, Enum):
    VERIFIED = "VERIFIED"
    LIKELY = "LIKELY"
    AMBIGUOUS = "AMBIGUOUS"
    REJECTED = "REJECTED"


class FactStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    EXTRACTED = "EXTRACTED"
    ENTITY_VERIFIED = "ENTITY_VERIFIED"
    EVIDENCE_VERIFIED = "EVIDENCE_VERIFIED"
    PUBLISHED = "PUBLISHED"
    REFRESHED = "REFRESHED"
    CONFLICT = "CONFLICT"
    RETRACTED = "RETRACTED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


class TerminalState(str, Enum):
    AVAILABLE = "available"
    NOT_AVAILABLE = "not_available"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"


class SourceType(str, Enum):
    REGISTRY = "registry"
    REGISTRY_ACCOUNTS = "registry_accounts"
    COMPANY_WEBSITE = "company_website"
    COMPANY_DOCUMENT = "company_document"
    JOB_BOARD = "job_board"
    PUBLIC_SECTOR = "public_sector"
    NEWS = "news"
    SEARCH = "search"
    OTHER = "other"


class CoverageCategory(str, Enum):
    IDENTITY = "identity"
    BUSINESS_DESCRIPTION = "business_description"
    INDUSTRY = "industry"
    FINANCIALS = "financials"
    LEADERSHIP = "leadership"
    LOCATIONS = "locations"
    PRODUCTS_SERVICES = "products_services"
    JOBS = "jobs"
    RECENT_ACTIVITY = "recent_activity"
    CHANGES = "changes"


COVERAGE_CATEGORIES = [c.value for c in CoverageCategory]


class CategoryState(str, Enum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    NOT_AVAILABLE = "not_available"
    BLOCKED = "blocked"
    AMBIGUOUS = "ambiguous"


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


# ---------------------------------------------------------------------------
# Company identity — canonical entity from the registry
# ---------------------------------------------------------------------------


class CompanyIdentity(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    organisation_number: str
    legal_name: str
    organisation_form: Optional[str] = None
    organisation_form_description: Optional[str] = None
    status: str = "unknown"  # active / under_liquidation / bankrupt / deleted / unknown
    registered_address: Optional[str] = None
    postal_address: Optional[str] = None
    municipality: Optional[str] = None
    postal_code: Optional[str] = None
    industry_code: Optional[str] = None
    industry_description: Optional[str] = None
    website: Optional[str] = None
    registration_date: Optional[str] = None
    employee_count: Optional[int] = None
    share_capital: Optional[float] = None
    share_capital_currency: Optional[str] = None
    number_of_shares: Optional[int] = None
    is_part_of_concern: bool = False
    bankrupt: Optional[bool] = None
    under_liquidation: Optional[bool] = None
    deleted_date: Optional[str] = None
    last_verified_at: Optional[str] = None

    def validate_format(self) -> bool:
        return validate_orgnr(self.organisation_number).valid


# ---------------------------------------------------------------------------
# Source — a retrieved document/API response
# ---------------------------------------------------------------------------


class SourceRecord(BaseModel):
    source_id: str = Field(default_factory=lambda: new_id("src"))
    url: Optional[str] = None
    domain: Optional[str] = None
    source_type: str = SourceType.OTHER.value
    authority_tier: int = Field(default=4, ge=0, le=4)
    title: Optional[str] = None
    retrieved_at: Optional[str] = None
    published_at: Optional[str] = None
    http_status: Optional[int] = None
    content_hash: Optional[str] = None
    access_status: str = "unknown"  # success / failed / blocked / timeout / robots_denied
    error_detail: Optional[str] = None
    org_number: Optional[str] = None  # company this source was fetched for


# ---------------------------------------------------------------------------
# Evidence — a snippet within a source that supports a fact
# ---------------------------------------------------------------------------


class EvidenceRecord(BaseModel):
    evidence_id: str = Field(default_factory=lambda: new_id("ev"))
    source_id: str
    url: Optional[str] = None
    source_title: Optional[str] = None
    source_type: str = SourceType.OTHER.value
    authority_tier: int = 4
    retrieved_at: Optional[str] = None
    published_at: Optional[str] = None
    evidence_text: Optional[str] = None
    page_or_section: Optional[str] = None
    content_hash: Optional[str] = None
    entity_match_details: Dict[str, Any] = Field(default_factory=dict)
    entity_verdict: str = MatchVerdict.AMBIGUOUS.value
    org_number: Optional[str] = None


# ---------------------------------------------------------------------------
# Fact — an independently verifiable claim
# ---------------------------------------------------------------------------


class Fact(BaseModel):
    fact_id: str = Field(default_factory=lambda: new_id("fact"))
    org_number: str
    category: str  # CoverageCategory value or specific field category
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
    entity_verdict: str = MatchVerdict.AMBIGUOUS.value
    fact_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: str = FactStatus.DISCOVERED.value
    conflict_note: Optional[str] = None
    run_id: Optional[str] = None

    def fact_key(self) -> str:
        """Identity of the fact slot for change detection."""
        return f"{self.category}|{self.field}|{self.reporting_period or ''}"


# ---------------------------------------------------------------------------
# Change record — fact-level diff between runs
# ---------------------------------------------------------------------------


class ChangeRecord(BaseModel):
    change_id: str = Field(default_factory=lambda: new_id("chg"))
    org_number: str
    run_id: str
    change_type: str  # NEW / CHANGED / RETRACTED / UNCHANGED / SOURCE_UNAVAILABLE
    field: str
    reporting_period: Optional[str] = None
    category: str
    previous_value: Optional[Any] = None
    current_value: Optional[Any] = None
    previous_source_id: Optional[str] = None
    current_source_id: Optional[str] = None
    detected_at: Optional[str] = None
    explanation: Optional[str] = None


# ---------------------------------------------------------------------------
# Trace events
# ---------------------------------------------------------------------------


class TraceEvent(BaseModel):
    timestamp: str
    stage: str
    message: str
    level: str = "info"
    details: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Research run
# ---------------------------------------------------------------------------


class RunState(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class ResearchRun(BaseModel):
    run_id: str = Field(default_factory=lambda: new_id("run"))
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    state: str = RunState.RUNNING.value
    request_count: int = 0
    estimated_cost_usd: float = 0.0
    companies: List[str] = Field(default_factory=list)
    company_states: Dict[str, str] = Field(default_factory=dict)  # orgnr -> terminal state
    requested_by: str = "cli"


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


class Coverage(BaseModel):
    states: Dict[str, str] = Field(
        default_factory=lambda: {c: CategoryState.NOT_FOUND.value for c in COVERAGE_CATEGORIES}
    )

    def set(self, category: str, state: str) -> None:
        self.states[category] = state

    def get(self, category: str) -> str:
        return self.states.get(category, CategoryState.NOT_FOUND.value)

    def found_count(self) -> int:
        return sum(1 for s in self.states.values() if s == CategoryState.FOUND.value)

    def researched_count(self) -> int:
        return sum(
            1 for s in self.states.values() if s in (CategoryState.FOUND.value, CategoryState.BLOCKED.value, CategoryState.NOT_AVAILABLE.value)
        )


# ---------------------------------------------------------------------------
# Final profile — derived from facts
# ---------------------------------------------------------------------------


class ResearchMetadata(BaseModel):
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_sec: Optional[float] = None
    request_count: int = 0
    request_budget: int = 2000
    estimated_cost_usd: float = 0.0
    cost_budget_usd: float = 10.0
    time_remaining_sec: Optional[float] = None
    stages_executed: List[str] = Field(default_factory=list)
    llm_calls: int = 0


class CompanyProfile(BaseModel):
    run_id: str
    organisation_number: str
    status: str = TerminalState.NOT_AVAILABLE.value
    company: Optional[CompanyIdentity] = None
    facts: List[Fact] = Field(default_factory=list)
    changes: List[ChangeRecord] = Field(default_factory=list)
    summary: Optional[str] = None
    unknowns: List[str] = Field(default_factory=list)
    sources: List[SourceRecord] = Field(default_factory=list)
    rejected_sources: List[Dict[str, Any]] = Field(default_factory=list)
    coverage: Dict[str, str] = Field(default_factory=dict)
    research_metadata: ResearchMetadata = Field(default_factory=ResearchMetadata)
    last_researched_at: Optional[str] = None
    previous_run_id: Optional[str] = None

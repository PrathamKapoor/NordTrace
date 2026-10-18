"""Domain models: Company, Fact, Evidence, Source, Changes, Coverage, Run.

The fact ledger is the source of truth: profiles are derived from facts,
never the other way around.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

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
    DUPLICATE = "DUPLICATE"
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
    return datetime.now(UTC).replace(microsecond=0)


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
    is_part_of_concern: Optional[bool] = None
    bankrupt: Optional[bool] = None
    under_liquidation: Optional[bool] = None
    deleted_date: Optional[str] = None
    last_verified_at: Optional[str] = None
    unresolved_fields: List[str] = Field(default_factory=list)

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
    snapshot_representation: Optional[str] = None
    access_status: str = "unknown"  # success / failed / blocked / timeout / robots_denied
    error_detail: Optional[str] = None
    org_number: Optional[str] = None  # company this source was fetched for
    requested_url: Optional[str] = None
    final_url: Optional[str] = None
    redirect_chain: List[str] = Field(default_factory=list)
    content_type: Optional[str] = None
    cache_hit: bool = False
    discovered_at: Optional[str] = None
    discovery_source_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Evidence — a snippet within a source that supports a fact
# ---------------------------------------------------------------------------


class JsonPointerLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["json_pointer"] = "json_pointer"
    pointer: str
    raw_value: Any
    normalization: Literal[
        "identity", "brreg-address-v1", "brreg-website-v1", "brreg-status-v1", "brreg-subunit-v1",
    ] = "identity"


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
    locator: Optional[JsonPointerLocator] = None


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
    item_key: Optional[str] = None
    subject_scope: Literal["legal_entity", "group", "branch", "brand", "unknown"] = "unknown"
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
        """Unambiguous logical identity; values and observation IDs are excluded."""
        return json.dumps([
            self.org_number, self.category, self.field, self.reporting_period or None,
            self.item_key or None, self.subject_scope,
        ], ensure_ascii=True, separators=(",", ":"))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def claim_id(self) -> str:
        return "claim_v1_" + content_hash(self.fact_key())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def observation_id(self) -> str:
        """fact_id is retained as the historical observation primary key."""
        return self.fact_id


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
    claim_id: Optional[str] = None
    item_key: Optional[str] = None
    subject_scope: str = "unknown"
    category: str
    previous_value: Optional[Any] = None
    current_value: Optional[Any] = None
    previous_source_id: Optional[str] = None
    current_source_id: Optional[str] = None
    previous_evidence_id: Optional[str] = None
    current_evidence_id: Optional[str] = None
    previous_observation_id: Optional[str] = None
    current_observation_id: Optional[str] = None
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
        default_factory=lambda: dict.fromkeys(COVERAGE_CATEGORIES, CategoryState.NOT_FOUND.value)
    )

    def set(self, category: str, state: str) -> None:
        self.states[category] = state

    def get(self, category: str) -> str:
        return self.states.get(category, CategoryState.NOT_FOUND.value)

    def found_count(self) -> int:
        return sum(1 for s in self.states.values() if s == CategoryState.FOUND.value)

    def researched_count(self) -> int:
        return sum(
            1
            for s in self.states.values()
            if s
            in (CategoryState.FOUND.value, CategoryState.BLOCKED.value, CategoryState.NOT_AVAILABLE.value)
        )


# ---------------------------------------------------------------------------
# Final profile — derived from facts
# ---------------------------------------------------------------------------


class RunConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    max_requests: int = Field(ge=0)
    max_runtime_sec: float = Field(gt=0)
    max_cost_usd: float = Field(ge=0)
    per_company_sec: float = Field(default=90, gt=0)
    finalization_reserve_sec: float = Field(default=0, ge=0)
    allowed_source_origins: Optional[List[str]] = None

    @field_validator("allowed_source_origins")
    @classmethod
    def validate_source_origins(cls, values: Optional[List[str]]) -> Optional[List[str]]:
        if values is None:
            return None  # Legacy configuration did not declare a source allowlist.
        normalized = []
        for value in values:
            parsed = urlsplit(value)
            if (any(ord(char) <= 32 or ord(char) >= 127 for char in value)
                    or parsed.scheme not in ("http", "https") or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
                raise ValueError("source policy requires bare HTTP(S) origins without credentials")
            port = parsed.port
            if port == 0:
                raise ValueError("source origin cannot use port zero")
            host = parsed.hostname.lower().rstrip(".")
            if ":" in host or not host:
                raise ValueError("source policy requires a hostname")
            suffix = f":{port}" if port and port != {"http": 80, "https": 443}[parsed.scheme] else ""
            normalized.append(f"{parsed.scheme}://{host}{suffix}")
        return list(dict.fromkeys(normalized))

    @model_validator(mode="after")
    def reserve_leaves_work_time(self) -> RunConfiguration:
        if self.finalization_reserve_sec >= self.max_runtime_sec:
            raise ValueError("finalization reserve must be smaller than run runtime")
        return self


class RunBudgetState(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    version: Literal[1] = 1
    configuration: RunConfiguration
    deadline_unix: float
    elapsed_floor_sec: float = Field(default=0, ge=0)
    last_seen_unix: float
    telemetry: Dict[str, Any] = Field(default_factory=dict)


class ResearchMetadata(BaseModel):
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_sec: Optional[float] = None
    request_count: int = 0
    request_budget: Optional[int] = None
    estimated_cost_usd: float = 0.0
    cost_budget_usd: Optional[float] = None
    time_remaining_sec: Optional[float] = None
    stages_executed: List[str] = Field(default_factory=list)
    llm_calls: int = 0
    run_configuration: Optional[RunConfiguration] = None


class ResearchError(BaseModel):
    code: str
    message: str
    stage: Optional[str] = None
    retryable: bool = False


class RefreshOutcome(BaseModel):
    """Current attempt state; transport success alone does not prove completeness."""

    requested_url: str
    family: str
    state: Literal["available", "not_available", "blocked", "not_applicable", "ambiguous", "failed"]
    source_id: Optional[str] = None
    completeness: Literal["complete", "partial", "unknown"] = "unknown"
    observed_at: str
    reason: str


class CompanyProfile(BaseModel):
    schema_version: str = "1.1"
    run_id: str
    organisation_number: str
    status: str = TerminalState.NOT_AVAILABLE.value
    status_reason: Optional[str] = Field(default=None, min_length=1)
    company: Optional[CompanyIdentity] = None
    facts: List[Fact] = Field(default_factory=list)
    conflicts: List[Fact] = Field(default_factory=list)
    last_known: List[Fact] = Field(default_factory=list)
    refresh_outcomes: List[RefreshOutcome] = Field(default_factory=list)
    changes: List[ChangeRecord] = Field(default_factory=list)
    summary: Optional[str] = None
    unknowns: List[str] = Field(default_factory=list)
    sources: List[SourceRecord] = Field(default_factory=list)
    evidence: List[EvidenceRecord] = Field(default_factory=list)
    errors: List[ResearchError] = Field(default_factory=list)
    refresh_metadata: Dict[str, Any] = Field(default_factory=dict)
    rejected_sources: List[Dict[str, Any]] = Field(default_factory=list)
    coverage: Dict[str, str] = Field(default_factory=dict)
    research_metadata: ResearchMetadata = Field(default_factory=ResearchMetadata)
    last_researched_at: Optional[str] = None
    previous_run_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_envelope(self) -> CompanyProfile:
        if self.schema_version != "1.1":
            raise ValueError("unsupported result schema_version")
        if self.status not in {state.value for state in TerminalState}:
            raise ValueError("invalid terminal status")
        if self.company and self.company.organisation_number != self.organisation_number:
            raise ValueError("identity belongs to another company")
        sources = {source.source_id: source for source in self.sources}
        evidence = {item.evidence_id: item for item in self.evidence}
        if len(sources) != len(self.sources) or len(evidence) != len(self.evidence):
            raise ValueError("duplicate source or evidence IDs")
        if any(fact.status != FactStatus.CONFLICT.value for fact in self.conflicts):
            raise ValueError("conflict observations must carry CONFLICT status")
        if any(fact.status != FactStatus.SOURCE_UNAVAILABLE.value for fact in self.last_known):
            raise ValueError("last-known observations must carry SOURCE_UNAVAILABLE status")
        if {fact.claim_id for fact in self.facts} & {fact.claim_id for fact in self.last_known}:
            raise ValueError("current claim cannot also be last-known")
        if {fact.claim_id for fact in self.facts} & {fact.claim_id for fact in self.conflicts}:
            raise ValueError("conflicting claim cannot also be published")
        if len({fact.fact_id for fact in self.facts + self.conflicts}) != len(self.facts + self.conflicts):
            raise ValueError("duplicate observation IDs in result")
        for fact in self.facts + self.conflicts + self.last_known:
            source = sources.get(fact.source_id)
            support = evidence.get(fact.evidence_id)
            if fact.org_number != self.organisation_number:
                raise ValueError("claim belongs to another company")
            if source is None or support is None or support.source_id != fact.source_id:
                raise ValueError("claim has dangling source/evidence reference")
            if source.org_number and source.org_number != self.organisation_number:
                raise ValueError("source belongs to another company")
            if support.org_number and support.org_number != self.organisation_number:
                raise ValueError("evidence belongs to another company")
        if any(fact.status != FactStatus.PUBLISHED.value for fact in self.facts):
            raise ValueError("published facts must carry PUBLISHED status")
        return self

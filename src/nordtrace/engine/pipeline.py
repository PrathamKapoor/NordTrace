"""Research pipeline: identity → registry → financials → website → jobs →
activity → coverage-driven top-ups → synthesis → profile.

Adaptive: stops early when coverage suffices; consults budgets before every
expensive stage; records a trace event per step; every company gets exactly
one terminal state.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from nordtrace.adapters.activity import ActivityAdapter
from nordtrace.adapters.brreg import BrregAdapter
from nordtrace.adapters.nav_jobs import NavJobsAdapter
from nordtrace.adapters.pdf_pipeline import PdfFinancialPipeline
from nordtrace.adapters.website import WebsiteAdapter
from nordtrace.core.request_gateway import RequestGateway
from nordtrace.core.budget import BudgetManager
from nordtrace.core.changes import detect_changes
from nordtrace.core.config import settings
from nordtrace.core.entity import EntityResolver, PublicationFirewall
from nordtrace.core.ledger import FactLedger
from nordtrace.core.llm import LLMClient
from nordtrace.core.models import (
    ChangeRecord,
    CompanyIdentity,
    CompanyProfile,
    Coverage,
    EvidenceRecord,
    Fact,
    FactStatus,
    MatchVerdict,
    ResearchMetadata,
    ResearchRun,
    SourceRecord,
    SourceType,
    TerminalState,
    TraceEvent,
    utcnow,
)
from nordtrace.core.repository import Repository
from nordtrace.core.synthesis import build_summary
from nordtrace.core.orgnr import validate_orgnr

logger = logging.getLogger("nordtrace.pipeline")


@dataclass
class CompanyOutcome:
    org_number: str
    terminal_state: str
    identity: Optional[CompanyIdentity] = None
    facts: List[Fact] = field(default_factory=list)
    evidence: List[EvidenceRecord] = field(default_factory=list)
    sources: List[SourceRecord] = field(default_factory=list)
    rejected: List[Dict] = field(default_factory=list)
    changes: List[ChangeRecord] = field(default_factory=list)
    summary: Optional[str] = None
    unknowns: List[str] = field(default_factory=list)
    coverage: Dict[str, str] = field(default_factory=dict)
    stages: List[str] = field(default_factory=list)
    error: Optional[str] = None


class ResearchPipeline:
    """One company research run."""

    def __init__(self, repo: Repository, budget: BudgetManager):
        self.repo = repo
        self.budget = budget
        self.gateway = RequestGateway(budget)
        self.resolver = EntityResolver()
        self.firewall = PublicationFirewall(self.resolver)
        self.brreg = BrregAdapter(self.gateway, budget)
        self.website = WebsiteAdapter(self.gateway, budget, self.resolver)
        self.jobs = NavJobsAdapter(self.gateway, budget, self.resolver)
        self.pdf = PdfFinancialPipeline(self.gateway, budget, self.resolver)
        self.activity = ActivityAdapter(self.gateway, budget)
        self.llm = LLMClient(budget)

    async def aclose(self) -> None:
        await self.gateway.aclose()
        await self.llm.aclose()

    # ------------------------------------------------------------------ trace
    def _trace(self, run_id: str, org: str, stage: str, message: str, level: str = "info") -> None:
        ev = TraceEvent(timestamp=utcnow().isoformat(), stage=stage, message=message, level=level)
        self.repo.add_trace(run_id, ev, org)

    # ------------------------------------------------------------------ main
    async def research_company(self, org_number: str, run_id: str) -> CompanyOutcome:
        started = time.monotonic()
        outcome = CompanyOutcome(org_number=org_number, terminal_state=TerminalState.FAILED.value)
        ledger = FactLedger()
        stages: List[str] = []
        registry_payload: Optional[dict] = None
        financials_status = 'unknown'

        try:
            # 0. validate orgnr format (registry checks registration separately)
            check = validate_orgnr(org_number)
            if not check.valid:
                outcome.terminal_state = TerminalState.NOT_APPLICABLE.value
                outcome.error = f"invalid organisation number: {check.reason}"
                self._trace(run_id, org_number, "validation", f"rejected: {check.reason}", "error")
                return outcome
            stages.append("validation")
            self._trace(run_id, org_number, "validation", f"organisation number accepted ({org_number})")

            # 1. canonical identity from registry
            ident, src, ev, hint = await self.brreg.fetch_entity(org_number, run_id)
            if src:
                ledger.add_source(src)
            if ev:
                ledger.add_evidence(ev)
            stages.append("identity")
            if hint != "found" or ident is None:
                self._trace(run_id, org_number, "identity", f"registry lookup failed: {hint}", "error")
                state = TerminalState.NOT_AVAILABLE.value if hint == "not_found" else (
                    TerminalState.BLOCKED.value if hint == "blocked" else TerminalState.FAILED.value)
                outcome.terminal_state = state
                outcome.sources = list(ledger.sources.values())
                outcome.error = f"registry lookup: {hint}"
                return outcome
            outcome.identity = ident
            # registry identity facts
            for fname, fval in (
                ("legal_name", ident.legal_name),
                ("organisation_form", ident.organisation_form),
                ("status", ident.status),
                ("registered_address", ident.registered_address),
                ("municipality", ident.municipality),
                ("industry_code", ident.industry_code),
                ("industry_description", ident.industry_description),
                ("website", ident.website),
                ("registration_date", ident.registration_date),
                ("employee_count", ident.employee_count),
            ):
                if fval in (None, "", "unknown"):
                    continue
                f = Fact(
                    org_number=org_number, run_id=run_id, category="identity", field=fname,
                    value=fval, normalized_value=str(fval), source_id=src.source_id,
                    evidence_id=ev.evidence_id, retrieved_at=utcnow().isoformat(),
                    entity_verdict=MatchVerdict.VERIFIED.value, fact_confidence=0.99,
                    status=FactStatus.PUBLISHED.value, published_at=utcnow().isoformat(),
                )
                ledger.add_fact(f, ev, src)
            self._trace(run_id, org_number, "identity", f"registry identity resolved: {ident.legal_name}")
            self.repo.upsert_company(ident, run_id)

            # 2. roles (leadership)
            if self.budget.can_make_request():
                rev_evs, role_facts, rsrc = await self.brreg.fetch_roles(org_number, run_id)
                if rsrc:
                    ledger.add_source(rsrc)
                for e in rev_evs:
                    ledger.add_evidence(e)
                for f in role_facts:
                    ledger.add_fact(f, None, rsrc)
                stages.append("roles")
                self._trace(run_id, org_number, "roles", f"{len(role_facts)} roles extracted")

            # 3. financials from registry accounts
            if self.budget.can_make_request():
                aev, afacts, asrc, astatus = await self.brreg.fetch_accounts(org_number, run_id)
                if asrc:
                    ledger.add_source(asrc)
                for e in aev:
                    ledger.add_evidence(e)
                for f in afacts:
                    ledger.add_fact(f, None, asrc)
                stages.append("financials")
                financials_status = astatus
                self._trace(run_id, org_number, "financials",
                            f"registry accounts: {astatus}, {len(afacts)} facts")
                # capture registry payload for activity adapter
                if asrc and asrc.access_status == "success":
                    import json
                    cached = self.gateway.get_content(asrc.url)
                    try:
                        payload = json.loads(cached.text if cached else "")
                        registry_payload = payload[0] if isinstance(payload, list) and payload else payload
                    except ValueError:
                        registry_payload = None

            # 4. website discovery + crawl
            if self.budget.can_make_request() and ident.website:
                w_evs, w_facts, w_sources, w_rejected, w_cov = await self.website.crawl(ident, run_id)
                for s in w_sources:
                    ledger.add_source(s)
                for e in w_evs:
                    ledger.add_evidence(e)
                for f in w_facts:
                    ledger.add_fact(f, None, None)
                for r in w_rejected:
                    r2 = dict(r)
                    r2["url"] = r.get("url")
                    outcome.rejected.append(r2)
                stages.append("website")
                self._trace(run_id, org_number, "website",
                            f"crawl complete: {len(w_sources)} sources, {len(w_facts)} facts, "
                            f"{len(w_rejected)} rejected")
            elif not ident.website:
                outcome.rejected.append({"url": None, "reason": "no website registered in registry"})

            # 5. jobs (NAV)
            if self.budget.can_make_request():
                j_evs, j_facts, j_src, j_rejected = await self.jobs.fetch_jobs(ident, run_id)
                if j_src:
                    ledger.add_source(j_src)
                for e in j_evs:
                    ledger.add_evidence(e)
                for f in j_facts:
                    ledger.add_fact(f, None, None)
                for r in j_rejected:
                    outcome.rejected.append(r)
                stages.append("jobs")
                self._trace(run_id, org_number, "jobs",
                            f"{len(j_facts)} jobs verified, {len(j_rejected)} rejected")

            # 6. activity from registry signals
            if registry_payload is not None and src:
                act_evs, act_facts = self.activity.extract_activity(ident, registry_payload, src, run_id)
                for e in act_evs:
                    ledger.add_evidence(e)
                for f in act_facts:
                    ledger.add_fact(f, None, None)
                stages.append("activity")
                self._trace(run_id, org_number, "activity", f"{len(act_facts)} registry activity events")

            # 7. change detection vs previous run
            prev_facts = self.repo.get_previous_facts(org_number, exclude_run_id=run_id)
            current_facts = ledger.published_facts(org_number)
            changes = detect_changes(org_number, run_id, prev_facts, current_facts)
            if changes:
                self.repo.insert_changes(changes)
                stages.append("changes")
                n_changed = sum(1 for c in changes if c.change_type in ("CHANGED", "NEW"))
                self._trace(run_id, org_number, "changes",
                            f"change detection: {n_changed} new/changed, "
                            f"{len(changes) - n_changed} unchanged/retracted")
            outcome.changes = changes

            # 8. persist ledger + coverage (order: sources → evidence → facts)
            for s in ledger.sources.values():
                s.org_number = org_number
            self.repo.insert_sources_bulk(list(ledger.sources.values()), run_id, org_number)
            all_ev = list(ledger.evidence.values())
            # only evidence whose source was persisted
            persisted_ids = {s.source_id for s in ledger.sources.values()}
            all_ev = [e for e in all_ev if e.source_id in persisted_ids]
            if all_ev:
                self.repo.insert_evidence_bulk(all_ev)
            all_facts = [e.fact for e in ledger.all_entries()]
            # only facts whose source+evidence were persisted (skips FAILED w/ dangling ev)
            persisted_ev = {e.evidence_id for e in all_ev}
            all_facts = [f for f in all_facts if f.source_id in persisted_ids and f.evidence_id in persisted_ev]
            if all_facts:
                self.repo.insert_facts_bulk(all_facts)

            coverage = self._coverage_from(ledger, org_number, financials_status)
            outcome.coverage = coverage.states
            outcome.facts = current_facts
            outcome.evidence = all_ev
            outcome.sources = list(ledger.sources.values())

            # 9. terminal state from coverage
            outcome.terminal_state = self._terminal_state(coverage, ident)
            # 10. synthesis (deterministic; LLM optional)
            outcome.summary = build_summary(ident, ledger, coverage, outcome.changes)
            outcome.unknowns = self._unknowns(coverage)
            stages.append("synthesis")
            self._trace(run_id, org_number, "synthesis",
                        f"profile completed: {outcome.terminal_state}, "
                        f"{len(current_facts)} published facts")

        except Exception as e:
            logger.exception("pipeline error for %s", org_number)
            outcome.terminal_state = TerminalState.FAILED.value
            outcome.error = f"{type(e).__name__}: {e}"
            self._trace(run_id, org_number, "error", str(e)[:300], "error")
        finally:
            outcome.stages = stages
            outcome.duration_sec = time.monotonic() - started  # type: ignore
        return outcome

    # ------------------------------------------------------------------ helpers
    def _coverage_from(self, ledger: FactLedger, org_number: str, accounts_status: str) -> Coverage:
        cov = Coverage()
        ident = None
        # identity
        if any(f.category == "identity" for f in ledger.published_facts(org_number)):
            cov.set("identity", "found")
        if any(f.category == "business_description" for f in ledger.published_facts(org_number)):
            cov.set("business_description", "found")
        if any(f.field in ("industry_code", "industry_description") for f in ledger.published_facts(org_number)):
            cov.set("industry", "found")
        fin = [f for f in ledger.published_facts(org_number) if f.category == "financials"]
        if fin:
            cov.set("financials", "found")
        elif accounts_status == "not_found":
            cov.set("financials", "not_available")
        elif accounts_status in ("failed", "blocked"):
            cov.set("financials", "blocked")
        if any(f.category == "leadership" for f in ledger.published_facts(org_number)):
            cov.set("leadership", "found")
        if any(f.category == "locations" for f in ledger.published_facts(org_number)):
            cov.set("locations", "found")
        if any(f.category == "products_services" for f in ledger.published_facts(org_number)):
            cov.set("products_services", "found")
        jobs = [f for f in ledger.published_facts(org_number) if f.category == "jobs"]
        if jobs:
            cov.set("jobs", "found")
        if any(f.category == "recent_activity" for f in ledger.published_facts(org_number)):
            cov.set("recent_activity", "found")
        return cov

    def _terminal_state(self, coverage: Coverage, ident: Optional[CompanyIdentity]) -> str:
        if ident is None:
            return TerminalState.NOT_AVAILABLE.value
        if ident.status == "deleted":
            return TerminalState.NOT_APPLICABLE.value
        found = coverage.found_count()
        if found >= 3:
            return TerminalState.AVAILABLE.value
        if found >= 1:
            return TerminalState.NOT_AVAILABLE.value  # identity + little else
        return TerminalState.NOT_AVAILABLE.value

    def _unknowns(self, coverage: Coverage) -> List[str]:
        labels = {
            "financials": "Annual accounts (not publicly available via permitted sources)",
            "leadership": "Board/management roles (registry roles unavailable)",
            "products_services": "Products/services (website sections unavailable)",
            "jobs": "Job postings (none found on public job boards)",
            "recent_activity": "Recent public activity (no dated events found)",
            "business_description": "Business description (website unavailable)",
        }
        out = []
        for cat, label in labels.items():
            if coverage.get(cat) in ("not_available", "not_found", "blocked"):
                out.append(label)
        return out

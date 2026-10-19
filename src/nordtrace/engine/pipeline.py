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
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from nordtrace.adapters.activity import ActivityAdapter
from nordtrace.adapters.brreg import BrregAdapter
from nordtrace.adapters.nav_jobs import NavJobsAdapter
from nordtrace.adapters.pdf_pipeline import PdfFinancialPipeline
from nordtrace.adapters.website import WebsiteAdapter
from nordtrace.core.budget import BudgetExceededError, BudgetManager, DeadlineReachedError
from nordtrace.core.contracts import build_result, project_identity
from nordtrace.core.entity import EntityResolver, PublicationFirewall
from nordtrace.core.ledger import FactLedger
from nordtrace.core.models import (
    ChangeRecord,
    CompanyIdentity,
    Coverage,
    EvidenceRecord,
    Fact,
    FactStatus,
    RefreshOutcome,
    SourceRecord,
    SourceType,
    TerminalState,
    TraceEvent,
    utcnow,
)
from nordtrace.core.orgnr import validate_orgnr
from nordtrace.core.refresh import apply_refresh, stale_notice
from nordtrace.core.repository import Repository
from nordtrace.core.request_gateway import RequestGateway
from nordtrace.core.synthesis import build_summary, unknowns_for_coverage

logger = logging.getLogger("nordtrace.pipeline")
_acquisition_deadline: ContextVar[Optional[tuple[asyncio.Timeout, str]]] = ContextVar(
    "acquisition_deadline", default=None,
)


@dataclass
class CompanyOutcome:
    org_number: str
    terminal_state: str
    status_reason: Optional[str] = None
    identity: Optional[CompanyIdentity] = None
    facts: List[Fact] = field(default_factory=list)
    observations: List[Fact] = field(default_factory=list)
    conflicts: List[Fact] = field(default_factory=list)
    last_known: List[Fact] = field(default_factory=list)
    refresh_outcomes: List[RefreshOutcome] = field(default_factory=list)
    previous_run_id: Optional[str] = None
    evidence: List[EvidenceRecord] = field(default_factory=list)
    sources: List[SourceRecord] = field(default_factory=list)
    rejected: List[Dict] = field(default_factory=list)
    changes: List[ChangeRecord] = field(default_factory=list)
    summary: Optional[str] = None
    unknowns: List[str] = field(default_factory=list)
    coverage: Dict[str, str] = field(default_factory=dict)
    stages: List[str] = field(default_factory=list)
    error: Optional[str] = None
    error_code: Optional[str] = None


class ResearchPipeline:
    """One company research run."""

    def __init__(self, repo: Repository, budget: BudgetManager):
        self.repo = repo
        self.worker_owner: Optional[str] = None
        self.budget = budget
        self.gateway = RequestGateway(budget, repository=repo)
        self.resolver = EntityResolver()
        self.firewall = PublicationFirewall(self.resolver)
        self.brreg = BrregAdapter(self.gateway, budget)
        self.website = WebsiteAdapter(self.gateway, budget, self.resolver)
        self.jobs = NavJobsAdapter(self.gateway, budget, self.resolver)
        self.pdf = PdfFinancialPipeline(self.gateway, budget, self.resolver)
        self.activity = ActivityAdapter(self.gateway, budget)

    async def aclose(self) -> None:
        await self.gateway.aclose()

    # ------------------------------------------------------------------ trace
    def _trace(self, run_id: str, org: str, stage: str, message: str, level: str = "info") -> None:
        ev = TraceEvent(timestamp=utcnow().isoformat(), stage=stage, message=message, level=level)
        self.repo.add_trace(run_id, ev, org)

    # ------------------------------------------------------------------ main
    async def research_company(self, org_number: str, run_id: str) -> CompanyOutcome:
        previous = self.repo.get_result(run_id, org_number)
        if previous:
            return CompanyOutcome(
                org_number=org_number, terminal_state=previous.status, status_reason=previous.status_reason,
                identity=previous.company,
                facts=previous.facts, conflicts=previous.conflicts,
                last_known=previous.last_known, refresh_outcomes=previous.refresh_outcomes,
                previous_run_id=previous.previous_run_id,
                evidence=previous.evidence, sources=previous.sources,
                rejected=previous.rejected_sources, changes=previous.changes, summary=previous.summary,
                unknowns=previous.unknowns, coverage=previous.coverage,
                stages=previous.research_metadata.stages_executed,
                error=previous.errors[0].message if previous.errors else None,
                error_code=previous.errors[0].code if previous.errors else None,
            )
        remaining = self.budget.work_time_remaining()
        deadline_code = ("company_deadline_exceeded" if self.budget.configuration.per_company_sec < remaining
                         else "deadline_exceeded")
        deadline = asyncio.timeout(min(self.budget.configuration.per_company_sec, remaining))
        token = _acquisition_deadline.set((deadline, deadline_code))
        try:
            async with deadline:
                outcome = await self._research_company(org_number, run_id)
        except TimeoutError:
            if not deadline.expired():
                raise
            # Cancellation finalization retains the real partial ledger before
            # asyncio converts its cancellation into TimeoutError.
            if self.repo.get_result(run_id, org_number):
                return await self.research_company(org_number, run_id)
            outcome = CompanyOutcome(
                org_number=org_number, terminal_state="failed", error_code=deadline_code,
                error="Research acquisition deadline reached.",
            )
        finally:
            _acquisition_deadline.reset(token)
        self._persist_result(outcome, run_id)
        return outcome

    def _persist_result(self, outcome: CompanyOutcome, run_id: str) -> None:
        outcome.identity = project_identity(outcome.identity, outcome.conflicts, outcome.facts)
        run = self.repo.get_run(run_id)
        self.repo.publish_result(build_result(
            outcome, run_id, self.budget, run.started_at if run and run.started_at else utcnow().isoformat()
        ), observations=outcome.observations, owner=self.worker_owner)

    async def _research_company(self, org_number: str, run_id: str) -> CompanyOutcome:
        started = time.monotonic()
        outcome = CompanyOutcome(org_number=org_number, terminal_state=TerminalState.FAILED.value)
        ledger = FactLedger(repository=self.repo)
        stages: List[str] = []
        financials_status = "unknown"
        cancelled = False
        budget_skipped: List[str] = []

        def acquisition_allowed(stage: str) -> bool:
            if self.budget.can_make_request():
                return True
            budget_skipped.append(stage)
            return False

        try:
            # 0. validate orgnr format (registry checks registration separately)
            check = validate_orgnr(org_number)
            if not check.valid:
                outcome.terminal_state = TerminalState.NOT_APPLICABLE.value
                outcome.error = f"invalid organisation number: {check.reason}"
                outcome.error_code = "invalid_organisation_number"
                self._trace(run_id, org_number, "validation", f"rejected: {check.reason}", "error")
                return outcome
            stages.append("validation")
            self._trace(run_id, org_number, "validation", f"organisation number accepted ({org_number})")

            # 1. canonical identity from registry
            self.budget.check()
            ident, src, ev, hint = await self.brreg.fetch_entity(org_number, run_id)
            stages.append("identity")
            if hint != "found" or ident is None or src is None or ev is None:
                self._trace(run_id, org_number, "identity", f"registry lookup failed: {hint}", "error")
                state = (
                    TerminalState.NOT_AVAILABLE.value
                    if hint == "not_found"
                    else (TerminalState.BLOCKED.value if hint == "blocked" else TerminalState.FAILED.value)
                )
                if hint == "ambiguous":
                    state = TerminalState.AMBIGUOUS.value
                outcome.terminal_state = state
                outcome.sources = [src] if src else []
                outcome.error = f"registry lookup: {hint}"
                outcome.error_code = {
                    "not_found": "entity_not_found", "blocked": "registry_blocked",
                    "ambiguous": "entity_ambiguous",
                }.get(hint, "registry_failed")
                if src is not None:
                    outcome.refresh_outcomes.append(RefreshOutcome.model_validate({
                        "requested_url": src.requested_url or src.url or "", "source_id": src.source_id,
                        "family": "identity", "state": state, "observed_at": utcnow().isoformat(),
                        "reason": src.error_detail or outcome.error,
                    }))
                return outcome
            outcome.identity = ident
            # src/ev are non-None here (guaranteed by the early return above)
            assert src is not None and ev is not None
            # Atomic registry fields have schema-qualified snapshot pointers.
            identity_evidence, identity_facts = self.brreg.identity_claims(ident, src, run_id)
            ledger.add_source(src)
            for item in identity_evidence:
                ledger.add_evidence(item)
            for fact in identity_facts:
                ledger.add_fact(fact)
            self._trace(run_id, org_number, "identity", f"registry identity resolved: {ident.legal_name}")
            # Registered subunits are relationships, not separate target legal identities.
            if acquisition_allowed("branches"):
                branches = await self.brreg.fetch_underenheter(org_number, run_id)
                for source in branches.sources:
                    ledger.add_source(source)
                for item in branches.evidence:
                    ledger.add_evidence(item)
                for fact in branches.facts:
                    ledger.add_fact(fact)
                completeness, reason = branches.completeness, branches.reason
                if any(fact.status != FactStatus.PUBLISHED.value for fact in branches.facts):
                    completeness = "partial"
                    reason = "Some subunit observations failed publication or conflict validation."
                for source in branches.sources:
                    page_state = branches.page_states[source.source_id]
                    if any(fact.status != FactStatus.PUBLISHED.value for fact in branches.facts
                           if fact.source_id == source.source_id):
                        page_state = "ambiguous"
                    outcome.refresh_outcomes.append(RefreshOutcome.model_validate({
                        "requested_url": source.requested_url or source.url or "", "family": "locations",
                        "source_id": source.source_id, "state": page_state, "completeness": completeness,
                        "observed_at": utcnow().isoformat(), "reason": reason,
                    }))
                outcome.rejected.extend(branches.rejected)
                stages.append("branches")
                self._trace(run_id, org_number, "branches", reason)

            # 2. roles (leadership)
            if acquisition_allowed("roles"):
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
            if acquisition_allowed("financials"):
                aev, afacts, asrc, astatus = await self.brreg.fetch_accounts(org_number, run_id)
                if asrc:
                    ledger.add_source(asrc)
                for e in aev:
                    ledger.add_evidence(e)
                for f in afacts:
                    ledger.add_fact(f, None, asrc)
                if asrc:
                    financial_state = {
                        "not_found": "not_available", "not_available": "not_available",
                        "ambiguous": "ambiguous", "failed": "failed", "blocked": "blocked",
                        "not_applicable": "not_applicable",
                    }.get(astatus, "failed")
                    reason = asrc.error_detail or f"Accounts extraction state: {astatus}."
                    if astatus == "found":
                        financial_state = (
                            "available" if any(f.category == "financials"
                                               and f.status == FactStatus.PUBLISHED.value for f in afacts)
                            else "ambiguous"
                        )
                        if financial_state == "ambiguous":
                            reason = ("Accounting candidates lack validated unit/scale "
                                      "and financial value support.")
                    outcome.refresh_outcomes.append(RefreshOutcome.model_validate({
                        "requested_url": asrc.requested_url or asrc.url or "", "source_id": asrc.source_id,
                        "family": "financials", "state": financial_state, "observed_at": utcnow().isoformat(),
                        "reason": reason,
                    }))
                stages.append("financials")
                financials_status = astatus
                self._trace(
                    run_id, org_number, "financials", f"registry accounts: {astatus}, {len(afacts)} facts"
                )
            # 4. website discovery + crawl (registry hjemmeside or name-derived candidates)
            if acquisition_allowed("website"):
                w_evs, w_facts, w_sources, w_rejected, w_cov = await self.website.crawl(
                    ident, run_id, identity_source_id=src.source_id,
                )
                for s in w_sources:
                    ledger.add_source(s)
                for e in w_evs:
                    ledger.add_evidence(e)
                for f in w_facts:
                    ledger.add_fact(f, None, None)
                for r in w_rejected:
                    if r.get("code") == "acquisition_budget_limited":
                        budget_skipped.append("website")
                    r2 = dict(r)
                    r2["url"] = r.get("url")
                    outcome.rejected.append(r2)
                stages.append("website")
                self._trace(
                    run_id,
                    org_number,
                    "website",
                    f"crawl complete: {len(w_sources)} sources, {len(w_facts)} facts, "
                    f"{len(w_rejected)} rejected",
                )
            else:
                outcome.rejected.append(
                    {"url": None, "reason": "request budget exhausted before website stage"}
                )

            # 5. NAV is locally policy-blocked until its feed contract is implemented.
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
            self._trace(
                run_id, org_number, "jobs", f"{len(j_facts)} jobs verified, {len(j_rejected)} rejected"
            )

            # 5b. Financial fallback uses documents discovered by the one website pass.
            # Check for actual eligible work before recording any budget skip.
            pdf_sources = [
                source for source in ledger.sources.values()
                if source.source_type == SourceType.COMPANY_DOCUMENT.value and source.url
            ][:2]
            if (
                pdf_sources
                and financials_status != "not_applicable"
                and not any(f.category == "financials" for f in ledger.published_facts(org_number))
                and self.budget.runtime.should_start_expensive_operation(20)
                and acquisition_allowed("adaptive_financials")
                and self.budget.runtime.should_start_expensive_operation(15)
            ):
                pdf_facts: list = []
                for pdf_src in pdf_sources:
                    assert pdf_src.url is not None
                    evs2, f2, src2, st2 = await self.pdf.process_pdf(ident, pdf_src.url, run_id)
                    ledger.add_source(src2)
                    for e in evs2:
                        ledger.add_evidence(e)
                    for f in f2:
                        ledger.add_fact(f, None, None)
                    pdf_facts.extend(f2)
                    pdf_state = {
                        "not_found": "not_available", "not_available": "not_available",
                        "ambiguous": "ambiguous", "failed": "failed", "blocked": "blocked",
                        "not_applicable": "not_applicable",
                    }.get(st2, "failed")
                    if st2 == "found":
                        pdf_state = ("available" if any(f.status == FactStatus.PUBLISHED.value for f in f2)
                                     else "ambiguous")
                    outcome.refresh_outcomes.append(RefreshOutcome.model_validate({
                        "requested_url": src2.requested_url or src2.url or "", "source_id": src2.source_id,
                        "family": "financials", "state": pdf_state, "observed_at": utcnow().isoformat(),
                        "reason": src2.error_detail or f"PDF extraction/support state: {pdf_state}.",
                    }))
                    # Preserve useful unresolved observations before acquisition
                    # failures; a failed source never proves financial absence.
                    precedence = {"not_found": 0, "not_available": 0, "blocked": 1,
                                  "failed": 2, "ambiguous": 3, "found": 3}
                    if (pdf_state in ("ambiguous", "failed", "blocked")
                            and precedence[pdf_state] > precedence.get(financials_status, 0)):
                        financials_status = pdf_state
                    self._trace(run_id, org_number, "adaptive_financials",
                                f"PDF completed with {pdf_state}; {len(f2)} claim candidates.")
                accepted_pdf = [f for f in pdf_facts if f.status == FactStatus.PUBLISHED.value]
                if accepted_pdf:
                    financials_status = "found"
                    stages.append("adaptive_financials")
                    self._trace(
                        run_id, org_number, "adaptive_financials",
                        f"PDF financial extraction: {len(accepted_pdf)} published facts",
                    )

            # 6. activity from registry signals
            if src:
                act_evs, act_facts = self.activity.extract_activity(ident, src, run_id)
                for e in act_evs:
                    ledger.add_evidence(e)
                for f in act_facts:
                    ledger.add_fact(f, None, None)
                stages.append("activity")
                self._trace(run_id, org_number, "activity", f"{len(act_facts)} registry activity events")

            # 7. changes are compared against canonical supported history in finalization.
            current_facts = ledger.published_facts(org_number)

            # 8. derive coverage; ledger persistence runs for success and failure below.
            coverage = self._coverage_from(ledger, org_number, financials_status)
            outcome.coverage = coverage.states
            outcome.facts = current_facts
            outcome.conflicts = ledger.conflicting_facts(org_number)

            # Exact registry resolution completed. Coverage is a separate axis;
            # neither sparse external information nor deletion means inapplicability.
            outcome.terminal_state = TerminalState.AVAILABLE.value
            outcome.status_reason = "research_completed"
            if outcome.conflicts:
                outcome.terminal_state = TerminalState.AMBIGUOUS.value
                outcome.status_reason = "conflicting_supported_observations"
            if budget_skipped:
                outcome.terminal_state = TerminalState.FAILED.value
                outcome.error_code = (
                    "deadline_exceeded" if self.budget.work_time_remaining() <= 0
                    else "request_budget_exhausted" if self.budget.requests.remaining() <= 0
                    else "acquisition_budget_limited"
                )
                outcome.status_reason = outcome.error_code
                outcome.error = (
                    "Run limit prevented acquisition stages: " + ", ".join(dict.fromkeys(budget_skipped))
                )
            # 10. synthesis (deterministic; LLM optional)
            stages.append("synthesis")
            self._trace(
                run_id,
                org_number,
                "synthesis",
                f"profile completed: {outcome.terminal_state}, {len(current_facts)} published facts",
            )

        except asyncio.CancelledError as cancellation:
            cancelled = True
            outcome.terminal_state = TerminalState.FAILED.value
            active_deadline = _acquisition_deadline.get()
            outcome.error_code = (active_deadline[1] if active_deadline and active_deadline[0].expired()
                                  else "research_cancelled")
            if cancellation.args and cancellation.args[0] in {
                "deadline_exceeded", "company_deadline_exceeded", "research_cancelled",
            }:
                outcome.error_code = cancellation.args[0]
            outcome.status_reason = outcome.error_code
            outcome.error = "Research interrupted; previously supported observations were retained."
            raise
        except (BudgetExceededError, DeadlineReachedError) as error:
            outcome.terminal_state = TerminalState.FAILED.value
            outcome.status_reason = outcome.error_code = (
                "deadline_exceeded" if isinstance(error, DeadlineReachedError) else "request_budget_exhausted"
            )
            outcome.error = str(error)
        except Exception as e:
            logger.exception("pipeline error for %s", org_number)
            outcome.terminal_state = TerminalState.FAILED.value
            outcome.status_reason = outcome.error_code = "research_failed"
            outcome.error = f"{type(e).__name__}: {e}"
            self._trace(run_id, org_number, "error", str(e)[:300], "error")
        finally:
            try:
                if ledger.sources:
                    self._finalize_ledger(outcome, ledger, run_id, financials_status)
                apply_refresh(self.repo, outcome, run_id)
                outcome.unknowns = list(dict.fromkeys([
                    *unknowns_for_coverage(Coverage(states=outcome.coverage)), *outcome.unknowns,
                ]))
                if outcome.conflicts:
                    outcome.unknowns.append(
                        "Conflicting supported observations were withheld; inspect their evidence."
                    )
                if outcome.changes:
                    stages.append("changes")
                if outcome.identity is not None:
                    outcome.summary = build_summary(
                        outcome.identity, ledger, Coverage(states=outcome.coverage), outcome.changes,
                        previous_run_id=outcome.previous_run_id,
                    )
                notice = stale_notice(outcome)
                if notice:
                    outcome.summary = " ".join(filter(None, [outcome.summary, notice]))
                outcome.stages = stages
                outcome.duration_sec = time.monotonic() - started  # type: ignore
                if cancelled:
                    self._persist_result(outcome, run_id)
            except Exception:
                if not cancelled:
                    raise
                logger.exception("could not retain interrupted pipeline result for %s", org_number)
        return outcome

    # ------------------------------------------------------------------ helpers
    def _finalize_ledger(
        self, outcome: CompanyOutcome, ledger: FactLedger, run_id: str, accounts_status: str,
    ) -> None:
        """Retain accepted and conflicting observations even after an adapter failure."""
        org = outcome.org_number
        sources = list(ledger.sources.values())
        for source in sources:
            source.org_number = org
        source_ids = {source.source_id for source in sources}
        evidence = [item for item in ledger.evidence.values() if item.source_id in source_ids]
        evidence_ids = {item.evidence_id for item in evidence}
        facts = [entry.fact for entry in ledger.all_entries()
                 if entry.fact.source_id in source_ids and entry.fact.evidence_id in evidence_ids]
        outcome.observations = facts
        outcome.facts = ledger.published_facts(org)
        outcome.conflicts = ledger.conflicting_facts(org)
        outcome.evidence = evidence
        outcome.sources = sources
        outcome.coverage = self._coverage_from(ledger, org, accounts_status).states

    def _coverage_from(self, ledger: FactLedger, org_number: str, accounts_status: str) -> Coverage:
        cov = Coverage()
        # identity
        if any(f.category == "identity" for f in ledger.published_facts(org_number)):
            cov.set("identity", "found")
        if any(f.category == "business_description" for f in ledger.published_facts(org_number)):
            cov.set("business_description", "found")
        if any(
            f.field in ("industry_code", "industry_description") for f in ledger.published_facts(org_number)
        ):
            cov.set("industry", "found")
        fin = [f for f in ledger.published_facts(org_number) if f.category == "financials"]
        if fin:
            cov.set("financials", "found")
        elif accounts_status == "not_found":
            cov.set("financials", "not_available")
        elif accounts_status in ("failed", "blocked", "ambiguous", "not_applicable"):
            cov.set("financials", accounts_status)
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
        for fact in ledger.conflicting_facts(org_number):
            category = fact.category
            if category == "identity" and fact.field in ("industry_code", "industry_description"):
                category = "industry"
            cov.set(category, "ambiguous")
        return cov

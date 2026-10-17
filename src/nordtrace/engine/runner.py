"""Batch runner: bounded-async execution with checkpointing + resume.

- bounded concurrency (default 4 companies in flight)
- global deadline always wins (45 min); per-company soft deadline moves on
- checkpointing: run state in SQLite after every company; resume skips
  companies that already have a terminal state in this run
- every company receives exactly one terminal state
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import List, Optional

from nordtrace.core.budget import BudgetManager, RunBudgetUnavailable
from nordtrace.core.config import settings
from nordtrace.core.contracts import build_result, map_inputs
from nordtrace.core.models import (
    CompanyProfile,
    ResearchError,
    ResearchMetadata,
    ResearchRun,
    RunState,
    TerminalState,
    new_id,
    utcnow,
)
from nordtrace.core.orgnr import validate_orgnr
from nordtrace.core.repository import Repository
from nordtrace.engine.pipeline import CompanyOutcome, ResearchPipeline

logger = logging.getLogger("nordtrace.runner")

_TERMINAL = {s.value for s in TerminalState}


class BatchRunner:
    def __init__(self, repo: Repository, budget: Optional[BudgetManager] = None, concurrency: int = 4):
        self.repo = repo
        self.budget = budget or BudgetManager(
            max_requests=settings.max_requests,
            max_runtime_sec=settings.max_runtime_sec,
            max_cost=settings.max_api_cost_usd,
            per_company_soft_sec=settings.per_company_soft_deadline_sec,
        )
        self.concurrency = max(1, concurrency)

    async def run_batch(
        self, org_numbers: List[str], requested_by: str = "cli", resume_run_id: Optional[str] = None
    ) -> ResearchRun:
        inputs = map_inputs(org_numbers)
        companies = list(dict.fromkeys(item.result_key for item in inputs))
        if resume_run_id:
            run = self.repo.get_run(resume_run_id)
            if run is None:
                raise ValueError(f"run {resume_run_id} not found")
            run.state = RunState.RUNNING.value
            # don't re-research companies that already have a terminal state
            if any(company not in run.companies for company in companies):
                raise ValueError("resume cannot add companies to an existing run")
            pending = [c for c in run.companies if c not in run.company_states]
            self.repo.update_run(run)
        else:
            run = ResearchRun(
                started_at=utcnow().isoformat(),
                companies=companies,
                requested_by=requested_by,
            )
            self.repo.create_run(run)
            self.repo.save_run_inputs(run.run_id, [item.model_dump() for item in inputs])
            pending = run.companies

        try:
            self.budget.bind_run(self.repo, run.run_id, initialize=resume_run_id is None)
        except RunBudgetUnavailable as error:
            for company in pending:
                if self.repo.get_result(run.run_id, company) is None:
                    self.repo.save_result(CompanyProfile(
                        run_id=run.run_id, organisation_number=company, status="failed",
                        errors=[ResearchError(code="run_budget_unavailable", message=str(error))],
                        research_metadata=ResearchMetadata(
                            started_at=run.started_at, completed_at=utcnow().isoformat(),
                            request_count=run.request_count, estimated_cost_usd=run.estimated_cost_usd,
                        ),
                    ))
            run.completed_at, run.state = utcnow().isoformat(), RunState.FAILED.value
            self.repo.update_run(run)
            return self.repo.get_run(run.run_id) or run

        pipeline = ResearchPipeline(self.repo, self.budget)
        owner = new_id("worker")
        try:
            semaphore = asyncio.Semaphore(self.concurrency)

            async def one(org: str) -> None:
                async with semaphore:
                    while not self.repo.try_claim_company(
                        run.run_id, org, owner, self.budget.runtime.time_remaining() + 60
                    ):
                        if self.repo.get_result(run.run_id, org):
                            self._checkpoint(run)
                            return
                        if self.budget.runtime.deadline_reached():
                            raise TimeoutError("deadline while waiting for another worker's task")
                        await asyncio.sleep(min(0.05, self.budget.runtime.time_remaining()))
                    company_started = time.monotonic()
                    try:
                        check = validate_orgnr(org)
                        if not check.valid:
                            outcome = CompanyOutcome(
                                org_number=org, terminal_state=TerminalState.NOT_APPLICABLE.value,
                                error=f"invalid organisation number: {check.reason}",
                                error_code="invalid_organisation_number",
                            )
                        elif self.budget.runtime.deadline_reached():
                            outcome = CompanyOutcome(
                                org_number=org, terminal_state=TerminalState.FAILED.value,
                                error="deadline reached before company started",
                                error_code="deadline_exceeded",
                            )
                        elif self.budget.requests.remaining() <= 0:
                            outcome = CompanyOutcome(
                                org_number=org, terminal_state=TerminalState.FAILED.value,
                                error="run request budget exhausted before company started",
                                error_code="request_budget_exhausted",
                            )
                        else:
                            outcome = await pipeline.research_company(org, run.run_id)
                    except Exception as error:
                        logger.exception("research failed for %s", org)
                        outcome = CompanyOutcome(
                            org_number=org, terminal_state=TerminalState.FAILED.value,
                            error=f"{type(error).__name__}: {error}", error_code="research_failed",
                        )
                    # The pipeline normally persists its result. Orchestration errors
                    # and providers returning outcomes must have complete envelopes too.
                    if self.repo.get_result(run.run_id, org) is None:
                        self.repo.save_result(build_result(
                            outcome, run.run_id, self.budget, run.started_at or utcnow().isoformat()
                        ))
                    if (
                        self.budget.runtime.company_time_exceeded(company_started)
                        and not self.budget.runtime.deadline_reached()
                    ):
                        logger.info("company %s exceeded soft deadline; moving on", org)
                    self.repo.release_company(run.run_id, org, owner)
                    self._checkpoint(run)

            tasks = [asyncio.create_task(one(c)) for c in pending]
            await asyncio.gather(*tasks)
        finally:
            await pipeline.aclose()

        # finalize: companies never researched (deadline) get a terminal state
        run.completed_at = utcnow().isoformat()
        run.state = (
            RunState.COMPLETED.value
            if not self.budget.runtime.deadline_reached()
            else RunState.INTERRUPTED.value
        )
        run.request_count = self.budget.requests.total_used
        run.estimated_cost_usd = round(self.budget.cost.total_used, 6)
        for c in run.companies:
            if c not in run.company_states:
                # deadline hit before this company started
                run.company_states[c] = TerminalState.FAILED.value
        self.repo.update_run(run)
        return run

    def _checkpoint(self, run: ResearchRun) -> None:
        """Persist run state after each company (checkpointing).
        Reads fresh state from the DB so mark_company_state isn't clobbered."""
        self.budget.checkpoint()
        run.request_count = self.budget.requests.total_used
        run.estimated_cost_usd = round(self.budget.cost.total_used, 6)
        fresh = self.repo.get_run(run.run_id)
        if fresh:
            run.company_states = fresh.company_states
        self.repo.update_run(run)

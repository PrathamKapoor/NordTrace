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

from nordtrace.core.budget import BudgetManager
from nordtrace.core.config import settings
from nordtrace.core.models import ResearchRun, RunState, TerminalState, utcnow
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

    async def run_batch(self, org_numbers: List[str], requested_by: str = "cli",
                        resume_run_id: Optional[str] = None) -> ResearchRun:
        if resume_run_id:
            run = self.repo.get_run(resume_run_id)
            if run is None:
                raise ValueError(f"run {resume_run_id} not found")
            run.state = RunState.RUNNING.value
            # don't re-research companies that already have a terminal state
            pending = [c for c in org_numbers if c not in run.company_states]
            run.companies = run.companies + [c for c in pending if c not in run.companies]
            self.repo.update_run(run)
        else:
            run = ResearchRun(
                started_at=utcnow().isoformat(),
                companies=list(dict.fromkeys(org_numbers)),
                requested_by=requested_by,
            )
            self.repo.create_run(run)

        pipeline = ResearchPipeline(self.repo, self.budget)
        try:
            semaphore = asyncio.Semaphore(self.concurrency)

            async def one(org: str) -> None:
                if self.budget.runtime.deadline_reached():
                    self.repo.mark_company_state(run.run_id, org, TerminalState.FAILED.value)
                    return
                async with semaphore:
                    # per-company soft deadline: skip if the global deadline is imminent
                    company_started = time.monotonic()
                    outcome = await pipeline.research_company(org, run.run_id)
                    if self.budget.runtime.company_time_exceeded(company_started) and \
                       not self.budget.runtime.deadline_reached():
                        logger.info("company %s exceeded soft deadline; moving on", org)
                    self.repo.mark_company_state(run.run_id, org, outcome.terminal_state)
                    self._checkpoint(run)

            tasks = [asyncio.create_task(one(c)) for c in run.companies]
            await asyncio.gather(*tasks)
        finally:
            await pipeline.aclose()

        # finalize: companies never researched (deadline) get a terminal state
        run.completed_at = utcnow().isoformat()
        run.state = RunState.COMPLETED.value if not self.budget.runtime.deadline_reached() else RunState.INTERRUPTED.value
        run.request_count = self.budget.requests.total_used
        run.estimated_cost_usd = round(self.budget.cost.total_used, 6)
        for c in run.companies:
            if c not in run.company_states:
                # deadline hit before this company started
                run.company_states[c] = TerminalState.FAILED.value
        self.repo.update_run(run)
        return run

    def _checkpoint(self, run: ResearchRun) -> None:
        """Persist run state after each company (checkpointing)."""
        run.request_count = self.budget.requests.total_used
        run.estimated_cost_usd = round(self.budget.cost.total_used, 6)
        self.repo.update_run(run)

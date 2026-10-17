"""Batch runner: bounded-async execution with checkpointing + resume.

- bounded concurrency (default 4 companies in flight)
- configured acquisition and per-company deadlines cancel cooperative work
- checkpointing: run state in SQLite after every company; resume skips
  companies that already have a terminal state in this run
- every company receives exactly one terminal state
"""

from __future__ import annotations

import asyncio
import logging
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
    new_id,
    utcnow,
)
from nordtrace.core.orgnr import validate_orgnr
from nordtrace.core.repository import Repository, TaskOwnershipError
from nordtrace.engine.pipeline import CompanyOutcome, ResearchPipeline

logger = logging.getLogger("nordtrace.runner")

class BatchRunner:
    def __init__(self, repo: Repository, budget: Optional[BudgetManager] = None, concurrency: int = 4):
        self.repo = repo
        self.budget = budget or BudgetManager(
            max_requests=settings.max_requests,
            max_runtime_sec=settings.max_runtime_sec,
            max_cost=settings.max_api_cost_usd,
            per_company_soft_sec=settings.per_company_soft_deadline_sec,
            finalization_reserve_sec=settings.finalization_reserve_sec,
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

        owner = new_id("worker")
        try:
            self.budget.bind_run(self.repo, run.run_id, initialize=resume_run_id is None)
        except RunBudgetUnavailable as error:
            for company in run.companies:
                if self.repo.get_result(run.run_id, company) is None:
                    code = "legacy_result_unavailable" if company not in pending else "run_budget_unavailable"
                    try:
                        self.repo.save_result(CompanyProfile(
                            run_id=run.run_id, organisation_number=company, status="failed",
                            status_reason=code,
                            errors=[ResearchError(code=code, message=str(error))],
                            research_metadata=ResearchMetadata(
                                started_at=run.started_at, completed_at=utcnow().isoformat(),
                                request_count=run.request_count, estimated_cost_usd=run.estimated_cost_usd,
                            ),
                        ), owner=owner)
                    except TaskOwnershipError:
                        pass  # A live owner's publication must not be replaced by this follower.
            complete = len(self.repo.get_results(run.run_id)) == len(run.companies)
            run.completed_at = utcnow().isoformat() if complete else None
            run.state = RunState.FAILED.value
            self.repo.update_run(run)
            return self.repo.get_run(run.run_id) or run

        pipeline = ResearchPipeline(self.repo, self.budget)
        pipeline.worker_owner = owner
        interrupted = False
        failed = False
        semaphore = asyncio.Semaphore(self.concurrency)

        def failure(org: str, code: str, message: str) -> CompanyOutcome:
            return CompanyOutcome(org_number=org, terminal_state="failed", error_code=code, error=message)

        def save_if_missing(org: str, outcome: CompanyOutcome) -> None:
            if self.repo.get_result(run.run_id, org) is None:
                try:
                    self.repo.save_result(build_result(
                        outcome, run.run_id, self.budget, run.started_at or utcnow().isoformat(),
                    ), owner=owner)
                except TaskOwnershipError:
                    # A cancelled follower cannot finalize a live owner's task.
                    # This run remains inspectably incomplete until that owner finishes.
                    pass

        async def acquire(org: str) -> CompanyOutcome:
            remaining = self.budget.work_time_remaining()
            code = ("company_deadline_exceeded" if self.budget.configuration.per_company_sec < remaining
                    else "deadline_exceeded")
            task = asyncio.create_task(pipeline.research_company(org, run.run_id))
            try:
                done, _ = await asyncio.wait(
                    {task}, timeout=min(self.budget.configuration.per_company_sec, remaining),
                )
                if done:
                    return task.result()
                task.cancel(code)
                await asyncio.gather(task, return_exceptions=True)
                return failure(org, code, "Research acquisition deadline reached.")
            except asyncio.CancelledError:
                task.cancel("research_cancelled")
                await asyncio.gather(task, return_exceptions=True)
                raise

        async def one(org: str) -> None:
            claimed = False
            cancelled = False
            try:
                async with semaphore:
                    check = validate_orgnr(org)
                    if not check.valid:
                        outcome = CompanyOutcome(
                            org_number=org, terminal_state="not_applicable",
                            error=f"invalid organisation number: {check.reason}",
                            error_code="invalid_organisation_number",
                        )
                    elif self.budget.work_time_remaining() <= 0:
                        outcome = failure(org, "deadline_exceeded", "Deadline reached before company start.")
                    elif self.budget.requests.remaining() <= 0:
                        outcome = failure(org, "request_budget_exhausted", "Run request budget exhausted.")
                    else:
                        ownership_wait = asyncio.timeout(self.budget.work_time_remaining())
                        try:
                            async with ownership_wait:
                                while not self.repo.try_claim_company(
                                    run.run_id, org, owner, self.budget.runtime.time_remaining() + 60,
                                ):
                                    if self.repo.get_result(run.run_id, org):
                                        return
                                    await asyncio.sleep(min(0.05, self.budget.work_time_remaining()))
                                claimed = True
                        except TimeoutError:
                            if not ownership_wait.expired():
                                raise
                            outcome = failure(org, "deadline_exceeded", "Deadline waiting for ownership.")
                        else:
                            outcome = await acquire(org)
                    save_if_missing(org, outcome)
            except asyncio.CancelledError:
                cancelled = True
                try:
                    save_if_missing(org, failure(org, "research_cancelled", "Research execution cancelled."))
                except Exception:
                    logger.exception("could not retain cancelled company %s", org)
                raise
            except Exception as error:
                logger.exception("research failed for %s", org)
                save_if_missing(org, failure(org, "research_failed", f"{type(error).__name__}: {error}"))
            finally:
                try:
                    if claimed:
                        self.repo.release_company(run.run_id, org, owner)
                    self._checkpoint(run)
                except Exception:
                    if not cancelled:
                        raise
                    logger.exception("company cancellation cleanup failed for %s", org)

        tasks = [asyncio.create_task(one(c)) for c in pending]
        try:
            await asyncio.gather(*tasks)
        except BaseException as error:
            interrupted = isinstance(error, asyncio.CancelledError)
            failed = not interrupted
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            try:
                # Queued coroutines can be cancelled before entering their body.
                # Finalize them explicitly, preserving already published envelopes.
                code = ("research_cancelled" if interrupted
                        else "run_failed" if failed else "deadline_exceeded")
                for org in run.companies:
                    if org not in pending:
                        save_if_missing(org, failure(
                            org, "legacy_result_unavailable", "Legacy checkpoint lacks a canonical envelope.",
                        ))
                    else:
                        save_if_missing(org, failure(org, code, "Research stopped before completion."))
                complete = len(self.repo.get_results(run.run_id)) == len(run.companies)
                run.completed_at = utcnow().isoformat() if complete else None
                run.state = (RunState.FAILED.value if failed else RunState.INTERRUPTED.value
                             if interrupted or self.budget.work_time_remaining() <= 0 or not complete
                             else RunState.COMPLETED.value)
                self._checkpoint(run)
            except Exception:
                if not interrupted:
                    raise
                logger.exception("run cancellation finalization failed for %s", run.run_id)
            finally:
                try:
                    await pipeline.aclose()
                except Exception:
                    if not interrupted:
                        raise
                    logger.exception("pipeline close failed during cancellation for %s", run.run_id)
        return self.repo.get_run(run.run_id) or run

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

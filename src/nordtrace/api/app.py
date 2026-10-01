"""NordTrace REST API — real endpoints backed by SQLite + research engine.

Every number displayed by the frontend comes from these endpoints.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from nordtrace.core.budget import BudgetManager
from nordtrace.core.config import settings
from nordtrace.core.models import Fact, ResearchRun, RunState, TerminalState, utcnow
from nordtrace.core.orgnr import validate_orgnr
from nordtrace.core.repository import Repository
from nordtrace.engine.pipeline import ResearchPipeline
from nordtrace.engine.runner import BatchRunner

logger = logging.getLogger("nordtrace.api")

app = FastAPI(
    title="NordTrace",
    version="2.0.0",
    description="Norwegian company intelligence agent — evidence-backed research",
)

_repo_lock = threading.Lock()
_repo_instance: Optional[Repository] = None
# background research tasks: run_id -> (asyncio loop handle)
_background_runs: Dict[str, Dict] = {}


def get_repo() -> Repository:
    global _repo_instance
    with _repo_lock:
        if _repo_instance is None:
            _repo_instance = Repository(settings.database_path)
        return _repo_instance


_DEGRADED_STATUSES = ("blocked", "failed", "timeout", "robots_denied", "rate_limited")


class ResearchRequest(BaseModel):
    organisation_number: str
    refresh: bool = Field(default=False, description="Force a new research run even if cached")


class BatchRequest(BaseModel):
    organisation_numbers: List[str]
    concurrency: int = Field(default=4, ge=1, le=16)


def _run_research_blocking(orgnr: str, run_id: str) -> None:
    """Synchronous wrapper run in a worker thread so the API stays responsive."""
    repo = get_repo()
    budget = BudgetManager(
        max_requests=settings.max_requests,
        max_runtime_sec=settings.max_runtime_sec,
        max_cost=settings.max_api_cost_usd,
        per_company_soft_sec=settings.per_company_soft_deadline_sec,
    )
    pipeline = ResearchPipeline(repo, budget)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        outcome = loop.run_until_complete(pipeline.research_company(orgnr, run_id))
        run = repo.get_run(run_id)
        if run:
            run.completed_at = utcnow().isoformat()
            run.state = RunState.COMPLETED.value
            run.request_count = budget.requests.total_used
            run.estimated_cost_usd = round(budget.cost.total_used, 6)
            repo.update_run(run)
            # mark AFTER update_run so update_run doesn't clobber the fresh state
            repo.mark_company_state(run_id, orgnr, outcome.terminal_state)
    except Exception:
        logger.exception("background research failed")
        run = repo.get_run(run_id)
        if run:
            run.state = RunState.FAILED.value
            run.completed_at = utcnow().isoformat()
            repo.update_run(run)
            repo.mark_company_state(run_id, orgnr, TerminalState.FAILED.value)
    finally:
        loop.run_until_complete(pipeline.aclose())
        loop.close()


@app.get("/")
async def root():
    return {"service": "NordTrace", "status": "running", "version": "2.0.0"}


@app.post("/research")
async def start_research(req: ResearchRequest, background: BackgroundTasks):
    orgnr = req.organisation_number.replace(" ", "").replace("-", "")
    check = validate_orgnr(orgnr)
    if not check.valid:
        raise HTTPException(status_code=422, detail=f"invalid organisation number: {check.reason}")
    repo = get_repo()
    run = ResearchRun(started_at=utcnow().isoformat(), companies=[orgnr], requested_by="api")
    repo.create_run(run)
    background.add_task(_run_research_blocking, orgnr, run.run_id)
    return {"run_id": run.run_id, "organisation_number": orgnr, "status": "started"}


@app.get("/research/{run_id}")
async def get_research(run_id: str):
    repo = get_repo()
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    out = {
        "run_id": run.run_id,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "state": run.state,
        "request_count": run.request_count,
        "estimated_cost_usd": run.estimated_cost_usd,
        "companies": run.companies,
        "company_states": run.company_states,
    }
    # attach full results for single-company runs (only when the company persisted)
    if len(run.companies) == 1:
        org = run.companies[0]
        if repo.get_company(org) is not None:
            try:
                out["result"] = _company_payload(repo, org, run_id)
            except HTTPException:
                pass
    return out


def _company_payload(repo: Repository, orgnr: str, run_id: Optional[str] = None) -> dict:
    identity = repo.get_company(orgnr)
    if identity is None:
        raise HTTPException(status_code=404, detail=f"company {orgnr} not found")

    def _dedupe(facts: list) -> list:
        seen: Dict[str, Fact] = {}
        for f in facts:
            if f.status not in ("PUBLISHED", "CONFLICT", "SOURCE_UNAVAILABLE"):
                continue
            k = f.fact_key()
            prev = seen.get(k)
            if k not in seen or (f.retrieved_at or "") > ((prev.retrieved_at if prev else "") or ""):
                seen[k] = f
        return list(seen.values())

    facts = _dedupe(repo.get_facts(orgnr, run_id))
    all_facts = facts
    sources = repo.get_sources(orgnr, run_id)
    changes = repo.get_changes(orgnr)
    # coverage from facts
    cov: Dict[str, str] = {}
    pub = [f for f in all_facts if f.status == "PUBLISHED"]
    for cat in (
        "identity",
        "business_description",
        "industry",
        "financials",
        "leadership",
        "locations",
        "products_services",
        "jobs",
        "recent_activity",
    ):
        if any(f.category == cat for f in pub):
            cov[cat] = "found"
        else:
            cov[cat] = "not_found"
    rejected = [
        {
            "url": s.url,
            "domain": s.domain,
            "reason": s.error_detail or s.access_status,
            "source_id": s.source_id,
            "access_status": s.access_status,
        }
        for s in sources
        if s.access_status in _DEGRADED_STATUSES
    ]
    from nordtrace.core.synthesis import _unknown_list

    coverage_obj = type("C", (), {"get": staticmethod(lambda c: cov.get(c, "not_found"))})()
    unknowns = _unknown_list(coverage_obj)  # type: ignore[arg-type]
    # run metadata
    run = repo.get_run(run_id) if run_id else None
    meta = {
        "started_at": run.started_at if run else None,
        "completed_at": run.completed_at if run else None,
        "request_count": run.request_count if run else 0,
        "estimated_cost_usd": run.estimated_cost_usd if run else 0.0,
        "request_budget": settings.max_requests,
        "cost_budget_usd": settings.max_api_cost_usd,
    }
    if run_id is None:
        # find the latest run containing this company
        for r in reversed(repo.list_runs(limit=20)):
            if orgnr in r.get("companies", []):
                run_id = r.get("run_id")
                break
    identity_row = repo.get_company(orgnr)
    terminal = (
        "available" if identity_row and len(pub) >= 3 else ("not_available" if identity_row else "failed")
    )
    return {
        "run_id": run_id,
        "organisation_number": orgnr,
        "status": terminal,
        "company": json.loads(identity_row.model_dump_json()) if identity_row else None,
        "facts": [json.loads(f.model_dump_json()) for f in facts],
        "changes": [json.loads(c.model_dump_json()) for c in changes],
        "summary": None,
        "unknowns": unknowns,
        "sources": [json.loads(s.model_dump_json()) for s in sources],
        "rejected_sources": rejected,
        "coverage": cov,
        "research_metadata": meta,
        "last_researched_at": identity_row.last_verified_at if identity_row else None,
    }


@app.get("/companies/{orgnr}")
async def get_company(orgnr: str):
    orgnr = orgnr.replace(" ", "").replace("-", "")
    if not validate_orgnr(orgnr).valid:
        raise HTTPException(status_code=422, detail="invalid organisation number")
    repo = get_repo()
    return _company_payload(repo, orgnr)


@app.get("/companies/{orgnr}/facts")
async def get_facts(orgnr: str):
    orgnr = orgnr.replace(" ", "").replace("-", "")
    repo = get_repo()
    if repo.get_company(orgnr) is None:
        raise HTTPException(status_code=404, detail=f"company {orgnr} not found")
    facts = repo.get_facts(orgnr)
    return {"facts": [json.loads(f.model_dump_json()) for f in facts], "evidence_linked": True}


@app.get("/companies/{orgnr}/changes")
async def get_changes(orgnr: str):
    orgnr = orgnr.replace(" ", "").replace("-", "")
    repo = get_repo()
    if repo.get_company(orgnr) is None:
        raise HTTPException(status_code=404, detail=f"company {orgnr} not found")
    changes = repo.get_changes(orgnr)
    return {"changes": [json.loads(c.model_dump_json()) for c in changes]}


@app.get("/companies/{orgnr}/sources")
async def get_sources(orgnr: str):
    orgnr = orgnr.replace(" ", "").replace("-", "")
    repo = get_repo()
    if repo.get_company(orgnr) is None:
        raise HTTPException(status_code=404, detail=f"company {orgnr} not found")
    sources = repo.get_sources(orgnr)
    rejected = [s for s in sources if s.access_status in _DEGRADED_STATUSES]
    return {
        "sources": [json.loads(s.model_dump_json()) for s in sources],
        "rejected_sources": [json.loads(s.model_dump_json()) for s in rejected],
    }


@app.get("/runs/{run_id}/trace")
async def get_trace(run_id: str):
    repo = get_repo()
    if repo.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    events = repo.get_trace(run_id)
    return {"run_id": run_id, "trace": [json.loads(e.model_dump_json()) for e in events]}


@app.post("/batch")
async def start_batch(req: BatchRequest, background: BackgroundTasks):
    valid: List[str] = []
    invalid: List[str] = []
    for o in req.organisation_numbers:
        check = validate_orgnr(o.replace(" ", "").replace("-", ""))
        (valid if check.valid else invalid).append(o)
    if not valid:
        raise HTTPException(status_code=422, detail="no valid organisation numbers")
    repo = get_repo()
    run = ResearchRun(started_at=utcnow().isoformat(), companies=valid, requested_by="api")
    repo.create_run(run)

    def run_batch_blocking():
        runner = BatchRunner(repo, concurrency=req.concurrency)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(runner.run_batch(valid, requested_by="api"))
        except Exception:
            logger.exception("batch failed")
        finally:
            loop.close()

    background.add_task(run_batch_blocking)
    return {"run_id": run.run_id, "requested": len(valid), "invalid_skipped": invalid, "status": "started"}


@app.get("/run-status")
async def run_status():
    """Current run budgets (requests/runtime/cost) for the dashboard."""
    repo = get_repo()
    runs = repo.list_runs(limit=1)
    from nordtrace.core.budget import CostBudget, RequestBudget, RuntimeBudget

    rb = RequestBudget(global_limit=settings.max_requests)
    rt = RuntimeBudget(total_limit_sec=settings.max_runtime_sec)
    cb = CostBudget(limit=settings.max_api_cost_usd)
    last = runs[0] if runs else None
    return {
        "last_run": last,
        "budgets": {
            "requests": {"used": rb.total_used, "limit": rb.global_limit},
            "runtime": {"elapsed_sec": round(rt.elapsed_sec(), 1), "limit_sec": rt.total_limit_sec},
            "cost": {"used": cb.total_used, "limit": cb.limit},
        },
    }


# Serve the frontend
_FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


@app.get("/dashboard")
async def dashboard():
    index = _FRONTEND / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="frontend not built")


@app.get("/health")
async def health():
    return {"ok": True}

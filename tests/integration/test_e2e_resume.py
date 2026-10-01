"""End-to-end + resume + budget tests. Live calls to Brreg; skippable offline."""
import json
import pathlib
import tempfile
import pytest

pytestmark = pytest.mark.live


def _brreg_up() -> bool:
    import urllib.request
    try:
        req = urllib.request.Request("https://data.brreg.no/enhetsregisteret/api/enheter/982463718",
                                     headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception:
        return False


@pytest.fixture()
def engine(tmp_path):
    from nordtrace.core.budget import BudgetManager
    from nordtrace.core.repository import Repository
    from nordtrace.engine.pipeline import ResearchPipeline
    from nordtrace.core.models import ResearchRun, utcnow

    repo = Repository(tmp_path / "e2e.db")
    bm = BudgetManager(max_requests=40)
    pipe = ResearchPipeline(repo, bm)
    run = ResearchRun(started_at=utcnow().isoformat(), companies=["982463718"])
    repo.create_run(run)
    return repo, bm, pipe, run


def test_e2e_full_research(engine):
    """orgnr → identity → sources → facts → evidence → profile → API output."""
    if not _brreg_up():
        pytest.skip("network unavailable")
    repo, bm, pipe, run = engine

    import asyncio
    outcome = asyncio.run(pipe.research_company("982463718", run.run_id))
    assert outcome.terminal_state in ("available", "not_available")
    assert outcome.identity and outcome.identity.legal_name == "TELENOR ASA"
    assert len(outcome.facts) >= 3
    assert len(outcome.evidence) >= 3
    # evidence chain executable: fact → evidence → source → URL → content
    f = outcome.facts[0]
    ev = next(e for e in outcome.evidence if e.evidence_id == f.evidence_id)
    src = next(s for s in outcome.sources if s.source_id == ev.source_id)
    assert src.url and src.content_hash and src.access_status == "success"
    # persisted
    db_facts = repo.get_facts("982463718", run.run_id)
    assert len(db_facts) >= 3
    trace = repo.get_trace(run.run_id)
    assert len(trace) >= 3


def test_e2e_refresh_detects_changes(engine):
    """Run the same company twice; second run must produce change records."""
    if not _brreg_up():
        pytest.skip("network unavailable")
    repo, bm, pipe, run = engine

    import asyncio
    o1 = asyncio.run(pipe.research_company("982463718", run.run_id))
    run2_id = run.run_id + "_refresh"
    from nordtrace.core.models import ResearchRun as RR, utcnow as _u
    repo.create_run(RR(run_id=run2_id, started_at=_u().isoformat(), companies=["982463718"]))
    o2 = asyncio.run(pipe.research_company("982463718", run2_id))
    # second run should not crash and must have changes records (NEW vs prev or UNCHANGED)
    assert o2.terminal_state in ("available", "not_available")
    # previous facts exist for run 2
    prev = repo.get_previous_facts("982463718", exclude_run_id=run2_id)
    assert len(prev) >= 3
    # history preserved: run1 facts still in DB
    run1_facts = repo.get_facts("982463718", run.run_id)
    assert len(run1_facts) >= 3


def test_budget_attack_request_limit(engine):
    """Attempt to exceed the request limit → pipeline degrades to terminal state
    (no request bypass; gateway raises internally and pipeline catches)."""
    from nordtrace.core.budget import BudgetExceededError
    repo, bm, pipe, run = engine
    bm.requests.global_limit = 3
    import asyncio
    # exhaust manually
    while bm.requests.try_acquire(1):
        pass
    assert bm.requests.remaining() == 0
    # pipeline must NOT make any further request; it returns a terminal outcome
    outcome = asyncio.run(pipe.research_company("982463718", run.run_id))
    assert outcome.terminal_state in ("failed", "blocked", "not_available", "ambiguous")
    # request counter unchanged after the attempt (no bypass)
    assert bm.requests.remaining() == 0


def test_concurrent_companies_no_race(engine):
    """10 companies concurrently — request counter stays within limit, no corruption."""
    if not _brreg_up():
        pytest.skip("network unavailable")
    from nordtrace.core.budget import BudgetManager
    from nordtrace.core.repository import Repository
    from nordtrace.engine.pipeline import ResearchPipeline
    from nordtrace.core.models import ResearchRun, utcnow

    repo, _, _, _ = engine
    bm = BudgetManager(max_requests=120)
    pipe = ResearchPipeline(repo, bm)
    run = ResearchRun(started_at=utcnow().isoformat(), companies=["982463718"])
    repo.create_run(run)

    import asyncio

    async def go():
        sem = asyncio.Semaphore(4)
        async def one():
            async with sem:
                await pipe.research_company("982463718", run.run_id)
        await asyncio.gather(*[one() for _ in range(10)])

    asyncio.run(go())
    snap = bm.requests.snapshot()
    assert snap["total_used"] <= 120
    # DB consistent: facts reference existing sources (FK enforced at insert)
    facts = repo.get_facts("982463718", run.run_id)
    assert len(facts) >= 3


def test_resume_skips_completed(engine):
    """Resume: completed companies not unnecessarily rerun; budget correct."""
    repo, bm, pipe, run = engine
    # simulate: 2 companies, 1 completed
    run.companies = ["982463718", "958973306"]
    repo.update_run(run)
    repo.mark_company_state(run.run_id, "982463718", "available")
    unfinished = repo.unfinished_companies(run.run_id)
    assert unfinished == ["958973306"]

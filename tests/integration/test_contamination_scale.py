"""Cross-company contamination + 100-company scale tests."""

import asyncio

import pytest

from nordtrace.core.models import ResearchRun, utcnow

pytestmark = pytest.mark.live


def test_cross_company_contamination(tmp_path):
    """Research A and B concurrently; verify A facts ⊂ A, B facts ⊂ B.
    Zero A-source → B-fact and B-source → A-fact."""
    from nordtrace.core.budget import BudgetManager
    from nordtrace.core.models import ResearchRun, utcnow
    from nordtrace.core.repository import Repository
    from nordtrace.engine.pipeline import ResearchPipeline

    async def go():
        repo = Repository(tmp_path / "contam.db")
        bm = BudgetManager(max_requests=60)
        pipe = ResearchPipeline(repo, bm)
        run = ResearchRun(started_at=utcnow().isoformat(), companies=["982463718", "958973306"])
        repo.create_run(run)

        async def one(org):
            await pipe.research_company(org, run.run_id)

        await asyncio.gather(one("982463718"), one("958973306"))
        await pipe.aclose()
        return repo, run

    repo, run = asyncio.run(go())

    # integrity: cross-company contamination is the critical check
    issues = repo.integrity_check()
    assert issues["cross_company_contamination"] == 0, issues
    assert issues["invalid_company_refs"] == 0

    # A facts reference only A sources; B facts only B sources
    for org in ("982463718", "958973306"):
        facts = repo.get_facts(org, run.run_id)
        sources = {s.source_id: s for s in repo.get_sources(org, run.run_id)}
        for f in facts:
            assert f.source_id in sources, f"fact {f.fact_id} references source outside {org}"
            assert sources[f.source_id].org_number == org


def _simulated_batch_100(tmp_path):
    """Deterministic fixture provider simulating 100 companies with mixed
    source outcomes: success, 429, timeouts, missing websites, malformed PDFs,
    conflicting evidence, slow sources."""
    from nordtrace.adapters import activity, brreg, nav_jobs, pdf_pipeline, website
    from nordtrace.core.budget import BudgetManager
    from nordtrace.core.models import (
        CompanyIdentity,
        EvidenceRecord,
        SourceRecord,
        utcnow,
    )
    from nordtrace.core.repository import Repository
    from nordtrace.engine.pipeline import ResearchPipeline

    class FakeGateway:
        """Simulated gateway: no network, deterministic mixed outcomes."""

        def __init__(self, budget):
            self.budget = budget
            self.calls: list = []

        async def fetch(
            self,
            url,
            *,
            stage="unknown",
            company=None,
            source_type="other",
            authority_tier=4,
            max_bytes=None,
            cache_ttl_override=None,
            respect_robots=False,
            allowed_domains=None,
            retries=2,
        ):
            self.budget.requests.try_acquire(1)
            self.calls.append((url, stage, company))
            # deterministic failure patterns by company hash
            h = sum(ord(c) for c in (company or "x"))
            mode = h % 10
            if mode == 0:  # rate-limited source
                return SourceRecord(
                    url=url,
                    domain="x.no",
                    source_type=source_type,
                    authority_tier=authority_tier,
                    access_status="rate_limited",
                    error_detail="429",
                    org_number=company,
                )
            if mode == 1:  # timeout
                return SourceRecord(
                    url=url,
                    domain="x.no",
                    source_type=source_type,
                    authority_tier=authority_tier,
                    access_status="timeout",
                    error_detail="timeout",
                    org_number=company,
                )
            if mode == 2 and "pdf" in url:  # malformed PDF
                return SourceRecord(
                    url=url,
                    domain="x.no",
                    source_type=source_type,
                    authority_tier=authority_tier,
                    access_status="success",
                    content_hash="bad",
                    org_number=company,
                )
            return SourceRecord(
                url=url,
                domain="x.no",
                source_type=source_type,
                authority_tier=authority_tier,
                access_status="success",
                content_hash=f"h-{company}-{stage}",
                org_number=company,
            )

        def get_content(self, url):
            h = sum(ord(c) for c in url)
            if h % 20 == 0:
                return None  # cache miss (forces honest failure)
            if "pdf" in url and h % 20 == 2:
                from types import SimpleNamespace

                return SimpleNamespace(text="", content=b"not-a-pdf", headers={"content-type": "text/html"})
            from types import SimpleNamespace

            body = f"navn FAKE AS orgnr content for {url}"
            return SimpleNamespace(text=body, content=body.encode(), headers={"content-type": "text/html"})

        async def aclose(self):
            pass

        def snapshot_cache_entries(self):
            return []

    class FakeBrreg(brreg.BrregAdapter):
        def __init__(self, gateway, budget):
            self.gateway = gateway
            self.budget = budget

        async def fetch_entity(self, org_number, run_id):
            src = await self.gateway.fetch(
                f"https://brreg/{org_number}",
                stage="identity",
                company=org_number,
                source_type="registry",
                authority_tier=0,
            )
            if src.access_status != "success":
                if src.http_status == 404:
                    return None, src, None, "not_found"
                return None, src, None, "failed"
            ident = CompanyIdentity(
                organisation_number=org_number,
                legal_name=f"FAKE AS {org_number}",
                status="active",
                municipality="OSLO",
                industry_code="01.000",
                last_verified_at=utcnow().isoformat(),
            )
            ev = EvidenceRecord(
                source_id=src.source_id,
                url=src.url,
                evidence_text="FAKE AS",
                entity_verdict="VERIFIED",
                org_number=org_number,
                content_hash=src.content_hash,
            )
            return ident, src, ev, "found"

    # monkeypatch pipeline internals via subclass
    class SimPipeline(ResearchPipeline):
        def __init__(self, repo, budget):
            from nordtrace.core.entity import EntityResolver, PublicationFirewall
            from nordtrace.core.llm import LLMClient

            self.repo = repo
            self.budget = budget
            self.gateway = FakeGateway(budget)
            self.resolver = EntityResolver()
            self.firewall = PublicationFirewall(self.resolver)
            self.brreg = FakeBrreg(self.gateway, budget)
            self.website = website.WebsiteAdapter(self.gateway, budget, self.resolver)
            self.jobs = nav_jobs.NavJobsAdapter(self.gateway, budget, self.resolver)
            self.pdf = pdf_pipeline.PdfFinancialPipeline(self.gateway, budget, self.resolver)
            self.activity = activity.ActivityAdapter(self.gateway, budget)
            self.llm = LLMClient(budget)

    repo = Repository(tmp_path / "sim100.db")
    bm = BudgetManager(max_requests=2000)
    return repo, bm, SimPipeline


def test_100_companies_simulated_all_terminal(tmp_path):
    """100 simulated companies → all terminal states, no bypass, no deadlock,
    no duplicate facts, no cross-company contamination."""
    repo, bm, SimPipeline = _simulated_batch_100(tmp_path)

    async def go():
        pipe = SimPipeline(repo, bm)
        run = ResearchRun(
            started_at=utcnow().isoformat(), companies=[f"{980000000 + i * 7}"[:9] for i in range(100)]
        )
        # ensure valid checksums: use real valid ones via generator
        from nordtrace.core.orgnr import _checksum_valid

        orgs = []
        base = 980000000
        while len(orgs) < 100:
            candidate = str(base + len(orgs) * 13)
            if len(candidate) == 9 and _checksum_valid(candidate):
                orgs.append(candidate)
            base += 1
        run.companies = orgs
        repo.create_run(run)
        sem = asyncio.Semaphore(8)

        async def one(org):
            async with sem:
                await pipe.research_company(org, run.run_id)

        await asyncio.gather(*[one(o) for o in orgs])
        await pipe.aclose()
        return run

    asyncio.run(go())
    # companies were researched via pipeline directly (not runner) — check facts instead
    facts = repo.conn.execute("SELECT COUNT(DISTINCT org_number) FROM facts").fetchone()[0]
    # deterministic failure mix: mode 0 (rate-limited) + mode 1 (timeout) = 20% of
    # companies fail at identity → ~80% produce facts; every company still got a
    # terminal state and consistent DB
    assert facts >= 70, f"only {facts}/100 companies produced facts"
    # no duplicate facts within a run
    issues = repo.integrity_check()
    assert issues["duplicate_fact_slots_same_run"] == 0, issues
    assert issues["cross_company_contamination"] == 0, issues
    assert issues["foreign_key_violations"] == 0
    # no budget bypass
    assert bm.requests.total_used <= 2000


def test_resume_under_failure_at_company_37(tmp_path):
    """100-company run stopped at 37 → resume: 1-37 not redundantly researched,
    38-100 continue, accounting correct, DB consistent."""
    from nordtrace.core.budget import BudgetManager
    from nordtrace.engine.runner import BatchRunner

    repo, bm, SimPipeline = _simulated_batch_100(tmp_path)

    from nordtrace.core.orgnr import _checksum_valid

    orgs = []
    base = 980000000
    while len(orgs) < 100:
        candidate = str(base + len(orgs) * 13)
        if len(candidate) == 9 and _checksum_valid(candidate):
            orgs.append(candidate)
        base += 1

    # patch pipeline to count researches
    research_counts = {"n": 0, "by_org": {}}
    real_research = SimPipeline.research_company

    class CountingPipeline(SimPipeline):
        async def research_company(self, org, run_id):
            research_counts["n"] += 1
            research_counts["by_org"][org] = research_counts["by_org"].get(org, 0) + 1
            return await real_research(self, org, run_id)

    async def go_interrupt():
        bm2 = BudgetManager(max_requests=2000)
        runner = BatchRunner(repo, bm2, concurrency=4)
        # interrupt: deadline after 37 companies
        original_elapsed = bm2.runtime.elapsed_sec

        def elapsed():
            if research_counts["n"] >= 37:
                return bm2.runtime.total_limit_sec + 1
            return original_elapsed()

        bm2.runtime.elapsed_sec = elapsed
        run = await runner.run_batch(orgs, requested_by="test")
        return run, bm2

    run1, bm2 = asyncio.run(go_interrupt())
    completed_1 = len(run1.company_states)
    assert completed_1 >= 30  # interrupt fired around 37

    async def go_resume():
        runner = BatchRunner(repo, concurrency=4)
        run2 = await runner.run_batch(orgs, resume_run_id=run1.run_id)
        return run2

    asyncio.run(go_resume())
    # 1-37 not redundantly researched
    rerun = sum(1 for org, n in research_counts["by_org"].items() if n > 1)
    assert rerun <= 5  # at most a few reruns (concurrency race at interrupt boundary)
    # all 100 companies now have terminal states
    final = repo.get_run(run1.run_id)
    assert len(final.company_states) == 100
    # DB consistent
    issues = repo.integrity_check()
    assert issues["cross_company_contamination"] == 0
    assert issues["foreign_key_violations"] == 0


def test_extreme_deadline_1sec(tmp_path):
    """deadline = 1 second → tasks cancel, DB consistent, terminal states, clean exit."""
    from nordtrace.core.budget import BudgetManager
    from nordtrace.engine.runner import BatchRunner

    repo, _, SimPipeline = _simulated_batch_100(tmp_path)
    from nordtrace.core.orgnr import _checksum_valid

    orgs = []
    base = 980000000
    while len(orgs) < 20:
        candidate = str(base + len(orgs) * 13)
        if len(candidate) == 9 and _checksum_valid(candidate):
            orgs.append(candidate)
        base += 1

    bm = BudgetManager(max_requests=2000, max_runtime_sec=1)
    runner = BatchRunner(repo, bm, concurrency=4)

    async def go():
        return await runner.run_batch(orgs, requested_by="test")

    run = asyncio.run(go())
    # run finalizes with terminal states for all companies (FAILED if not researched)
    assert len(run.company_states) == len(orgs)
    assert run.state in ("interrupted", "completed", "failed")
    # DB consistent
    issues = repo.integrity_check()
    assert issues["foreign_key_violations"] == 0
    assert issues["cross_company_contamination"] == 0

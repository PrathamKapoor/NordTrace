"""An acquired resource page does not establish an event or active vacancy."""
import asyncio

import httpx
import pytest

from nordtrace.adapters.website import WebsiteAdapter
from nordtrace.core.budget import BudgetManager
from nordtrace.core.entity import EntityResolver
from nordtrace.core.models import CompanyIdentity, ResearchRun
from nordtrace.core.repository import Repository
from nordtrace.core.request_gateway import RequestGateway
from nordtrace.engine.pipeline import ResearchPipeline

ORG = "982463718"
HOME = "https://fixture.example/"


@pytest.mark.parametrize("path,body,kind,family", [
    ("news", "News and press releases", "news_page", "recent_activity"),
    ("news", '<time datetime="2025-01-02">Archive updated</time>News index',
     "news_page", "recent_activity"),
    ("careers", "Careers. No openings listed on this fixture page.", "careers_page", "jobs"),
])
def test_acquired_index_is_a_resource_candidate_without_family_coverage(
    tmp_path, monkeypatch, path, body, kind, family,
):
    repo = Repository(tmp_path / "resources.db")
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    calls = []
    budget = BudgetManager(max_requests=50)
    def respond(request):
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/":
            return httpx.Response(200, text=f'<p>FIXTURE AS Org.nr 982 463 718</p>'
                                  f'<a href="/{path}">Resource</a>')
        return httpx.Response(200, text=f"<main>FIXTURE AS Org.nr 982 463 718 {body}</main>")
    async def execute():
        gateway = RequestGateway(budget, repository=repo)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        adapter = WebsiteAdapter(gateway=gateway, resolver=EntityResolver(), budget=budget)
        try:
            return await adapter.crawl(CompanyIdentity(organisation_number=ORG, legal_name="FIXTURE AS",
                                                      website=HOME), "fixture")
        finally:
            await gateway.aclose()
    try:
        evidence, facts, sources, rejected, coverage = asyncio.run(execute())
        assert not rejected
        assert coverage.get(family) != "found"
        assert not any(f.category == family for f in facts)
        resources = [f for f in facts if f.category == "resources" and f.field == kind]
        assert len(resources) == 1
        resource = resources[0]
        assert resource.value == {"url": HOME + path}
        assert resource.item_key == HOME + path and resource.status == "EXTRACTED"
        source = next(s for s in sources if s.source_id == resource.source_id)
        captured, raw = repo.read_capture(source.source_id)
        assert captured.content_hash == source.content_hash and body.encode() in raw
        assert any(e.evidence_id == resource.evidence_id for e in evidence)
        # Discovery and domain-restricted crawl use separate robots policy keys.
        assert calls == [HOME + "robots.txt", HOME, HOME + "robots.txt", HOME + path]
        assert budget.requests.total_used == 4
    finally:
        repo.close()


def test_resource_candidates_are_retained_without_published_event_or_hiring_claims(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "pipeline.db")
    run = ResearchRun(companies=[ORG])
    repo.create_run(run)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    def respond(request):
        if request.url.path.endswith("/enheter/" + ORG):
            return httpx.Response(200, json={"organisasjonsnummer": ORG, "navn": "FIXTURE AS",
                                           "hjemmeside": HOME})
        if str(request.url) == HOME:
            return httpx.Response(200, text='<p>FIXTURE AS Org.nr 982 463 718</p>'
                                  '<a href="/news">News</a><a href="/careers">Careers</a>')
        if request.url.path in ("/news", "/careers"):
            return httpx.Response(200, text="FIXTURE AS Org.nr 982 463 718. Index page only.")
        return httpx.Response(404)
    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=100))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()
    try:
        outcome = asyncio.run(execute())
        assert outcome.error is None
        profile = repo.get_result(run.run_id, ORG)
        assert profile.status == "available" and profile.facts
        assert not any(f.category in ("recent_activity", "jobs", "resources") for f in profile.facts)
        assert profile.coverage["recent_activity"] != "found" and profile.coverage["jobs"] != "found"
        candidates = [f for f in repo.get_facts(ORG, run.run_id) if f.category == "resources"]
        assert {f.field for f in candidates} == {"news_page", "careers_page"}
        assert len(candidates) == 2 and len({f.claim_id for f in candidates}) == 2
        assert all(f.status == "FAILED" and "snapshot support" in f.conflict_note for f in candidates)
        assert all(any(s.source_id == f.source_id for s in profile.sources) for f in candidates)
    finally:
        repo.close()

"""Candidate discovery and fetched PDF source registration are separate states."""

import asyncio

import httpx
import pytest

from nordtrace.adapters.website import WebsiteAdapter
from nordtrace.core.budget import BudgetManager
from nordtrace.core.entity import EntityResolver
from nordtrace.core.models import CompanyIdentity, EvidenceRecord, Fact, ResearchRun
from nordtrace.core.rate_limiter import RateLimiter, SourcePolicy
from nordtrace.core.repository import Repository
from nordtrace.core.request_gateway import RequestGateway

ORG = "982463718"
HOME = "https://target.example/"
PDF = HOME + "annual.pdf"
HTML = '<p>TARGET AS Org.nr: 982463718</p><a href="annual.pdf">Annual report</a>'


def test_unrequested_pdf_candidate_cannot_appear_successfully_retrieved(tmp_path, monkeypatch):
    monkeypatch.setattr("nordtrace.adapters.website.settings.max_pages_per_company", 0)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(404) if request.url.path == "/robots.txt" else httpx.Response(200, text=HTML)

    repo = Repository(tmp_path / "candidate.db")
    budget = BudgetManager()
    gw = RequestGateway(budget, repository=repo, rate_limiter=RateLimiter(
        default_policy=SourcePolicy(min_interval=0)
    ))
    gw._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))

    async def execute():
        try:
            return await WebsiteAdapter(gw, budget, EntityResolver()).crawl(
                CompanyIdentity(organisation_number=ORG, legal_name="TARGET AS", website=HOME), "fixture"
            )
        finally:
            await gw.aclose()

    _, _, sources, _, _ = asyncio.run(execute())
    candidate = next(source for source in sources if source.url == PDF)
    assert PDF not in calls
    assert candidate.access_status == "discovered"
    assert candidate.retrieved_at is None
    assert candidate.http_status is None
    assert candidate.content_hash is None
    repo.close()


@pytest.mark.parametrize(
    "accounts_status", ["not_found", "not_available", "blocked", "ambiguous", "failed", "not_applicable"]
)
def test_missing_accounts_fallback_registers_the_exact_fetched_pdf(tmp_path, monkeypatch, accounts_status):
    from nordtrace.engine.pipeline import ResearchPipeline

    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    calls = []

    def respond(request):
        calls.append(str(request.url))
        if str(request.url).endswith("/enheter/" + ORG):
            return httpx.Response(200, json={
                "organisasjonsnummer": ORG, "navn": "TARGET AS", "hjemmeside": HOME,
            })
        if str(request.url) == HOME:
            return httpx.Response(200, text=HTML)
        if str(request.url) == PDF:
            return httpx.Response(200, content=b"%PDF fixture acquisition", headers={
                "content-type": "application/pdf",
            })
        return httpx.Response(404)

    repo = Repository(tmp_path / "fallback.db")
    run = ResearchRun(companies=[ORG])
    repo.create_run(run)
    budget = BudgetManager()
    pipeline = ResearchPipeline(repo, budget)
    pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))

    async def accounts(*args):
        source = await pipeline.gateway.fetch("https://registry.example/accounts", retries=0, company=ORG)
        return [], [], source, accounts_status

    # Stub extraction only: this test verifies orchestration and exact acquisition
    # registration, not the current unsafe PDF financial parser's correctness.
    async def extract(identity, url, run_id):
        source = await pipeline.gateway.fetch(url, retries=0, company=ORG, source_type="company_document")
        evidence = EvidenceRecord(
            source_id=source.source_id, evidence_text="NOK 2024 Revenue 123",
            content_hash=source.content_hash, org_number=ORG, entity_verdict="VERIFIED",
        )
        fact = Fact(
            org_number=ORG, category="financials", field="revenue", value=123, normalized_value=123,
            currency="NOK", reporting_period="FY2024", source_id=source.source_id,
            evidence_id=evidence.evidence_id, entity_verdict="VERIFIED", run_id=run_id,
        )
        return [evidence], [fact], source, "found"

    monkeypatch.setattr(pipeline.brreg, "fetch_accounts", accounts)
    monkeypatch.setattr(pipeline.pdf, "process_pdf", extract)

    async def execute():
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()

    outcome = asyncio.run(execute())
    if accounts_status == "not_applicable":
        assert PDF not in calls
        assert not any(fact.category == "financials" for fact in outcome.facts)
        repo.close()
        return
    assert calls.count(PDF) == 1
    published = next(fact for fact in outcome.facts if fact.category == "financials")
    source = next(source for source in outcome.sources if source.source_id == published.source_id)
    assert source.access_status == "success"
    assert source.http_status == 200
    assert repo.read_capture(source.source_id)[1] == b"%PDF fixture acquisition"
    for acquired in outcome.sources:
        if acquired.access_status == "success":
            captured, _ = repo.read_capture(acquired.source_id)
            assert captured.content_hash == acquired.content_hash
    assert repo.get_result(run.run_id, ORG).facts
    assert repo.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    repo.close()


def test_pdf_links_with_query_or_fragment_bypass_html_crawl():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup('<a href="/annual.pdf?download=1#page=3">Report</a>', "lxml")
    links, pdfs = WebsiteAdapter._extract_links(soup, HOME, "target.example")
    assert links == []
    assert pdfs == [HOME + "annual.pdf?download=1"]

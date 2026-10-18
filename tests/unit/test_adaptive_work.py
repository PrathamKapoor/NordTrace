"""A second website pass must do new work; current duplicate pass is retired."""
import asyncio

import httpx
import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.models import ResearchRun
from nordtrace.core.repository import Repository
from nordtrace.engine.pipeline import ResearchPipeline

ORG = "982463718"
HOME = "https://target.example/"


def test_missing_business_support_does_not_repeat_identical_website_crawl(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "adaptive.db")
    run = ResearchRun(companies=[ORG])
    repo.create_run(run)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    invocations = []
    requests = []

    def respond(request):
        requests.append(str(request.url))
        if request.url.path == "/enhetsregisteret/api/enheter/" + ORG:
            return httpx.Response(200, json={
                "organisasjonsnummer": ORG, "navn": "FIXTURE AS", "hjemmeside": HOME,
            })
        if str(request.url) == HOME:
            return httpx.Response(200, text='<html><body>FIXTURE AS Org.nr 982 463 718'
                                  ' Company-owned fixture description.</body></html>')
        return httpx.Response(404)

    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=100))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        crawl = pipeline.website.crawl
        async def counted(*args, **kwargs):
            invocations.append((args, kwargs))
            return await crawl(*args, **kwargs)
        monkeypatch.setattr(pipeline.website, "crawl", counted)
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()
    try:
        outcome = asyncio.run(execute())
        assert outcome.error is None
        assert len(invocations) == 1
        assert requests.count(HOME) == 1
        assert "adaptive_business" not in outcome.stages
        # No unsupported website candidate is promoted merely to satisfy coverage.
        assert not any(f.category == "business_description" for f in outcome.facts)
        assert repo.get_result(run.run_id, ORG).facts
    finally:
        repo.close()

@pytest.mark.parametrize("has_pdf", [False, True])
def test_exactly_spent_budget_fails_only_if_a_pdf_candidate_remains(tmp_path, monkeypatch, has_pdf):
    repo = Repository(tmp_path / "last-request.db")
    run = ResearchRun(companies=[ORG])
    repo.create_run(run)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    calls = []

    def respond(request):
        calls.append(str(request.url))
        if request.url.path == "/enhetsregisteret/api/enheter/" + ORG:
            return httpx.Response(200, json={
                "organisasjonsnummer": ORG, "navn": "FIXTURE AS", "hjemmeside": HOME,
            })
        if str(request.url) == HOME:
            link = '<a href="/annual.pdf">Annual report</a>' if has_pdf else ""
            return httpx.Response(200, text=f'<p>FIXTURE AS Org.nr 982 463 718</p>{link}')
        if request.url.host == "arbeidsplassen.nav.no":
            hop = int(request.url.params.get("hop", "0"))
            if hop < 3:
                return httpx.Response(302, headers={"location": f"/stillinger/api/search?hop={hop + 1}"})
        return httpx.Response(404)

    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=10))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()
    try:
        outcome = asyncio.run(execute())
        frozen = repo.get_result(run.run_id, ORG)
        assert len(calls) == frozen.research_metadata.request_count == 10
        assert frozen.status == ("failed" if has_pdf else "available")
        if has_pdf:
            assert "adaptive_financials" in frozen.errors[0].message
            assert frozen.status_reason == "request_budget_exhausted"
        else:
            assert not frozen.errors and outcome.error is None
        assert frozen.facts
    finally:
        repo.close()

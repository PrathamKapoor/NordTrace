"""No anonymous legacy search or false no-vacancy claim while feed is unwired."""
import asyncio

import httpx
import pytest

from nordtrace.adapters.nav_jobs import NavJobsAdapter
from nordtrace.core.budget import BudgetManager
from nordtrace.core.entity import EntityResolver
from nordtrace.core.models import CompanyIdentity, ResearchRun
from nordtrace.core.repository import Repository
from nordtrace.core.request_gateway import RequestGateway
from nordtrace.engine.pipeline import ResearchPipeline

ORG = "982463718"


def test_unimplemented_nav_feed_does_not_call_legacy_search_or_publish_no_jobs(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "nav.db")
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    requests = []
    async def execute():
        budget = BudgetManager(max_requests=10)
        gateway = RequestGateway(budget, repository=repo)
        def respond(request):
            requests.append(str(request.url))
            return httpx.Response(200, json={"hits": {"hits": []}})
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            adapter = NavJobsAdapter(gateway, budget, EntityResolver())
            identity = CompanyIdentity(organisation_number=ORG, legal_name="FIXTURE AS")
            result = await adapter.fetch_jobs(identity, "fixture")
            assert budget.requests.total_used == 0
            return result
        finally:
            await gateway.aclose()
    try:
        evidence, facts, source, rejected = asyncio.run(execute())
        assert requests == []
        assert not evidence and not facts
        assert source.access_status == "blocked" and source.org_number == ORG
        assert source.retrieved_at is None and source.content_hash is None and source.http_status is None
        assert source.url == "https://pam-stilling-feed.nav.no/api/v1/feed"
        assert rejected[0]["code"] == "nav_feed_not_implemented"
    finally:
        repo.close()


def test_canonical_hiring_state_is_blocked_without_a_no_vacancies_assertion(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "pipeline.db")
    run = ResearchRun(companies=[ORG])
    repo.create_run(run)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    requests = []
    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(200, json={"organisasjonsnummer": ORG, "navn": "FIXTURE AS"}) \
            if request.url.path.endswith("/enheter/" + ORG) else httpx.Response(404)
    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=100))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()
    try:
        asyncio.run(execute())
        result = repo.get_result(run.run_id, ORG)
        assert not any("nav.no" in url for url in requests)
        assert result.coverage["jobs"] == "blocked"
        assert next(item for item in result.refresh_outcomes if item.family == "jobs").state == "blocked"
        assert not any(f.category == "jobs" for f in result.facts)
        assert "no job postings found" not in result.summary.lower()
        assert not any("none found" in item.lower() for item in result.unknowns)
    finally:
        repo.close()

@pytest.mark.parametrize("access", ["blocked", "robots_denied", "rate_limited"])
def test_job_board_refresh_policy_states_remain_blocked(tmp_path, access):
    from nordtrace.core.models import SourceRecord
    from nordtrace.core.refresh import apply_refresh
    from nordtrace.engine.pipeline import CompanyOutcome

    repo = Repository(tmp_path / "states.db")
    run = ResearchRun(companies=[ORG])
    repo.create_run(run)
    source = SourceRecord(url="https://pam-stilling-feed.nav.no/api/v1/feed", source_type="job_board",
                          org_number=ORG, access_status=access)
    outcome = CompanyOutcome(org_number=ORG, terminal_state="available", sources=[source])
    try:
        apply_refresh(repo, outcome, run.run_id)
        assert outcome.refresh_outcomes[0].family == "jobs"
        assert outcome.refresh_outcomes[0].state == outcome.coverage["jobs"] == "blocked"
    finally:
        repo.close()

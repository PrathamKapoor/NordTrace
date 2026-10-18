"""A malformed successful identity response cannot establish authoritative absence."""
import asyncio

import httpx
import pytest

from nordtrace.adapters.brreg import BrregAdapter
from nordtrace.core.budget import BudgetManager
from nordtrace.core.repository import Repository
from nordtrace.core.request_gateway import RequestGateway

ORG = "982463718"


@pytest.mark.parametrize("name", [None, "", "  \t", 0, False, [], {}, ["FIXTURE AS"], {"name": "FIXTURE AS"}])
def test_successful_registry_response_requires_nonempty_string_name(tmp_path, monkeypatch, name):
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    repo = Repository(tmp_path / "schema.db")

    async def execute():
        gateway = RequestGateway(BudgetManager(max_requests=1), repository=repo)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"organisasjonsnummer": ORG, "navn": name})))
        try:
            return await BrregAdapter(gateway, gateway.budget).fetch_entity(ORG, "fixture")
        finally:
            await gateway.aclose()
    try:
        identity, source, evidence, state = asyncio.run(execute())
        assert state == "failed"
        assert identity is None and evidence is None
        assert source.http_status == 200
        assert source.error_detail == "registry identity name missing or invalid"
        assert repo.read_capture(source.source_id)[1]
    finally:
        repo.close()

@pytest.mark.parametrize("status,document,expected,code", [
    (200, {"organisasjonsnummer": ORG}, "failed", "registry_failed"),
    (200, {"organisasjonsnummer": "958973306", "navn": None}, "ambiguous", "entity_ambiguous"),
    (404, {}, "not_available", "entity_not_found"),
])
def test_malformed_identity_and_authoritative_absence_remain_distinct_in_result(
    tmp_path, monkeypatch, status, document, expected, code,
):
    from nordtrace.core.models import ResearchRun, utcnow
    from nordtrace.engine.pipeline import ResearchPipeline

    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    repo = Repository(tmp_path / "outcome.db")
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=1))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(status, json=document)))
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()
    try:
        outcome = asyncio.run(execute())
        result = repo.get_result(run.run_id, ORG)
        assert outcome.terminal_state == result.status == expected
        assert result.company is None and not result.facts
        assert result.errors[0].code == code
        assert result.coverage["identity"] == expected
        assert result.refresh_outcomes[0].state == expected
        assert result.sources[0].http_status == status
    finally:
        repo.close()

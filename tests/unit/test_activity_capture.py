"""Activity must read the retained entity capture, never accounts or URL cache state."""
import asyncio
import json

import httpx
import pytest

from nordtrace.adapters.activity import ActivityAdapter
from nordtrace.core.budget import BudgetManager
from nordtrace.core.models import CompanyIdentity, ResearchRun, utcnow
from nordtrace.core.repository import Repository
from nordtrace.core.request_gateway import RequestGateway
from nordtrace.engine.pipeline import ResearchPipeline

ORG = "982463718"
URL = f"https://data.brreg.no/enhetsregisteret/api/enheter/{ORG}"
ENTITY = {"organisasjonsnummer": ORG, "navn": "FIXTURE AS", "antallAnsatte": 0,
          "registreringsdatoForetaksregisteret": "2024-01-02"}


@pytest.mark.parametrize("accounts_status", [200, 404])
def test_pipeline_activity_uses_entity_capture_independently_of_accounts(
    tmp_path, monkeypatch, accounts_status,
):
    repo = Repository(tmp_path / "pipeline.db")
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    seen = []
    original = ActivityAdapter.extract_activity

    def extract(adapter, identity, *args):
        if len(args) == 3:
            payload, source, run_id = args
            assert payload == ENTITY, "Activity received a different endpoint payload"
            result = original(adapter, identity, payload, source, run_id)
        else:
            source, run_id = args
            result = original(adapter, identity, source, run_id)
        seen.append((source, result))
        return result

    monkeypatch.setattr(ActivityAdapter, "extract_activity", extract)

    def respond(request):
        if str(request.url) == URL:
            return httpx.Response(200, json=ENTITY)
        if "/regnskap/" in request.url.path:
            return httpx.Response(accounts_status, json=[{
                "organisasjonsnummer": ORG, "registreringsdatoForetaksregisteret": "2099-12-31",
            }])
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
        assert len(seen) == 1
        source, (evidence, facts) = seen[0]
        assert source.url == URL
        registration = next(f for f in facts if f.field == "registration")
        assert registration.value["date"] == "2024-01-02"
        assert registration.source_id == source.source_id
        assert all(item.retrieved_at == source.retrieved_at for item in [*evidence, *facts])
        for item in evidence:
            assert item.locator is not None and item.locator.pointer == ""
            assert item.locator.raw_value == ENTITY
            assert json.loads(item.evidence_text) == ENTITY
            assert item.entity_match_details["publication_support"] == "unimplemented"
        # Existing candidate semantics still lack validated activity locators.
        assert not any(f.category == "recent_activity" for f in outcome.facts)
    finally:
        repo.close()


@pytest.mark.parametrize("problem", [
    "cache_poison", "metadata", "wrong_subject", "accounts", "missing", "tamper",
])
def test_activity_replays_exact_capture_and_rejects_unbound_inputs(tmp_path, monkeypatch, problem):
    repo = Repository(tmp_path / "capture.db")
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    document = dict(ENTITY)
    if problem == "wrong_subject":
        document["organisasjonsnummer"] = "958973306"
    url = URL if problem != "accounts" else "https://data.brreg.no/regnskapsregisteret/regnskap/" + ORG

    async def execute():
        gateway = RequestGateway(BudgetManager(max_requests=5), repository=repo)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=document)))
        try:
            source = await gateway.fetch(url, company=ORG, source_type="registry", authority_tier=0)
            identity = CompanyIdentity(organisation_number=ORG, legal_name="FIXTURE AS", employee_count=0)
            adapter = ActivityAdapter(gateway, gateway.budget)
            if problem == "cache_poison":
                gateway.get_content(url).text = json.dumps({
                    "registreringsdatoForetaksregisteret": "2099-01-01",
                })
                evidence, facts = adapter.extract_activity(identity, source, "fixture")
                assert next(f for f in facts if f.field == "registration").value["date"] == "2024-01-02"
                assert all(e.retrieved_at == source.retrieved_at for e in evidence)
            else:
                if problem == "metadata":
                    source.content_hash = "0" * 64
                elif problem == "missing":
                    source.source_id = "absent"
                elif problem == "tamper":
                    repo.conn.execute("UPDATE snapshot_blobs SET content=?", (b"{}",))
                    repo.conn.commit()
                with pytest.raises((ValueError, KeyError)):
                    adapter.extract_activity(identity, source, "fixture")
        finally:
            await gateway.aclose()
    try:
        asyncio.run(execute())
    finally:
        repo.close()

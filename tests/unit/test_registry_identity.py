"""The authoritative response must identify the requested legal entity."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from nordtrace.adapters.brreg import BrregAdapter
from nordtrace.core.budget import BudgetManager
from nordtrace.core.models import SourceRecord


@pytest.mark.parametrize("returned_org", ["958973306", None, "invalid"])
def test_registry_response_cannot_manufacture_requested_identity(returned_org):
    record = {"navn": "UNRELATED AS"}
    if returned_org is not None:
        record["organisasjonsnummer"] = returned_org

    class CapturedGateway:
        async def fetch(self, url, **kwargs):
            return SourceRecord(url=url, access_status="success", http_status=200, source_type="registry")

        def get_content(self, url):
            return SimpleNamespace(content=json.dumps(record).encode())

    adapter = BrregAdapter(CapturedGateway(), BudgetManager())
    identity, source, evidence, state = asyncio.run(adapter.fetch_entity("982463718", "fixture"))
    assert identity is None
    assert evidence is None
    assert state == "ambiguous"
    assert "identifier" in source.error_detail


def test_wrong_registry_entity_is_ambiguous_in_canonical_api_result(tmp_path, monkeypatch):
    import httpx
    from fastapi.testclient import TestClient

    from nordtrace.api.app import app
    from nordtrace.core.repository import Repository
    from nordtrace.core.request_gateway import RequestGateway

    repo = Repository(tmp_path / "registry-boundary.db")
    monkeypatch.setattr("nordtrace.api.app.get_repo", lambda: repo)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    async def client(self):
        if self._client is None:
            self._client = httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={
                    "organisasjonsnummer": "958973306", "navn": "UNRELATED AS",
                })
            ))
        return self._client

    monkeypatch.setattr(RequestGateway, "_get_client", client)
    with TestClient(app) as api:
        run = api.post("/research", json={"organisation_number": "982463718"}).json()
        result = api.get(f"/research/{run['run_id']}").json()["result"]
        assert result["status"] == "ambiguous"
        assert result["company"] is None
        assert result["facts"] == []
        assert result["errors"][0]["code"] == "entity_ambiguous"
        assert result["sources"][0]["http_status"] == 200
    repo.close()


def test_matching_registry_identifier_resolves_the_actual_returned_name():
    class CapturedGateway:
        async def fetch(self, url, **kwargs):
            return SourceRecord(url=url, access_status="success", http_status=200, source_type="registry")

        def get_content(self, url):
            return SimpleNamespace(content=json.dumps({
                "organisasjonsnummer": "982463718", "navn": "TARGET AS",
            }).encode())

    adapter = BrregAdapter(CapturedGateway(), BudgetManager())
    identity, source, evidence, state = asyncio.run(adapter.fetch_entity("982463718", "fixture"))
    assert state == "found"
    assert identity.organisation_number == "982463718"
    assert identity.legal_name == "TARGET AS"
    assert evidence.org_number == "982463718"


@pytest.mark.parametrize("destination", [
    "https://unrelated.example/entity", "http://data.brreg.no/enhetsregisteret/api/enheter/982463718",
    "https://data.brreg.no:8443/enhetsregisteret/api/enheter/982463718",
], ids=["foreign-authority", "tls-downgrade", "alternate-port"])
def test_registry_cannot_delegate_authority_to_an_unrelated_redirect(tmp_path, monkeypatch, destination):
    import httpx

    from nordtrace.core.repository import Repository
    from nordtrace.engine.pipeline import ResearchPipeline

    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    repo = Repository(tmp_path / "registry-redirect.db")
    pipeline = ResearchPipeline(repo, BudgetManager())
    calls = []

    def respond(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(302, headers={"location": destination})
        return httpx.Response(200, json={"organisasjonsnummer": "982463718", "navn": "IMPOSTOR AS"})

    pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))

    async def execute():
        try:
            return await pipeline.brreg.fetch_entity("982463718", "fixture")
        finally:
            await pipeline.aclose()

    identity, source, evidence, state = asyncio.run(execute())
    assert len(calls) == 1
    assert identity is None
    assert evidence is None
    assert state == "blocked"
    assert source.access_status == "blocked"
    repo.close()

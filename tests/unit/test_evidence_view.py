"""Evidence views are frozen-run references, checked against retained bytes offline."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from nordtrace.api.app import app
from nordtrace.core.budget import BudgetManager
from nordtrace.core.models import ResearchRun
from nordtrace.core.repository import Repository
from nordtrace.engine.pipeline import ResearchPipeline

ORG = "982463718"


@pytest.fixture
def captured(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "evidence-view.db")
    monkeypatch.setattr("nordtrace.api.app.get_repo", lambda: repo)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    async def research(name):
        run = ResearchRun(companies=[ORG])
        repo.create_run(run)
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=100))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={
                "organisasjonsnummer": ORG, "navn": name, "antallAnsatte": 0,
            }) if request.url.path.endswith("/enheter/" + ORG) else httpx.Response(404)))
        try:
            await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()
        return repo.get_result(run.run_id, ORG)
    result = asyncio.run(research("OLD Æ AS"))
    with TestClient(app) as client:
        yield repo, result, client, research
    repo.close()


def endpoint(result, evidence_id=None):
    fact = next(f for f in result.facts if f.field == "legal_name")
    return f"/companies/{ORG}/evidence/{evidence_id or fact.evidence_id}?run_id={result.run_id}"


def test_view_returns_supported_value_locator_and_snapshot_metadata(captured):
    repo, result, client, _ = captured
    response = client.get(endpoint(result))
    assert response.status_code == 200
    view = response.json()
    assert view["format"] == "nordtrace-evidence-view-v1"
    assert view["run_id"] == result.run_id and view["organisation_number"] == ORG
    assert view["evidence"]["locator"]["pointer"] == "/navn"
    assert view["evidence"]["locator"]["raw_value"] == "OLD Æ AS"
    assert json.loads(view["evidence"]["evidence_text"]) == "OLD Æ AS"
    assert view["claims"][0]["state"] == "current"
    assert view["claims"][0]["claim"]["value"] == "OLD Æ AS"
    source, body = repo.read_capture(view["source"]["source_id"])
    assert view["snapshot"] == {
        "verified": True, "content_hash": source.content_hash,
        "representation": "http-response-body-v1", "byte_count": len(body),
    }
    assert view["source"]["retrieved_at"] == view["evidence"]["retrieved_at"]


def test_historical_view_does_not_read_latest_company_or_evidence(captured):
    _, result, client, research = captured
    newer = asyncio.run(research("NEW AS"))
    assert newer.run_id != result.run_id
    view = client.get(endpoint(result)).json()
    assert view["claims"][0]["claim"]["value"] == "OLD Æ AS"
    assert view["run_id"] == result.run_id
    assert client.get(endpoint(newer, result.facts[0].evidence_id)).status_code == 404


@pytest.mark.parametrize("problem", ["missing", "tamper"])
def test_missing_or_corrupt_snapshot_is_explicit_and_never_refetched(captured, problem):
    repo, result, client, _ = captured
    if problem == "missing":
        repo.conn.execute("DELETE FROM source_captures")
    else:
        repo.conn.execute("UPDATE snapshot_blobs SET content=?", (b"{}",))
    repo.conn.commit()
    response = client.get(endpoint(result))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "snapshot_unavailable"


def test_view_requires_exact_frozen_membership(captured):
    _, result, client, _ = captured
    assert client.get(endpoint(result).split("?")[0]).status_code == 422
    assert client.get(endpoint(result, "absent")).status_code == 404
    assert client.get(endpoint(result).replace(result.run_id, "absent-run")).status_code == 404
    assert client.get(endpoint(result).replace(ORG, "958973306")).status_code == 404
    assert client.get(endpoint(result).replace(ORG, "invalid")).status_code == 422

def test_view_rechecks_claim_value_instead_of_trusting_persisted_verdict(captured):
    repo, result, client, _ = captured
    payload = result.model_dump(mode="json")
    fact = next(item for item in payload["facts"] if item["field"] == "legal_name")
    fact["value"] = fact["normalized_value"] = "UNSUPPORTED VALUE"
    repo.conn.execute("UPDATE company_results SET payload_json=? WHERE run_id=? AND result_key=?",
                      (json.dumps(payload), result.run_id, ORG))
    repo.conn.commit()
    response = client.get(endpoint(result))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "claim_support_invalid"

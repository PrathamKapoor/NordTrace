"""Registry authority requires official acquisition endpoints, not declared tiers."""

import asyncio
import hashlib
import json

import httpx
import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.ledger import FactLedger
from nordtrace.core.models import EvidenceRecord, Fact, ResearchRun, SourceRecord, utcnow
from nordtrace.core.repository import Repository
from nordtrace.engine.pipeline import ResearchPipeline

ORG = "982463718"
OFFICIAL = "https://data.brreg.no/enhetsregisteret/api/enheter/" + ORG


@pytest.mark.parametrize("url", [
    "https://untrusted.example/enhetsregisteret/api/enheter/" + ORG,
    OFFICIAL.replace("https:", "http:"),
    OFFICIAL.replace("data.brreg.no", "data.brreg.no:8443"),
    OFFICIAL.replace(ORG, "958973306"),
    OFFICIAL.replace("/enheter/", "/other/"),
    OFFICIAL + "?unverified=projection",
    OFFICIAL.replace("https://", "https://user@"),
    OFFICIAL + "#unverified",
])
@pytest.mark.parametrize("location", ["url", "requested_url", "final_url", "redirect_chain"])
def test_declared_registry_tier_cannot_publish_from_unqualified_endpoint(tmp_path, url, location):
    repo = Repository(tmp_path / "authority.db")
    body = json.dumps({"organisasjonsnummer": ORG, "navn": "FIXTURE AS"}).encode()
    urls = {"url": OFFICIAL, location: [OFFICIAL, url, OFFICIAL] if location == "redirect_chain" else url}
    source = SourceRecord(
        **urls, source_type="registry", authority_tier=0, org_number=ORG,
        access_status="success", http_status=200, retrieved_at=utcnow().isoformat(),
        content_hash=hashlib.sha256(body).hexdigest(), snapshot_representation="http-response-body-v1",
    )
    repo.save_capture(source, body)
    evidence = EvidenceRecord(
        source_id=source.source_id, content_hash=source.content_hash, org_number=ORG,
        entity_verdict="VERIFIED", authority_tier=0, source_type="registry",
        retrieved_at=source.retrieved_at, evidence_text='"FIXTURE AS"',
        locator={"kind": "json_pointer", "pointer": "/navn", "raw_value": "FIXTURE AS"},
    )
    fact = Fact(
        org_number=ORG, category="identity", field="legal_name", subject_scope="legal_entity",
        value="FIXTURE AS", normalized_value="FIXTURE AS", source_id=source.source_id,
        evidence_id=evidence.evidence_id, entity_verdict="VERIFIED", retrieved_at=source.retrieved_at,
    )
    ledger = FactLedger(repository=repo)
    result = ledger.add_fact(fact, evidence, source)
    assert result.status == "FAILED"
    assert "acquisition" in result.conflict_note
    repo.close()


@pytest.mark.parametrize("status", [200, 404])
def test_configured_mirror_cannot_publish_structured_identity_as_official(tmp_path, monkeypatch, status):
    repo = Repository(tmp_path / "mirror.db")
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    monkeypatch.setattr("nordtrace.core.config.settings.brreg_base_url", "https://mirror.example/registry")
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=30))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(status, json={
                "organisasjonsnummer": ORG, "navn": "MIRROR ASSERTION AS",
            })
        ))
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()

    outcome = asyncio.run(execute())
    assert outcome.terminal_state == "ambiguous"
    frozen = repo.get_result(run.run_id, ORG)
    assert frozen.company is None and frozen.facts == []
    assert frozen.sources and frozen.sources[0].http_status == status
    if status == 200:
        assert repo.read_capture(frozen.sources[0].source_id)[1]
    assert frozen.errors[0].code == "entity_ambiguous"
    assert frozen.coverage["identity"] == "ambiguous"
    repo.close()


def test_explicit_default_tls_port_and_same_endpoint_redirect_remain_permitted():
    from nordtrace.core.evidence import require_registry_identity_acquisition

    explicit = OFFICIAL.replace("data.brreg.no", "data.brreg.no:443")
    source = SourceRecord(url=OFFICIAL, requested_url=explicit, final_url=OFFICIAL,
                          redirect_chain=[explicit, OFFICIAL])
    require_registry_identity_acquisition(source, ORG)

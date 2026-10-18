"""Escaped non-scalar source strings must not destroy terminal envelopes."""
import asyncio
import hashlib
import json

import httpx
import pytest

from nordtrace.adapters.activity import ActivityAdapter
from nordtrace.adapters.brreg import BrregAdapter
from nordtrace.core.budget import BudgetManager
from nordtrace.core.ledger import FactLedger
from nordtrace.core.models import CompanyIdentity, EvidenceRecord, Fact, ResearchRun, SourceRecord, utcnow
from nordtrace.core.repository import Repository
from nordtrace.core.request_gateway import RequestGateway
from nordtrace.engine.pipeline import ResearchPipeline

ORG = "982463718"


@pytest.mark.parametrize("body,expected", [
    (b'{"organisasjonsnummer":"982463718","navn":"BAD\xed\xa0\x80 AS"}', "failed"),
    (json.dumps({"organisasjonsnummer": ORG, "navn": "FIXTURE \ufffd AS"},
                ensure_ascii=False).encode("utf-8"), "found"),
    (b'\xef\xbb\xbf' + json.dumps({"organisasjonsnummer": ORG, "navn": "FIXTURE \ufffd AS"},
                                  ensure_ascii=False).encode("utf-8"), "found"),
], ids=["malformed-utf8", "literal-replacement-character", "utf8-bom"])
def test_registry_extraction_does_not_replacement_decode_invalid_bytes(tmp_path, monkeypatch, body, expected):
    repo = Repository(tmp_path / "decode.db")
    budget = BudgetManager(max_requests=1)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    async def execute():
        gateway = RequestGateway(budget, repository=repo)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=body,
                                           headers={"content-type": "application/json;charset=utf-8"})))
        try:
            return await BrregAdapter(gateway, budget).fetch_entity(ORG, "fixture")
        finally:
            await gateway.aclose()
    try:
        identity, source, evidence, state = asyncio.run(execute())
        assert state == expected
        assert repo.read_capture(source.source_id)[1] == body
        if expected == "failed":
            assert identity is None and evidence is None and source.error_detail
        else:
            assert identity.legal_name == "FIXTURE \ufffd AS" and evidence
    finally:
        repo.close()


@pytest.mark.parametrize("updates,expected", [
    ({"navn": "BAD\ud800 AS"}, "failed"),
    ({"forretningsadresse": {"adresse": ["Bad\udfff street"]}}, "failed"),
    ({"organisasjonsform": {"kode": "AS\ud800"}}, "failed"),
    ({"metadata": {"bad\ud800": "unselected nested key"}}, "failed"),
    ({"navn": "FIXTURE \U0001f6e0 AS"}, "available"),
], ids=["name-surrogate", "address-surrogate", "form-surrogate", "nested-key", "paired-unicode"])
def test_registry_unicode_preserves_complete_outcome_and_exact_acquisition(
    tmp_path, monkeypatch, updates, expected,
):
    document = {"organisasjonsnummer": ORG, "navn": "FIXTURE AS"} | updates
    body = json.dumps(document, ensure_ascii=True).encode()
    repo = Repository(tmp_path / "unicode.db")
    run = ResearchRun(companies=[ORG])
    repo.create_run(run)
    budget = BudgetManager(max_requests=50, allowed_source_origins=["https://data.brreg.no"])
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    def respond(request):
        if request.url.path.endswith("/enheter/" + ORG):
            return httpx.Response(200, content=body, headers={"content-type": "application/json"})
        return httpx.Response(404)

    async def execute():
        pipeline = ResearchPipeline(repo, budget)
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()

    try:
        outcome = asyncio.run(execute())
        result = repo.get_result(run.run_id, ORG)
        assert outcome.terminal_state == result.status == expected
        source = next(item for item in result.sources if item.url.endswith("/enheter/" + ORG))
        assert repo.read_capture(source.source_id)[1] == body
        result.model_dump_json().encode("utf-8")
        if expected == "failed":
            assert result.company is None and not result.facts
            assert result.errors[0].code == "registry_failed"
        else:
            assert result.company.legal_name == updates["navn"]
            assert any(fact.field == "legal_name" and fact.value == updates["navn"] for fact in result.facts)
    finally:
        repo.close()


@pytest.mark.parametrize("family", ["roles", "accounts", "branches"])
def test_registry_family_abstains_before_retaining_non_scalar_candidates(tmp_path, monkeypatch, family):
    payloads = {
        "roles": {"rollegrupper": [{"type": {"kode": "DAGL"}, "roller": [
            {"type": {"kode": "DAGL"}, "person": {"navn": {"fornavn": "BAD\ud800"}}},
        ]}]},
        "accounts": {"metadata": "bad\ud800"},
        "branches": {"_embedded": {"underenheter": [
            {"organisasjonsnummer": "974760673", "overordnetEnhet": ORG, "navn": "BAD\ud800"},
        ]}},
    }
    body = json.dumps(payloads[family], ensure_ascii=True).encode()
    repo = Repository(tmp_path / "families.db")
    budget = BudgetManager(max_requests=1)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    async def execute():
        gateway = RequestGateway(budget, repository=repo)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=body, headers={"content-type": "application/json"})))
        adapter = BrregAdapter(gateway, budget)
        try:
            if family == "branches":
                result = await adapter.fetch_underenheter(ORG, "fixture")
                assert result.state == "failed" and not result.facts and not result.evidence
                return result.sources[0]
            if family == "accounts":
                evidence, facts, source, state = await adapter.fetch_accounts(ORG, "fixture")
                assert state == "failed"
            else:
                evidence, facts, source = await adapter.fetch_roles(ORG, "fixture")
            assert not evidence and not facts and "Unicode" in source.error_detail
            return source
        finally:
            await gateway.aclose()

    try:
        source = asyncio.run(execute())
        assert source.access_status == "success" and source.http_status == 200
        assert repo.read_capture(source.source_id)[1] == body
        assert budget.requests.total_used == 1
    finally:
        repo.close()


def test_activity_rejects_non_scalar_capture_before_building_candidate_evidence(tmp_path):
    repo = Repository(tmp_path / "activity.db")
    budget = BudgetManager()
    gateway = RequestGateway(budget, repository=repo)
    body = json.dumps({"organisasjonsnummer": ORG, "navn": "FIXTURE AS", "extra": "bad\ud800"}).encode()
    source = SourceRecord(
        url="https://data.brreg.no/enhetsregisteret/api/enheter/" + ORG, source_type="registry",
        authority_tier=0, org_number=ORG, access_status="success", http_status=200,
        retrieved_at=utcnow().isoformat(), content_hash=hashlib.sha256(body).hexdigest(),
        snapshot_representation="http-response-body-v1",
    )
    repo.save_capture(source, body)
    try:
        with pytest.raises(ValueError, match="Unicode"):
            ActivityAdapter(gateway, budget).extract_activity(
                CompanyIdentity(organisation_number=ORG, legal_name="FIXTURE AS"), source, "fixture",
            )
        assert budget.requests.total_used == 0 and repo.read_capture(source.source_id)[1] == body
    finally:
        repo.close()


def test_invalid_unicode_refresh_keeps_last_known_claims_and_frozen_history(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "refresh.db")
    body = [json.dumps({"organisasjonsnummer": ORG, "navn": "FIXTURE AS"}).encode()]
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    def respond(request):
        if request.url.path.endswith("/enheter/" + ORG):
            return httpx.Response(200, content=body[0], headers={"content-type": "application/json"})
        return httpx.Response(404)

    async def execute(run):
        budget = BudgetManager(max_requests=50, allowed_source_origins=["https://data.brreg.no"])
        pipeline = ResearchPipeline(repo, budget)
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()

    try:
        first = ResearchRun(companies=[ORG])
        repo.create_run(first)
        asyncio.run(execute(first))
        previous = repo.get_result(first.run_id, ORG)
        frozen = previous.model_dump_json()
        assert previous.status == "available" and previous.facts
        body[0] = b'{"organisasjonsnummer":"982463718","navn":"BAD\\ud800 AS"}'
        second = ResearchRun(companies=[ORG])
        repo.create_run(second)
        asyncio.run(execute(second))
        current = repo.get_result(second.run_id, ORG)
        assert current.status == "failed" and not current.facts
        assert {fact.claim_id for fact in current.last_known} == {fact.claim_id for fact in previous.facts}
        assert all(fact.status == "SOURCE_UNAVAILABLE" for fact in current.last_known)
        assert not any(change.change_type == "RETRACTED" for change in current.changes)
        assert repo.get_result(first.run_id, ORG).model_dump_json() == frozen
        current.model_dump_json().encode("utf-8")
    finally:
        repo.close()


@pytest.mark.parametrize("position", ["key", "value", "selected-name"])
def test_independent_snapshot_validation_rejects_non_scalar_json_strings(tmp_path, position):
    value = "BAD\ud800 AS" if position == "selected-name" else "FIXTURE AS"
    document = {"organisasjonsnummer": ORG, "navn": value}
    if position != "selected-name":
        document["metadata"] = {"bad\udfff" if position == "key" else "key": "bad\ud800"}
    body = json.dumps(document, ensure_ascii=True).encode()
    repo = Repository(tmp_path / "proof.db")
    source = SourceRecord(
        url="https://data.brreg.no/enhetsregisteret/api/enheter/" + ORG, source_type="registry",
        authority_tier=0, org_number=ORG, access_status="success", http_status=200,
        retrieved_at=utcnow().isoformat(), content_hash=hashlib.sha256(body).hexdigest(),
        snapshot_representation="http-response-body-v1",
    )
    repo.save_capture(source, body)
    evidence = EvidenceRecord(
        source_id=source.source_id, source_type="registry", authority_tier=0, org_number=ORG,
        entity_verdict="VERIFIED", retrieved_at=source.retrieved_at, content_hash=source.content_hash,
        evidence_text=json.dumps(value, ensure_ascii=False),
        locator={"kind": "json_pointer", "pointer": "/navn", "raw_value": value},
    )
    fact = Fact(org_number=ORG, category="identity", field="legal_name", value=value,
                normalized_value=value, source_id=source.source_id, evidence_id=evidence.evidence_id,
                subject_scope="legal_entity", entity_verdict="VERIFIED", retrieved_at=source.retrieved_at)
    try:
        result = FactLedger(repo).add_fact(fact, evidence, source)
        assert result.status == "FAILED" and "Unicode" in result.conflict_note
        assert repo.read_capture(source.source_id)[1] == body
    finally:
        repo.close()

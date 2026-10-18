"""Publication input must have unambiguous pointers and finite JSON numbers."""
import asyncio
import hashlib
import json

import httpx
import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.evidence import parse_json_body
from nordtrace.core.ledger import FactLedger
from nordtrace.core.models import EvidenceRecord, Fact, ResearchRun, SourceRecord, utcnow
from nordtrace.core.repository import Repository
from nordtrace.engine.pipeline import ResearchPipeline

ORG = "982463718"


@pytest.mark.parametrize("body", [
    b'{"navn":"FIRST AS","navn":"SECOND AS"}',
    b'{"navn":"FIRST AS","na\\u0076n":"SECOND AS"}',
    b'{"nested":{"value":1,"value":2}}',
    b'{"value":NaN}', b'{"value":Infinity}', b'{"value":-Infinity}',
    b'{"value":1e400}',
    b'{"value":1e-4000}',
], ids=["duplicate", "escaped-duplicate", "nested-duplicate", "nan", "infinity",
        "negative-infinity", "overflow", "underflow"])
def test_json_body_rejects_ambiguous_members_and_unsupported_numbers(body):
    with pytest.raises(ValueError):
        parse_json_body(body)


@pytest.mark.parametrize("body,expected", [
    (b'{"value":0}', {"value": 0}),
    (b'{"value":-1.25}', {"value": -1.25}),
    (b'{"text":"NaN Infinity duplicate value:1 value:2"}',
     {"text": "NaN Infinity duplicate value:1 value:2"}),
    ('{"å":1,"a\\u030a":2}'.encode(), {"å": 1, "a\u030a": 2}),
    (b'{"value":0e-99999999999999999999999999}', {"value": 0.0}),
])
def test_json_body_keeps_valid_values_and_distinct_unicode_member_names(body, expected):
    assert parse_json_body(body) == expected


@pytest.mark.parametrize("suffix,reason", [
    (b',"navn":"FIRST AS","navn":"SECOND AS"', "duplicate"),
    (b',"navn":"SECOND AS","metadata":{"value":1,"value":2}', "duplicate"),
    (b',"navn":"SECOND AS","value":NaN', "nonfinite"),
    (b',"navn":"SECOND AS","value":1e400', "finite range"),
    (b',"navn":"SECOND AS","value":1e-4000', "underflow"),
], ids=["member-duplicate", "nested-duplicate", "nan", "overflow", "underflow"])
def test_snapshot_claim_cannot_publish_from_ambiguous_or_unsupported_json(tmp_path, suffix, reason):
    body = b'{"organisasjonsnummer":"982463718"' + suffix + b'}'
    repo = Repository(tmp_path / "duplicate.db")
    source = SourceRecord(
        url="https://data.brreg.no/enhetsregisteret/api/enheter/" + ORG, source_type="registry",
        authority_tier=0, org_number=ORG, access_status="success", http_status=200,
        retrieved_at=utcnow().isoformat(), content_hash=hashlib.sha256(body).hexdigest(),
        snapshot_representation="http-response-body-v1",
    )
    repo.save_capture(source, body)
    value = "SECOND AS"
    evidence = EvidenceRecord(
        source_id=source.source_id, source_type="registry", authority_tier=0, org_number=ORG,
        entity_verdict="VERIFIED", retrieved_at=source.retrieved_at, content_hash=source.content_hash,
        evidence_text=json.dumps(value),
        locator={"kind": "json_pointer", "pointer": "/navn", "raw_value": value},
    )
    fact = Fact(org_number=ORG, category="identity", field="legal_name", value=value,
                normalized_value=value, source_id=source.source_id, evidence_id=evidence.evidence_id,
                subject_scope="legal_entity", entity_verdict="VERIFIED", retrieved_at=source.retrieved_at)
    try:
        result = FactLedger(repo).add_fact(fact, evidence, source)
        assert result.status == "FAILED" and reason in result.conflict_note
    finally:
        repo.close()


@pytest.mark.parametrize("suffix", [
    b',"navn":"FIRST AS","navn":"SECOND AS"',
    b',"navn":"SECOND AS","value":NaN',
    b',"navn":"SECOND AS","metadata":' + b"[" * 65 + b"0" + b"]" * 65,
], ids=["duplicate-member", "nonfinite-constant", "excessive-nesting"])
def test_rejected_source_json_still_produces_a_terminal_envelope(tmp_path, monkeypatch, suffix):
    body = b'{"organisasjonsnummer":"982463718"' + suffix + b'}'
    repo = Repository(tmp_path / "pipeline.db")
    run = ResearchRun(companies=[ORG])
    repo.create_run(run)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=1))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=body, headers={"content-type": "application/json"})))
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()
    try:
        outcome = asyncio.run(execute())
        profile = repo.get_result(run.run_id, ORG)
        assert outcome.terminal_state == profile.status == "failed"
        assert profile.company is None and not profile.facts
        assert profile.errors[0].code == "registry_failed"
        assert profile.sources[0].http_status == 200 and profile.sources[0].access_status == "success"
        assert repo.read_capture(profile.sources[0].source_id)[1] == body
        assert body.decode() not in profile.sources[0].error_detail
    finally:
        repo.close()


@pytest.mark.parametrize("depth", [65, 1200])
def test_json_body_rejects_excessive_nesting_before_decoder(depth):
    with pytest.raises(ValueError, match="nesting capacity"):
        parse_json_body(b"[" * depth + b"0" + b"]" * depth)


def test_json_body_keeps_bounded_nesting_and_quoted_brackets():
    raw = b"[" * 64 + b'"[{\\\"}]"' + b"]" * 64
    value = parse_json_body(raw)
    for _ in range(64):
        value = value[0]
    assert value == '[{"}]'

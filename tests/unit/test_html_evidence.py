"""Authored synthetic HTML; deterministic support tests, not live accuracy labels."""

import hashlib
import json

import pytest

from nordtrace.core.ledger import FactLedger
from nordtrace.core.models import EvidenceRecord, Fact, SourceRecord, utcnow
from nordtrace.core.repository import Repository

ORG = "982463718"
FOREIGN = "958973306"
VALUE = "Vi reparerer måleinstrumenter."
NODE = {
    "@context": "https://schema.org",
    "@type": "Organization",
    "legalName": "TARGET AS",
    "vatID": "NO982463718MVA",
    "description": VALUE,
}


def html_body(node=None, footer=None):
    return (
        '<html><body><main>TARGET AS</main><script type="application/ld+json">'
        + json.dumps(NODE if node is None else node, ensure_ascii=False)
        + "</script><footer>"
        + (footer or "Org.nr. 982 463 718")
        + "</footer></body></html>"
    ).encode()


@pytest.fixture
def material(tmp_path):
    repo = Repository(tmp_path / "html.db")

    def capture(body, url, kind, tier, content_type=None):
        source = SourceRecord(
            url=url,
            requested_url=url,
            final_url=url,
            source_type=kind,
            authority_tier=tier,
            org_number=ORG,
            access_status="success",
            http_status=200,
            content_type=content_type or ("text/html; charset=utf-8" if tier else "application/json"),
            retrieved_at=utcnow().isoformat(),
            content_hash=hashlib.sha256(body).hexdigest(),
            snapshot_representation="http-response-body-v1",
        )
        repo.save_capture(source, body)
        return source

    anchor = capture(
        json.dumps(
            {"organisasjonsnummer": ORG, "navn": "TARGET AS", "hjemmeside": "https://target.example"}
        ).encode(),
        "https://data.brreg.no/enhetsregisteret/api/enheter/" + ORG,
        "registry",
        0,
    )

    def attempt(
        body=None, change=None, anchor_source=anchor, website="https://target.example/", content_type=None
    ):
        source = capture(html_body() if body is None else body, website, "company_website", 1, content_type)
        data = {
            "source_id": source.source_id,
            "source_type": source.source_type,
            "authority_tier": 1,
            "org_number": ORG,
            "entity_verdict": "VERIFIED",
            "retrieved_at": source.retrieved_at,
            "content_hash": source.content_hash,
            "evidence_text": VALUE,
            "locator": {
                "kind": "html_json_ld",
                "representation": "utf8-html-lxml-v1",
                "script_index": 0,
                "pointer": "/description",
                "raw_value": VALUE,
                "identity_source_id": anchor_source.source_id,
                "normalization": "schema-org-description-v1",
                "assertion": "source_authored",
            },
        }
        fact_data = {
            "org_number": ORG,
            "category": "business_description",
            "field": "description",
            "value": VALUE,
            "normalized_value": VALUE,
            "subject_scope": "legal_entity",
            "entity_verdict": "VERIFIED",
            "retrieved_at": source.retrieved_at,
            "source_id": source.source_id,
        }
        if change:
            change(data, fact_data, source)
        evidence = EvidenceRecord(**data)
        fact = Fact(**fact_data, evidence_id=evidence.evidence_id)
        ledger = FactLedger(repo)
        ledger.add_source(anchor_source)
        result = ledger.add_fact(fact, evidence, source)
        return result, evidence, source, ledger

    yield repo, anchor, attempt, capture
    repo.close()


def test_exact_html_literal_support_publishes_from_retained_bytes(material):
    result, evidence, source, ledger = material[2]()
    assert result.status == "PUBLISHED", result.conflict_note
    assert ledger.published_facts() == [result]
    assert evidence.locator.kind == "html_json_ld"
    assert material[0].read_capture(source.source_id)[1] == html_body()


@pytest.mark.parametrize(
    "case", ["value", "raw", "pointer", "script", "scope", "predicate", "anchor", "verdict", "quote", "time"]
)
def test_unsupported_html_claims_fail_publication(material, case):
    def change(data, fact, source):
        if case == "value":
            fact["value"] = fact["normalized_value"] = "Invented description"
        if case == "raw":
            data["locator"]["raw_value"] = "Invented description"
        if case == "pointer":
            data["locator"]["pointer"] = "/legalName"
        if case == "script":
            data["locator"]["script_index"] = 1
        if case == "scope":
            fact["subject_scope"] = "group"
        if case == "predicate":
            fact["category"] = "activity"
        if case == "anchor":
            data["locator"]["identity_source_id"] = "missing"
        if case == "verdict":
            data["entity_verdict"] = "REJECTED"
        if case == "quote":
            data["evidence_text"] = "Unsupported generated paraphrase"
        if case == "time":
            fact["retrieved_at"] = "2000-01-01T00:00:00+00:00"

    result, *_ = material[2](change=change)
    assert result.status == "FAILED", case


@pytest.mark.parametrize("case", ["org", "name", "footer", "domain", "duplicate", "encoding", "context"])
def test_wrong_subject_and_unresolvable_html_fail_publication(material, case):
    node = dict(NODE)
    footer = None
    website = "https://target.example/"
    if case == "org":
        node["vatID"] = "NO" + FOREIGN + "MVA"
    if case == "name":
        node["legalName"] = "TARGET HOLDING AS"
    if case == "context":
        node["@context"] = "https://untrusted.example/context"
    if case == "footer":
        footer = "Org.nr. " + FOREIGN
    if case == "domain":
        website = "https://unrelated.example/"
    body = html_body(node, footer)
    if case == "duplicate":
        body = body.replace(b'"description":', b'"description":"Invented","description":')
    if case == "encoding":
        body = body.replace(b"TARGET AS", b"TARGET\xff AS")
    result, *_ = material[2](body=body, website=website)
    assert result.status == "FAILED", case


def test_html_requires_versioned_envelope_and_roundtrips_offline(material, tmp_path):
    from nordtrace.core.export import export_run, verify_bundle
    from nordtrace.core.models import CompanyProfile, ResearchRun

    repo, anchor, attempt, _ = material
    fact, evidence, source, _ = attempt()
    run = ResearchRun(companies=[ORG])
    repo.create_run(run)
    repo.save_run_inputs(run.run_id, [{"index": 0, "supplied": ORG, "result_key": ORG}])
    data = {
        "run_id": run.run_id,
        "organisation_number": ORG,
        "status": "available",
        "facts": [fact],
        "evidence": [evidence],
        "sources": [anchor, source],
    }
    with pytest.raises(ValueError, match="requires result schema_version 1.2"):
        CompanyProfile(**data)
    result = CompanyProfile(schema_version="1.2", **data)
    from nordtrace.validate import validate_result

    assert validate_result(result.model_dump(mode="json")) == []
    repo.save_result(result)
    assert repo.get_result(run.run_id, ORG) == result
    output = tmp_path / "html.zip"
    manifest = export_run(repo, run.run_id, output)
    assert manifest["result_schema"] == "nordtrace-1.2"
    repo.close()
    assert verify_bundle(output)["completion"]["complete"] is True


@pytest.mark.parametrize("case", ["tax-id", "zero-port", "charset"])
def test_html_identity_and_representation_contradictions_are_not_ignored(material, case):
    node = dict(NODE)
    website = "https://target.example/"
    if case == "tax-id":
        node["taxID"] = "NO" + FOREIGN
    if case == "zero-port":
        website = "https://target.example:0/"
    body = html_body(node)
    if case == "charset":
        body = body.replace(b"<html>", b'<html><head><meta charset="iso-8859-1"></head>')
    result, *_ = material[2](body=body, website=website)
    assert result.status == "FAILED", case


@pytest.mark.parametrize("target", ["html", "anchor"])
@pytest.mark.parametrize("damage", ["missing", "tampered"])
def test_html_snapshot_failure_cannot_publish(material, target, damage):
    repo, anchor, attempt, _ = material

    def change(data, fact, source):
        source_id = source.source_id if target == "html" else anchor.source_id
        if damage == "missing":
            repo.conn.execute("DELETE FROM source_captures WHERE source_id=?", (source_id,))
        else:
            repo.conn.execute(
                "UPDATE snapshot_blobs SET content=? WHERE content_hash=("
                "SELECT content_hash FROM source_captures WHERE source_id=?)",
                (b"bad", source_id),
            )
        repo.conn.commit()

    fact, *_ = attempt(change=change)
    assert fact.status == "FAILED"


@pytest.mark.parametrize(
    "content_type",
    [
        "text/html;charset=windows-1252;charset=utf-8",
        "text/html;charset=utf-8;charset=utf-8",
        "text/html;charset=windows-1252",
        "application/xhtml+xml;charset=utf-8",
    ],
)
def test_html_ambiguous_or_unsupported_http_representation_abstains(material, content_type):
    fact, *_ = material[2](content_type=content_type)
    assert fact.status == "FAILED"


def test_outage_retains_html_anchor_without_an_incidental_registry_claim(material):
    from nordtrace.core.budget import BudgetManager
    from nordtrace.core.contracts import build_result
    from nordtrace.core.models import CompanyProfile, ResearchRun
    from nordtrace.core.refresh import apply_refresh
    from nordtrace.engine.pipeline import CompanyOutcome

    repo, anchor, attempt, _ = material
    fact, evidence, source, _ = attempt()
    earlier = ResearchRun(companies=[ORG], started_at="2026-10-01T00:00:00+00:00")
    repo.create_run(earlier)
    previous = CompanyProfile(
        schema_version="1.2",
        run_id=earlier.run_id,
        organisation_number=ORG,
        status="available",
        facts=[fact],
        evidence=[evidence],
        sources=[anchor, source],
    )
    repo.save_result(previous)
    later = ResearchRun(companies=[ORG], started_at="2026-10-02T00:00:00+00:00")
    repo.create_run(later)
    outcome = CompanyOutcome(org_number=ORG, terminal_state="failed")
    apply_refresh(repo, outcome, later.run_id)
    assert {item.source_id for item in outcome.sources} == {anchor.source_id, source.source_id}
    result = build_result(outcome, later.run_id, BudgetManager(), later.started_at)
    assert result.schema_version == "1.2"
    assert len(result.last_known) == 1 and not result.facts
    assert {change.change_type for change in result.changes} == {"SOURCE_UNAVAILABLE"}
    assert repo.get_result(earlier.run_id, ORG) == previous


@pytest.mark.parametrize("case", ["supported", "foreign-footer", "conflict"])
def test_real_pipeline_html_publication_and_api_replay(tmp_path, monkeypatch, case):
    import asyncio

    import httpx
    from fastapi.testclient import TestClient

    from nordtrace.api.app import app
    from nordtrace.core.budget import BudgetManager
    from nordtrace.core.export import export_run, verify_bundle
    from nordtrace.core.models import ResearchRun
    from nordtrace.engine.pipeline import ResearchPipeline
    from nordtrace.validate import validate_result

    repo = Repository(tmp_path / "pipeline.db")
    run = ResearchRun(companies=[ORG])
    repo.create_run(run)
    repo.save_run_inputs(run.run_id, [{"index": 0, "supplied": ORG, "result_key": ORG}])
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    monkeypatch.setattr("nordtrace.api.app.get_repo", lambda: repo)
    body = html_body(footer="Org.nr " + FOREIGN if case == "foreign-footer" else None)
    if case == "conflict":
        other = dict(NODE, description="A competing description.")
        body = body.replace(
            b"</body>",
            b'<script type="application/ld+json">' + json.dumps(other).encode() + b"</script></body>",
        )

    def respond(request):
        if str(request.url) == "https://target.example/":
            return httpx.Response(200, content=body, headers={"content-type": "text/html; charset=utf-8"})
        if request.url.path.endswith("/enheter/" + ORG):
            return httpx.Response(
                200,
                json={
                    "organisasjonsnummer": ORG,
                    "navn": "TARGET AS",
                    "hjemmeside": "https://target.example/",
                },
            )
        return httpx.Response(404)

    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=30))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()

    try:
        outcome = asyncio.run(execute())
        assert outcome.error is None
        profile = repo.get_result(run.run_id, ORG)
        assert validate_result(profile.model_dump(mode="json")) == []
        descriptions = [fact for fact in profile.facts if fact.category == "business_description"]
        if case == "supported":
            assert len(descriptions) == 1 and descriptions[0].value == VALUE
            assert profile.schema_version == "1.2" and "Website description:" in profile.summary
            evidence = next(
                item for item in profile.evidence if item.evidence_id == descriptions[0].evidence_id
            )
            with TestClient(app) as client:
                response = client.get(f"/companies/{ORG}/evidence/{evidence.evidence_id}?run_id={run.run_id}")
                assert response.status_code == 200
                view = response.json()
                assert view["evidence"]["locator"]["script_index"] == 0
                assert view["evidence"]["locator"]["assertion"] == "source_authored"
                assert view["evidence"]["locator"]["raw_value"] == VALUE
        else:
            assert not descriptions and VALUE not in profile.summary
            if case == "conflict":
                assert (
                    len([fact for fact in profile.conflicts if fact.category == "business_description"]) == 2
                )
        output = tmp_path / "pipeline.zip"
        export_run(repo, run.run_id, output)
        repo.close()
        assert verify_bundle(output)["completion"]["result_count"] == 1
    finally:
        repo.close()


def test_html_content_after_closed_document_cannot_hide_competing_subject(material):
    body = html_body() + b"<footer>Org.nr. 958973306</footer>"
    fact, *_ = material[2](body=body)
    assert fact.status == "FAILED"


def test_html_meta_cannot_have_ambiguous_charset_parameters(material):
    body = html_body().replace(
        b"<html>",
        b'<html><head><meta http-equiv="content-type" '
        b'content="text/html;charset=utf-8;charset=windows-1252"></head>',
    )
    fact, *_ = material[2](body=body)
    assert fact.status == "FAILED"


@pytest.mark.parametrize("source_type", ["company_website", "other"])
def test_html_cannot_publish_through_an_unlocated_in_memory_ledger(source_type):
    source = SourceRecord(
        source_id="html",
        source_type=source_type,
        access_status="success",
        content_type="text/html",
        org_number=ORG,
    )
    evidence = EvidenceRecord(
        source_id="html", evidence_text=VALUE, entity_verdict="VERIFIED", org_number=ORG
    )
    fact = Fact(
        org_number=ORG,
        category="business_description",
        field="description",
        value=VALUE,
        source_id="html",
        evidence_id=evidence.evidence_id,
        entity_verdict="VERIFIED",
    )
    result = FactLedger().add_fact(fact, evidence, source)
    assert result.status == "FAILED"

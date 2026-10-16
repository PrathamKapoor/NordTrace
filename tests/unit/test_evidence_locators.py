"""Adversarial support labels independent of extractor confidence/snippets."""

import hashlib
import json

import pytest

from nordtrace.core.ledger import FactLedger
from nordtrace.core.models import EvidenceRecord, Fact, SourceRecord, utcnow
from nordtrace.core.repository import Repository

ORG = "982463718"


def captured(repo, document):
    body = json.dumps(document, ensure_ascii=False).encode("utf-8")
    source = SourceRecord(
        url="https://data.brreg.no/enhetsregisteret/api/enheter/" + ORG,
        source_type="registry", org_number=ORG, access_status="success", http_status=200,
        authority_tier=0, retrieved_at=utcnow().isoformat(),
        content_hash=hashlib.sha256(body).hexdigest(), snapshot_representation="http-response-body-v1",
    )
    repo.save_capture(source, body)
    return source


@pytest.mark.parametrize(
    "defect", ["missing_locator", "wrong_value", "wrong_pointer", "wrong_subject", "tamper"]
)
def test_registry_claim_cannot_publish_from_an_invented_snippet(tmp_path, defect):
    repo = Repository(tmp_path / "proof.db")
    document = {"organisasjonsnummer": ORG, "navn": "TARGET AS", "hjemmeside": "TARGET AS"}
    if defect == "wrong_subject":
        document["organisasjonsnummer"] = "958973306"
    source = captured(repo, document)
    locator = {"kind": "json_pointer", "pointer": "/navn", "raw_value": "TARGET AS"}
    if defect == "wrong_pointer":
        locator["pointer"] = "/hjemmeside"
    if defect == "tamper":
        repo.conn.execute("UPDATE snapshot_blobs SET content=?", (b"tampered",))
        repo.conn.commit()
    ev = EvidenceRecord(
        source_id=source.source_id, evidence_text='"TARGET AS"', content_hash=source.content_hash,
        org_number=ORG, entity_verdict="VERIFIED", locator=None if defect == "missing_locator" else locator,
        source_type="registry", authority_tier=0, retrieved_at=source.retrieved_at,
    )
    value = "INVENTED AS" if defect == "wrong_value" else "TARGET AS"
    fact = Fact(
        org_number=ORG, subject_scope="legal_entity", category="identity",
         field="legal_name", value=value, normalized_value=value,
        source_id=source.source_id, evidence_id=ev.evidence_id, entity_verdict="VERIFIED",
        retrieved_at=source.retrieved_at,
    )
    ledger = FactLedger(repository=repo)
    result = ledger.add_fact(fact, ev, source)
    assert result.status == "FAILED"
    expected = {
        "missing_locator": "locator required", "wrong_value": "supported normalized value",
        "wrong_pointer": "claim predicate", "wrong_subject": "snapshot subject", "tamper": "integrity",
    }
    assert expected[defect] in result.conflict_note
    repo.close()


def test_exact_registry_field_and_zero_are_supported(tmp_path):
    repo = Repository(tmp_path / "proof.db")
    source = captured(repo, {"organisasjonsnummer": ORG, "navn": "TARGET AS", "antallAnsatte": 0})
    ledger = FactLedger(repository=repo)
    for field, pointer, value in [
        ("legal_name", "/navn", "TARGET AS"), ("employee_count", "/antallAnsatte", 0),
    ]:
        ev = EvidenceRecord(
            source_id=source.source_id, content_hash=source.content_hash, org_number=ORG,
            entity_verdict="VERIFIED", evidence_text=json.dumps(value),
            source_type="registry", authority_tier=0, retrieved_at=source.retrieved_at,
            locator={"kind": "json_pointer", "pointer": pointer, "raw_value": value},
        )
        fact = Fact(
            org_number=ORG, subject_scope="legal_entity", category="identity",
         field=field, value=value, normalized_value=value,
            source_id=source.source_id, evidence_id=ev.evidence_id, entity_verdict="VERIFIED",
            retrieved_at=source.retrieved_at,
        )
        assert ledger.add_fact(fact, ev, source).status == "PUBLISHED"
    assert len(ledger.published_facts()) == 2
    repo.close()


def test_pointer_escape_and_array_rules():
    from nordtrace.core.evidence import resolve_pointer

    data = {"a/b": {"~key": [0, "supported"]}}
    assert resolve_pointer(data, "/a~1b/~0key/1") == "supported"
    for pointer in ["a/b", "/a~2b", "/a~1b/~0key/-1", "/a~1b/~0key/01", "/a~1b/~0key/2"]:
        with pytest.raises(ValueError):
            resolve_pointer(data, pointer)


@pytest.mark.parametrize("raw", [True, False, -1, 1.5, "1"])
def test_employee_predicate_rejects_non_count_values_in_identity_and_claim(tmp_path, raw):
    from types import SimpleNamespace

    from nordtrace.adapters.brreg import BrregAdapter
    from nordtrace.core.budget import BudgetManager

    repo = Repository(tmp_path / "types.db")
    document = {"organisasjonsnummer": ORG, "navn": "TARGET AS", "antallAnsatte": raw}
    source = captured(repo, document)
    adapter = BrregAdapter(
        SimpleNamespace(get_content=lambda url: SimpleNamespace(text=json.dumps(document))), BudgetManager()
    )
    identity = adapter._parse_entity(document, ORG)
    assert identity.employee_count is None
    _, candidates = adapter.identity_claims(identity, source, "fixture")
    assert not any(fact.field == "employee_count" for fact in candidates)
    ev = EvidenceRecord(
        source_id=source.source_id, content_hash=source.content_hash, org_number=ORG,
        source_type="registry", authority_tier=0, retrieved_at=source.retrieved_at,
        entity_verdict="VERIFIED", evidence_text=json.dumps(raw),
        locator={"kind": "json_pointer", "pointer": "/antallAnsatte", "raw_value": raw},
    )
    fact = Fact(
        org_number=ORG, subject_scope="legal_entity", category="identity",
         field="employee_count", value=raw, normalized_value=raw,
        source_id=source.source_id, evidence_id=ev.evidence_id, entity_verdict="VERIFIED",
        retrieved_at=source.retrieved_at,
    )
    result = FactLedger(repository=repo).add_fact(fact, ev, source)
    assert result.status == "FAILED"
    assert "nonnegative integer" in result.conflict_note
    repo.close()


@pytest.mark.parametrize("change", ["source_date", "source_authority", "evidence_date", "claim_date"])
def test_observation_metadata_cannot_upgrade_the_capture(tmp_path, change):
    repo = Repository(tmp_path / "metadata.db")
    source = captured(repo, {"organisasjonsnummer": ORG, "navn": "TARGET AS"})
    ev = EvidenceRecord(
        source_id=source.source_id, content_hash=source.content_hash, org_number=ORG,
        source_type="registry", authority_tier=0, retrieved_at=source.retrieved_at,
        entity_verdict="VERIFIED", evidence_text='"TARGET AS"',
        locator={"kind": "json_pointer", "pointer": "/navn", "raw_value": "TARGET AS"},
    )
    fact = Fact(
        org_number=ORG, subject_scope="legal_entity", category="identity",
         field="legal_name", value="TARGET AS",
        normalized_value="TARGET AS",
        source_id=source.source_id, evidence_id=ev.evidence_id, entity_verdict="VERIFIED",
        retrieved_at=source.retrieved_at,
    )
    if change == "source_date":
        source.retrieved_at = "2030-01-01T00:00:00+00:00"
    elif change == "source_authority":
        source.authority_tier = 4
    elif change == "evidence_date":
        ev.retrieved_at = "2030-01-01T00:00:00+00:00"
    else:
        fact.retrieved_at = "2030-01-01T00:00:00+00:00"
    result = FactLedger(repository=repo).add_fact(fact, ev, source)
    assert result.status == "FAILED"
    assert "capture" in result.conflict_note
    repo.close()


def test_forced_liquidation_and_missing_flags_are_not_active():
    from nordtrace.adapters.brreg import BrregAdapter
    from nordtrace.core.budget import BudgetManager

    adapter = BrregAdapter(None, BudgetManager())
    minimal = {"organisasjonsnummer": ORG, "navn": "TARGET AS"}
    identity = adapter._parse_entity(minimal, ORG)
    assert identity.status == "unknown"
    assert identity.bankrupt is None
    assert identity.under_liquidation is None
    assert identity.is_part_of_concern is None
    flags = {"konkurs": False, "underAvvikling": False, "underTvangsavviklingEllerTvangsopplosning": True}
    assert adapter._parse_entity(minimal | flags, ORG).status == "under_compulsory_liquidation"
    flags["underTvangsavviklingEllerTvangsopplosning"] = False
    assert adapter._parse_entity(minimal | flags, ORG).status == "active"


def test_production_result_and_sqlite_roundtrip_keep_atomic_locators(tmp_path, monkeypatch):
    import asyncio

    import httpx
    from fastapi.testclient import TestClient

    from nordtrace.api.app import app
    from nordtrace.core.budget import BudgetManager
    from nordtrace.core.models import ResearchRun
    from nordtrace.engine.pipeline import ResearchPipeline

    repo = Repository(tmp_path / "pipeline-proof.db")
    run = ResearchRun(companies=[ORG])
    repo.create_run(run)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    monkeypatch.setattr("nordtrace.api.app.get_repo", lambda: repo)
    record = {
        "organisasjonsnummer": ORG, "navn": "TARGET Æ AS", "antallAnsatte": 0,
        "organisasjonsform": {"kode": "AS"},
        "forretningsadresse": {"adresse": ["Testveien 1"], "postnummer": "0123", "poststed": "OSLO"},
    }

    def respond(request):
        if str(request.url).endswith("/enheter/" + ORG):
            return httpx.Response(200, json=record)
        return httpx.Response(404)

    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager())
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()

    result = asyncio.run(execute())
    values = {fact.field: fact.value for fact in result.facts}
    assert values == {
        "legal_name": "TARGET Æ AS", "employee_count": 0,
        "organisation_form": "AS", "registered_address": "Testveien 1 0123 OSLO",
    }
    assert result.identity.status == "unknown"
    for fact in result.facts:
        evidence = repo.get_evidence(fact.evidence_id)
        assert evidence.locator is not None
        source = next(
            source for source in repo.get_sources(ORG, run.run_id) if source.source_id == fact.source_id
        )
        assert source.snapshot_representation == "http-response-body-v1"
        assert FactLedger(repository=repo).add_fact(fact.model_copy(), evidence, source).status == "PUBLISHED"
    with TestClient(app) as api:
        payload = api.get(f"/companies/{ORG}?run_id={run.run_id}").json()
        assert payload["company"]["status"] == "unknown"
        assert all(evidence["locator"] for evidence in payload["evidence"])
        assert {fact["field"] for fact in payload["facts"]} == set(values)
    assert repo.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    repo.close()


def test_schema3_upgrade_preserves_captures_and_adds_nullable_locators(tmp_path):
    import sqlite3

    path = tmp_path / "upgrade3.db"
    repo = Repository(path)
    source = captured(repo, {"organisasjonsnummer": ORG, "navn": "TARGET AS"})
    repo.conn.execute("ALTER TABLE evidence DROP COLUMN locator_json")
    repo.conn.execute("ALTER TABLE sources DROP COLUMN source_json")
    repo.conn.execute("ALTER TABLE facts DROP COLUMN item_key")
    repo.conn.execute("ALTER TABLE facts DROP COLUMN subject_scope")
    repo.conn.execute("ALTER TABLE changes DROP COLUMN change_json")
    repo.conn.execute("PRAGMA user_version=3")
    repo.conn.commit()
    repo.close()
    upgraded = Repository(path)
    assert upgraded.read_capture(source.source_id)[0] == source
    assert upgraded.conn.execute("PRAGMA user_version").fetchone()[0] == 5
    assert upgraded.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    upgraded.close()
    backups = list(tmp_path.glob("upgrade3.db.pre-v4-*.bak"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 3
    Repository(path).close()
    assert len(list(tmp_path.glob("upgrade3.db.pre-v4-*.bak"))) == 1


@pytest.mark.parametrize(
    "scope,item", [("group", None), ("unknown", None), ("legal_entity", "invented-item")]
)
def test_scalar_registry_identity_cannot_be_relabelled_as_group_or_collection(tmp_path, scope, item):
    repo = Repository(tmp_path / "scope.db")
    source = captured(repo, {"organisasjonsnummer": ORG, "navn": "TARGET AS"})
    evidence = EvidenceRecord(
        source_id=source.source_id, content_hash=source.content_hash, org_number=ORG,
        source_type="registry", authority_tier=0, retrieved_at=source.retrieved_at,
        entity_verdict="VERIFIED", evidence_text='"TARGET AS"',
        locator={"kind": "json_pointer", "pointer": "/navn", "raw_value": "TARGET AS"},
    )
    fact = Fact(
        org_number=ORG, category="identity", field="legal_name", value="TARGET AS",
        normalized_value="TARGET AS", subject_scope=scope, item_key=item,
        source_id=source.source_id, evidence_id=evidence.evidence_id, entity_verdict="VERIFIED",
        retrieved_at=source.retrieved_at,
    )
    assert FactLedger(repository=repo).add_fact(fact, evidence, source).status == "FAILED"
    repo.close()

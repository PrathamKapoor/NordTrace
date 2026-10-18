"""Competing supported observations must not publish an arbitrary winner."""

import hashlib
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from nordtrace.adapters.brreg import BrregAdapter
from nordtrace.core.budget import BudgetManager
from nordtrace.core.contracts import build_result
from nordtrace.core.ledger import FactLedger
from nordtrace.core.models import Coverage, ResearchRun, SourceRecord, utcnow
from nordtrace.core.repository import Repository
from nordtrace.core.synthesis import build_summary
from nordtrace.engine.pipeline import CompanyOutcome

ORG = "982463718"


def observed_name(repo, name, industry=None, field="legal_name"):
    document = {"organisasjonsnummer": ORG, "navn": name}
    if industry is not None:
        document["naeringskode1"] = {"kode": "01.000", "beskrivelse": industry}
    body = json.dumps(document).encode()
    source = SourceRecord(
        url="https://data.brreg.no/enhetsregisteret/api/enheter/" + ORG,
        source_type="registry", authority_tier=0, org_number=ORG,
        access_status="success", http_status=200, retrieved_at=utcnow().isoformat(),
        content_hash=hashlib.sha256(body).hexdigest(), snapshot_representation="http-response-body-v1",
    )
    repo.save_capture(source, body)
    adapter = BrregAdapter(SimpleNamespace(get_content=lambda url: SimpleNamespace(content=body)),
                           BudgetManager())
    identity = adapter._parse_entity(document, ORG)
    evidence, facts = adapter.identity_claims(identity, source, "fixture")
    selected = next(fact for fact in facts if fact.field == field)
    supporting = next(item for item in evidence if item.evidence_id == selected.evidence_id)
    return identity, source, supporting, selected


def test_competing_supported_values_withhold_every_observation_and_preserve_evidence(tmp_path):
    repo = Repository(tmp_path / "conflicts.db")
    ledger = FactLedger(repository=repo)
    _, first_source, first_evidence, first = observed_name(repo, "FIRST AS")
    _, second_source, second_evidence, second = observed_name(repo, "SECOND AS")
    ledger.add_fact(first, first_evidence, first_source)
    assert len(ledger.published_facts()) == 1
    ledger.add_fact(second, second_evidence, second_source)
    assert ledger.published_facts() == []
    assert len(ledger.conflicting_facts()) == 2
    assert {fact.value for fact in ledger.conflicting_facts()} == {"FIRST AS", "SECOND AS"}
    assert all(fact.status == "CONFLICT" for fact in ledger.conflicting_facts())
    # Corroborating one side cannot silently resolve the competing observation.
    _, third_source, third_evidence, third = observed_name(repo, "FIRST AS")
    ledger.add_fact(third, third_evidence, third_source)
    assert ledger.published_facts() == []
    assert len(ledger.conflicting_facts()) == 3
    ledger.add_fact(third, third_evidence, third_source)
    assert len(ledger.conflicting_facts()) == 3
    assert len({fact.claim_id for fact in ledger.conflicting_facts()}) == 1
    for fact in ledger.conflicting_facts():
        assert repo.read_capture(fact.source_id)[1]
    repo.close()


def test_canonical_conflicts_remain_inspectable_without_publishing_disputed_values(tmp_path):
    repo = Repository(tmp_path / "envelope.db")
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    ledger = FactLedger(repository=repo)
    identity, source, evidence, first = observed_name(repo, "FIRST AS")
    ledger.add_fact(first, evidence, source)
    _, second_source, second_evidence, second = observed_name(repo, "SECOND AS")
    ledger.add_fact(second, second_evidence, second_source)
    outcome = CompanyOutcome(
        org_number=ORG, terminal_state="ambiguous", identity=identity,
        facts=ledger.published_facts(), conflicts=ledger.conflicting_facts(),
        evidence=list(ledger.evidence.values()), sources=list(ledger.sources.values()),
    )
    result = build_result(outcome, run.run_id, BudgetManager(), run.started_at)
    repo.save_result(result)
    frozen = repo.get_result(run.run_id, ORG)
    assert frozen.facts == []
    assert len(frozen.conflicts) == 2
    assert {fact.evidence_id for fact in frozen.conflicts} == {
        evidence.evidence_id, second_evidence.evidence_id,
    }
    assert frozen.status == "ambiguous"
    assert frozen.company.legal_name == ""
    assert frozen.company.unresolved_fields == ["legal_name"]
    assert identity.legal_name == "FIRST AS"  # Acquisition identity is not mutated.
    invalid = outcome
    invalid.facts = [first.model_copy(update={"status": "PUBLISHED"})]
    with pytest.raises(ValidationError, match="conflicting claim"):
        build_result(invalid, run.run_id, BudgetManager(), run.started_at)
    repo.close()


@pytest.mark.parametrize("fail_after_conflict", [False, True])
def test_pipeline_persists_conflicts_and_ambiguous_family_without_summary_winner(
    tmp_path, monkeypatch, fail_after_conflict,
):
    import asyncio

    import httpx
    from fastapi.testclient import TestClient

    from nordtrace.api.app import app
    from nordtrace.engine.pipeline import ResearchPipeline

    repo = Repository(tmp_path / "pipeline-conflict.db")
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    monkeypatch.setattr("nordtrace.api.app.get_repo", lambda: repo)
    entity_calls = []

    def respond(request):
        if str(request.url).endswith("/enheter/" + ORG):
            entity_calls.append(str(request.url))
            return httpx.Response(200, json={
                "organisasjonsnummer": ORG, "navn": "FIRST AS" if len(entity_calls) == 1 else "SECOND AS",
            })
        return httpx.Response(404)

    pipeline = ResearchPipeline(repo, BudgetManager(max_requests=30))
    pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))

    async def contradictory_refresh(org, run_id):
        # Inject a second real acquired identity observation at this stage.
        # This verifies pipeline publication plumbing, not roles extraction.
        pipeline.gateway.cache_ttl = 0
        identity, source, _, hint = await pipeline.brreg.fetch_entity(org, run_id)
        assert hint == "found"
        evidence, facts = pipeline.brreg.identity_claims(identity, source, run_id)
        return evidence, facts, source

    monkeypatch.setattr(pipeline.brreg, "fetch_roles", contradictory_refresh)
    if fail_after_conflict:
        async def crash_accounts(*args):
            raise RuntimeError("Injected parser failure after supported disagreement")

        monkeypatch.setattr(pipeline.brreg, "fetch_accounts", crash_accounts)

    async def execute():
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()

    outcome = asyncio.run(execute())
    assert outcome.terminal_state == ("failed" if fail_after_conflict else "ambiguous")
    assert outcome.coverage["identity"] == "ambiguous"
    assert outcome.facts == []
    assert len(outcome.conflicts) == 2
    assert "FIRST AS" not in (outcome.summary or "") and "SECOND AS" not in (outcome.summary or "")
    with TestClient(app) as api:
        result = api.get(f"/companies/{ORG}?run_id={run.run_id}").json()
        assert result["status"] == ("failed" if fail_after_conflict else "ambiguous")
        assert len(result["conflicts"]) == 2
        assert result["facts"] == []
        assert result["company"]["legal_name"] == ""
        assert result["company"]["unresolved_fields"] == ["legal_name"]
        assert repo.get_company(ORG).legal_name == ""
        for observation in result["conflicts"]:
            assert repo.read_capture(observation["source_id"])[1]
    repo.close()


def test_disputed_structured_fields_and_dependent_address_parts_are_suppressed():
    from nordtrace.core.models import CompanyIdentity, Fact

    identity = CompanyIdentity(
        organisation_number=ORG, legal_name="TARGET AS", employee_count=12,
        industry_description="First industry", registered_address="First street 1",
        municipality="OSLO", postal_code="0001", status="active", bankrupt=False,
        under_liquidation=False,
    )
    conflicts = [Fact(
        org_number=ORG, category="identity", field=field, status="CONFLICT", value=value,
        source_id="source", evidence_id="evidence",
    ) for field, value in [
        ("employee_count", 12), ("industry_description", "First industry"),
        ("registered_address", "First street 1"), ("status", "active"),
    ]]
    # Test the projection separately from envelope reference validation.
    from nordtrace.core.contracts import project_identity

    projected = project_identity(identity, conflicts)
    assert projected.legal_name == "TARGET AS"
    assert projected.employee_count is None
    assert projected.industry_description is None
    assert projected.registered_address is None
    assert projected.municipality is None and projected.postal_code is None
    assert projected.status == "unknown"
    assert projected.bankrupt is None and projected.under_liquidation is None
    assert identity.employee_count == 12 and identity.municipality == "OSLO"


def test_summary_withholds_disputed_identity_and_industry(tmp_path):
    repo = Repository(tmp_path / "summary-conflicts.db")
    ledger = FactLedger(repository=repo)
    identity = None
    for name, industry in [("FIRST AS", "First industry"), ("SECOND AS", "Second industry")]:
        for field in ("legal_name", "industry_description"):
            observed, source, evidence, fact = observed_name(repo, name, industry, field)
            identity = identity or observed
            ledger.add_fact(fact, evidence, source)
    summary = build_summary(identity, ledger, Coverage(), [])
    for disputed in ("FIRST AS", "SECOND AS", "First industry", "Second industry"):
        assert disputed not in summary
    assert "sources disagree" in summary.lower()
    repo.close()


def test_summary_finds_verified_values_after_logical_key_change(tmp_path):
    repo = Repository(tmp_path / "summary-values.db")
    ledger = FactLedger(repository=repo)
    identity, source, evidence, fact = observed_name(
        repo, "TARGET AS", "Fixture manufacturing", "industry_description"
    )
    ledger.add_fact(fact, evidence, source)
    identity.industry_description = "Unverified fallback"
    summary = build_summary(identity, ledger, Coverage(), [])
    assert "Industry: Fixture manufacturing" in summary
    # Other value families use the same typed lookup, without parsing IDs.
    from nordtrace.core.models import EvidenceRecord, Fact

    legacy = FactLedger()
    legacy.add_source(SourceRecord(source_id="fixture", access_status="success", org_number=ORG))
    legacy.add_evidence(EvidenceRecord(
        evidence_id="quote", source_id="fixture", evidence_text="Fixture workforce 0", org_number=ORG,
        entity_verdict="VERIFIED",
    ))
    legacy.add_fact(Fact(
        org_number=ORG, category="identity", field="employee_count", value=0, normalized_value=0,
        source_id="fixture", evidence_id="quote", entity_verdict="VERIFIED",
    ))
    assert "Registered employees: 0." in build_summary(identity, legacy, Coverage(), [])
    repo.close()

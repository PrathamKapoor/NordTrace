"""Brief references resolve to published claims; subunits retain their own scope."""
import asyncio
import re
from types import SimpleNamespace

import httpx
import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.ledger import FactLedger
from nordtrace.core.models import CompanyIdentity, Coverage, EvidenceRecord, Fact, ResearchRun, SourceRecord
from nordtrace.core.repository import Repository
from nordtrace.core.synthesis import build_summary
from nordtrace.engine.pipeline import ResearchPipeline

ORG = "982463718"
SUBUNIT = "958973306"


@pytest.mark.parametrize("unit_count", [1, 4])
def test_real_profile_brief_references_identity_and_registered_subunit_observations(
    tmp_path, monkeypatch, unit_count,
):
    repo = Repository(tmp_path / "references.db")
    run = ResearchRun(companies=[ORG])
    repo.create_run(run)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    def respond(request):
        if request.url.path.endswith("/enheter/" + ORG):
            return httpx.Response(200, json={
                "organisasjonsnummer": ORG, "navn": "TARGET FIXTURE AS", "antallAnsatte": 0,
                "naeringskode1": {"kode": "70.200", "beskrivelse": "Fixture consulting"},
            })
        if request.url.path.endswith("/underenheter"):
            units = [{
                "organisasjonsnummer": SUBUNIT, "overordnetEnhet": ORG, "navn": "CLOSED FIXTURE UNIT",
                "beliggenhetsadresse": {"adresse": ["Fixture street 7"], "postnummer": "0001",
                                       "poststed": "OSLO", "kommune": "OSLO"},
                "nedleggelsesdato": "2025-12-31",
            }]
            for number in ["984851006", "985889635", "992445432"][:unit_count - 1]:
                units.append({"organisasjonsnummer": number, "overordnetEnhet": ORG,
                              "navn": f"Additional fixture unit {number}"})
            return httpx.Response(200, json={"_embedded": {"underenheter": units},
                                            "page": {"number": 0, "size": 20,
                                                     "totalElements": unit_count, "totalPages": 1}})
        return httpx.Response(404)
    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=30,
                                    allowed_source_origins=["https://data.brreg.no"]))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()
    try:
        asyncio.run(execute())
        result = repo.get_result(run.run_id, ORG)
        references = set(re.findall(r"\[(claim_v1_[a-f0-9]{64})\]", result.summary))
        published = {fact.claim_id: fact for fact in result.facts}
        assert references <= published.keys()
        displayed = [f for f in result.facts if f.field in (
            "legal_name", "industry_description", "industry_code", "employee_count",
        )]
        subunits = sorted((f for f in result.facts if f.field == "branch"), key=lambda f: f.item_key)
        assert len(subunits) == unit_count
        displayed += subunits[:3]
        assert len(displayed) == 4 + min(3, unit_count) and {f.claim_id for f in displayed} <= references
        if unit_count == 4:
            assert subunits[-1].claim_id not in references
            assert "Additional verified subunit observations appear in the profile." in result.summary
        branch = next(f for f in displayed if f.field == "branch")
        assert f"[{branch.claim_id}]" in result.summary
        assert f"CLOSED FIXTURE UNIT (orgnr {SUBUNIT})" in result.summary
        assert "Fixture street 7 0001 OSLO" in result.summary
        assert "closed 2025-12-31" in result.summary
        assert "Registered subunits observed:" in result.summary
        assert "active workplace" not in result.summary.lower()
        employee = next(f for f in displayed if f.field == "employee_count")
        assert f"Registered employees: 0. [{employee.claim_id}]" in result.summary
    finally:
        repo.close()


@pytest.mark.parametrize("category,field,value", [
    ("business_description", "description", "Fixture services"),
    ("leadership", "board", {"name": "Fixture Person", "role": "chair"}),
    ("recent_activity", "event", {"event": "Fixture event", "date": "2025-01-02"}),
    ("financials", "total_operating_revenue", 123),
])
def test_template_fragments_keep_logical_claim_references_without_granting_publication(
    category, field, value,
):
    # Legacy in-memory ledger tests template mechanics only, not production support
    # for these still-withheld predicates. Real snapshot-backed publication above.
    ledger = FactLedger()
    source = SourceRecord(source_id="source", access_status="success", org_number=ORG)
    evidence = EvidenceRecord(source_id="source", evidence_id="evidence", org_number=ORG,
                              entity_verdict="VERIFIED",
                              evidence_text="Fixture candidate source; EUR 123; reporting year 2025.")
    fact = Fact(org_number=ORG, category=category, field=field, value=value, source_id="source",
                evidence_id="evidence", entity_verdict="VERIFIED", reporting_period="2025",
                currency="EUR", unit="units", subject_scope="legal_entity")
    if category == "financials":
        ledger.add_fact(fact, evidence, source)
        assert fact.status == "FAILED" and ledger.published_facts(ORG) == []
        # Renderer-only hypothetical DTO input: no publication is granted.
        ledger = SimpleNamespace(
            evidence={}, current_values=lambda org: {fact.fact_key(): fact},
            published_facts=lambda org: [fact], conflicting_facts=lambda org: [],
        )
    else:
        ledger.add_fact(fact, evidence, source)
        assert ledger.published_facts(ORG) == [fact]
    summary = build_summary(CompanyIdentity(organisation_number=ORG, legal_name="FIXTURE AS"),
                            ledger, Coverage(), [])
    assert f"[{fact.claim_id}]" in summary


def test_branch_renderer_cannot_attach_a_foreign_parent_from_legacy_preliminary_ledger():
    ledger = FactLedger()
    source = SourceRecord(source_id="source", access_status="success", org_number=ORG)
    evidence = EvidenceRecord(source_id="source", evidence_id="evidence", org_number=ORG,
                              entity_verdict="VERIFIED", evidence_text="Synthetic legacy candidate")
    fact = Fact(org_number=ORG, category="locations", field="branch", item_key=SUBUNIT,
                value={"name": "FOREIGN UNIT", "orgnr": SUBUNIT, "parent_orgnr": "984851006"},
                source_id="source", evidence_id="evidence", entity_verdict="VERIFIED")
    ledger.add_fact(fact, evidence, source)
    summary = build_summary(CompanyIdentity(organisation_number=ORG, legal_name="FIXTURE AS"),
                            ledger, Coverage(), [])
    assert "FOREIGN UNIT" not in summary and f"[{fact.claim_id}]" not in summary

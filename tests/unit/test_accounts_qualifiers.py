"""Official-schema-shaped synthetic accounts; not financial accuracy gold."""
import asyncio
from copy import deepcopy

import httpx
import pytest

from nordtrace.adapters.brreg import BrregAdapter
from nordtrace.core.budget import BudgetManager
from nordtrace.core.repository import Repository
from nordtrace.core.request_gateway import RequestGateway

ORG = "982463718"
BASE = {
    "virksomhet": {"organisasjonsnummer": ORG}, "regnskapstype": "SELSKAP", "valuta": "EUR",
    "regnskapsperiode": {"fraDato": "2025-01-01", "tilDato": "2025-12-31"},
    "resultatregnskapResultat": {"driftsresultat": {
        "driftsinntekter": {"sumDriftsinntekter": 0}, "driftsresultat": -12,
    }},
}


def collect(tmp_path, monkeypatch, payload):
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    repo = Repository(tmp_path / "accounts.db")
    async def execute():
        gateway = RequestGateway(BudgetManager(max_requests=1), repository=repo)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload)))
        try:
            return await BrregAdapter(gateway, gateway.budget).fetch_accounts(ORG, "fixture")
        finally:
            await gateway.aclose()
    try:
        result = asyncio.run(execute())
        assert repo.read_capture(result[2].source_id)[1]
        return result
    finally:
        repo.close()


@pytest.mark.parametrize("field,value", [
    ("valuta", None), ("valuta", ""), ("valuta", False),
    ("regnskapsperiode", {}),
    ("regnskapsperiode", {"fraDato": "2025-01-01"}),
    ("regnskapsperiode", {"tilDato": "2025-12-31"}),
    ("regnskapsperiode", {"fraDato": "2025-02-30", "tilDato": "2025-12-31"}),
    ("regnskapsperiode", {"fraDato": "2025-12-31", "tilDato": "2025-01-01"}),
    ("virksomhet", {}), ("virksomhet", {"organisasjonsnummer": "958973306"}),
    ("regnskapstype", "KONSERN"), ("regnskapstype", None),
])
def test_unresolved_qualifiers_abstain_instead_of_defaulting_or_manufacturing_identity(
    tmp_path, monkeypatch, field, value,
):
    document = deepcopy(BASE)
    document[field] = value
    evidence, facts, source, status = collect(tmp_path, monkeypatch, [document])
    assert facts == [] and evidence == []
    assert status == "ambiguous"
    assert source.error_detail


def test_legal_entity_accounts_do_not_lose_to_newer_group_accounts(tmp_path, monkeypatch):
    group = deepcopy(BASE)
    group["regnskapstype"] = "KONSERN"
    group["regnskapsperiode"] = {"fraDato": "2026-01-01", "tilDato": "2026-12-31"}
    group["resultatregnskapResultat"]["driftsresultat"]["driftsinntekter"]["sumDriftsinntekter"] = 999
    evidence, facts, source, status = collect(tmp_path, monkeypatch, [group, BASE])
    assert status == "found"
    revenue = next(f for f in facts if f.field == "revenue")
    assert revenue.value == "0" and revenue.currency == "EUR"
    assert revenue.reporting_period == "2025-01-01/2025-12-31"
    assert revenue.subject_scope == "legal_entity"
    assert revenue.retrieved_at == source.retrieved_at
    assert next(f for f in facts if f.field == "operating_result").value == "-12"
    assert evidence[0].entity_match_details["regnskapstype"] == "SELSKAP"


def test_same_period_competing_records_remain_ambiguous(tmp_path, monkeypatch):
    changed = deepcopy(BASE)
    changed["resultatregnskapResultat"]["driftsresultat"]["driftsinntekter"]["sumDriftsinntekter"] = 12
    evidence, facts, source, status = collect(tmp_path, monkeypatch, [BASE, changed])
    assert status == "ambiguous" and not facts and not evidence
    assert source.error_detail

@pytest.mark.parametrize("payload,expected,http_status", [
    ([BASE], "ambiguous", 200),
    ([{**BASE, "valuta": None}], "ambiguous", 200),
    ([None], "failed", 200),
    ({}, "blocked", 403),
    ({}, "not_available", 410),
])
def test_accounts_abstention_state_survives_canonical_finalization(
    tmp_path, monkeypatch, payload, expected, http_status,
):
    from nordtrace.core.models import ResearchRun
    from nordtrace.engine.pipeline import ResearchPipeline

    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    repo = Repository(tmp_path / "pipeline.db")
    run = ResearchRun(companies=[ORG])
    repo.create_run(run)
    def respond(request):
        if request.url.path.endswith("/enheter/" + ORG):
            return httpx.Response(200, json={"organisasjonsnummer": ORG, "navn": "FIXTURE AS"})
        if "/regnskap/" in request.url.path:
            return httpx.Response(http_status, json=payload)
        return httpx.Response(404)
    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=100))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()
    try:
        asyncio.run(execute())
        result = repo.get_result(run.run_id, ORG)
        assert not any(f.category == "financials" for f in result.facts)
        assert result.coverage["financials"] == expected
        attempt = next(item for item in result.refresh_outcomes if item.family == "financials")
        assert attempt.state == expected
        assert attempt.reason
    finally:
        repo.close()

def test_candidate_lexeme_replays_but_does_not_enable_financial_publication(tmp_path, monkeypatch):
    from nordtrace.core.evidence import resolve_pointer
    from nordtrace.core.financial import parse_accounts_json
    from nordtrace.core.ledger import CitationValidator

    evidence, facts, source, _ = collect(tmp_path, monkeypatch, [BASE])
    repo = Repository(tmp_path / "accounts.db")
    try:
        _, body = repo.read_capture(source.source_id)
        details = evidence[0].entity_match_details
        assert evidence[0].locator is None
        assert resolve_pointer(parse_accounts_json(body), details["field_pointer"]).lexeme == "0"
        assert details["raw_number_lexeme"] == "0"
        assert evidence[0].entity_match_details["unit_scale_basis"] == "unresolved"
        assert all(f.status == "EXTRACTED" for f in facts)
        validator = CitationValidator({source.source_id: source}, {e.evidence_id: e for e in evidence}, repo)
        assert all(not validator.validate(fact)[0] for fact in facts)
    finally:
        repo.close()

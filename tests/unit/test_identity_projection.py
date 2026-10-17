"""Structured profile fields must not bypass snapshot-backed claim publication."""

import asyncio

import httpx
import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.contracts import build_result, project_identity
from nordtrace.core.models import ResearchRun, utcnow
from nordtrace.core.repository import Repository
from nordtrace.engine.pipeline import ResearchPipeline

ORG = "982463718"


@pytest.mark.parametrize("corruption", [None, "employee_count", "legal_name", "registered_address"])
def test_company_projection_withholds_unbacked_fields_and_preserves_supported_zero(
    tmp_path, monkeypatch, corruption,
):
    repo = Repository(tmp_path / "structured.db")
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    document = {
        "organisasjonsnummer": ORG, "navn": "FIXTURE AS", "antallAnsatte": 0,
        "organisasjonsform": {"kode": "AS", "beskrivelse": "Unconverted form description"},
        "kapital": {"belop": True, "valuta": "NOK", "antallAksjer": True},
        "erIKonsern": False, "konkurs": False, "underAvvikling": False,
        "underTvangsavviklingEllerTvangsopplosning": False,
        "postadresse": {"adresse": ["Fixture postal box 1"], "postnummer": "0001", "kommune": "OSLO"},
        "forretningsadresse": {
            "adresse": ["Fixture road 1"], "postnummer": "0001", "poststed": "OSLO", "kommune": "OSLO",
        },
    }
    intermediate_rows = []
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    def respond(request):
        if request.url.path.endswith("/enheter/" + ORG):
            return httpx.Response(200, json=document)
        return httpx.Response(404)

    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=30))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        if corruption:
            original = pipeline.brreg._parse_entity

            def corrupt(*args):
                identity = original(*args)
                value = 999999 if corruption == "employee_count" else "UNSUPPORTED NAME AS"
                setattr(identity, corruption, value)
                return identity

            monkeypatch.setattr(pipeline.brreg, "_parse_entity", corrupt)
        fetch_branches = pipeline.brreg.fetch_underenheter

        async def inspect_intermediate_row(*args):
            current = repo.get_company(ORG)
            intermediate_rows.append(current)
            return await fetch_branches(*args)

        monkeypatch.setattr(pipeline.brreg, "fetch_underenheter", inspect_intermediate_row)
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()

    outcome = asyncio.run(execute())
    assert len(intermediate_rows) == 1
    assert intermediate_rows[0] is None, "A company row must remain unpublished until the atomic commit"
    result = repo.get_result(run.run_id, ORG)
    if corruption == "legal_name":
        assert result.company.legal_name == ""
        assert "UNSUPPORTED NAME AS" not in (result.summary or "")
    assert result.company.share_capital is None, "Boolean capital must not publish as monetary1.0"
    assert result.company.share_capital_currency is None
    assert result.company.number_of_shares is None
    if corruption == "employee_count":
        assert result.company.employee_count is None
    else:
        assert type(result.company.employee_count) is int and result.company.employee_count == 0
    supported = {fact.field: fact.value for fact in result.facts if fact.category == "identity"}
    for field, value in result.company.model_dump().items():
        if field in {"organisation_number", "last_verified_at", "unresolved_fields"}:
            continue
        if value is None or value == "" or value == "unknown":
            continue
        assert field in supported, f"Unbacked structured business field: {field}"
        assert value == supported[field]
    current = repo.get_company(ORG)
    assert current.share_capital is None and current.employee_count == result.company.employee_count
    assert "share_capital" in result.company.unresolved_fields
    assert "999999" not in (result.summary or "")
    assert result.company.municipality == "OSLO", "Unsupported address cannot erase a supported municipality"
    assert project_identity(result.company, result.conflicts, result.facts) == result.company
    # The serializer must use accepted evidence even if its acquisition DTO drifts later.
    outcome.identity.legal_name = "POST-ACQUISITION DRIFT AS"
    outcome.identity.employee_count = 999999
    rebuilt = build_result(outcome, run.run_id, BudgetManager(), run.started_at)
    assert rebuilt.company.legal_name == result.company.legal_name
    assert rebuilt.company.employee_count == result.company.employee_count
    assert repo.get_result(run.run_id, ORG) == result  # Rebuilding cannot rewrite history.
    repo.close()

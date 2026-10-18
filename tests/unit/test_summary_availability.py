"""Missing supported observations must not become assertions of business absence."""
import asyncio

import httpx
import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.ledger import FactLedger
from nordtrace.core.models import CompanyIdentity, Coverage, ResearchRun
from nordtrace.core.repository import Repository
from nordtrace.core.synthesis import build_summary
from nordtrace.engine.pipeline import ResearchPipeline

ORG = "982463718"


@pytest.mark.parametrize("state,phrase", [
    ("not_found", "not verified in this run"),
    ("not_available", "no supported observation available"),
    ("blocked", "verification blocked"),
    ("ambiguous", "evidence unresolved or conflicting"),
    ("failed", "verification failed"),
    ("not_applicable", "not applicable"),
])
def test_summary_unknowns_describe_verification_state_not_public_absence(state, phrase):
    identity = CompanyIdentity(organisation_number=ORG, legal_name="FIXTURE AS")
    coverage = Coverage(states=dict.fromkeys(
        ["financials", "leadership", "jobs", "recent_activity", "business_description"], state,
    ))
    summary = build_summary(identity, FactLedger(), coverage, [])
    assert f"Financials: {phrase}." in summary
    assert f"Annual accounts ({phrase})" in summary
    assert f"Job postings ({phrase})" in summary
    assert "not publicly available" not in summary
    assert "no dated public events found" not in summary
    assert "registry roles data" not in summary


def test_unknowns_use_final_refresh_states_and_keep_outage_diagnostics(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "summary.db")
    first = ResearchRun(companies=[ORG])
    repo.create_run(first)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    accounts = [{
        "virksomhet": {"organisasjonsnummer": ORG}, "regnskapstype": "SELSKAP", "valuta": "EUR",
        "regnskapsperiode": {"fraDato": "2025-01-01", "tilDato": "2025-12-31"},
        "resultatregnskapResultat": {"driftsresultat": {"driftsinntekter": {"sumDriftsinntekter": 0}}},
    }]
    blocked = False
    def respond(request):
        if request.url.path.endswith("/enheter/" + ORG):
            return httpx.Response(403) if blocked else httpx.Response(200, json={
                "organisasjonsnummer": ORG, "navn": "FIXTURE AS",
            })
        if "/regnskap/" in request.url.path:
            return httpx.Response(200, json=accounts)
        return httpx.Response(404)
    async def execute(run_id):
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=30,
                                    allowed_source_origins=["https://data.brreg.no"]))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            await pipeline.research_company(ORG, run_id)
        finally:
            await pipeline.aclose()
    try:
        asyncio.run(execute(first.run_id))
        result = repo.get_result(first.run_id, ORG)
        assert result.coverage["financials"] == "ambiguous"
        assert result.coverage["jobs"] == "blocked"
        assert "Annual accounts (evidence unresolved or conflicting)" in result.unknowns
        assert "Job postings (verification blocked)" in result.unknowns
        assert "not publicly available" not in result.summary
        assert not any(f.category == "financials" for f in result.facts)
        blocked = True
        second = ResearchRun(companies=[ORG])
        repo.create_run(second)
        asyncio.run(execute(second.run_id))
        unavailable = repo.get_result(second.run_id, ORG)
        assert unavailable.last_known
        assert any("last-known observations" in item for item in unavailable.unknowns)
        # Earlier persisted briefs stay immutable after a later source outage.
        assert repo.get_result(first.run_id, ORG).model_dump() == result.model_dump()
    finally:
        repo.close()

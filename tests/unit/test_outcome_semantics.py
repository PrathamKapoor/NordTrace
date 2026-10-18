"""Company availability follows observed research outcome, not coverage thresholds."""

import asyncio

import httpx
import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.contracts import batch_payload, build_result
from nordtrace.core.models import CompanyProfile, ResearchRun, utcnow
from nordtrace.core.repository import Repository
from nordtrace.engine.pipeline import CompanyOutcome, ResearchPipeline

ORG = "982463718"


@pytest.mark.parametrize("deleted", [False, True])
def test_identity_only_completion_is_available_with_explicit_reason(tmp_path, monkeypatch, deleted):
    repo = Repository(tmp_path / "identity-only.db")
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    document = {"organisasjonsnummer": ORG, "navn": "FIXTURE AS"}
    if deleted:
        document["slettedato"] = "2025-01-01"
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    def respond(request):
        if request.url.path.endswith("/enheter/" + ORG):
            return httpx.Response(200, json=document)
        return httpx.Response(404)

    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=30))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()

    outcome = asyncio.run(execute())
    assert outcome.terminal_state == "available"
    frozen = repo.get_result(run.run_id, ORG)
    assert frozen.status_reason == "research_completed"
    assert frozen.coverage["identity"] == "found"
    assert frozen.coverage["financials"] != "found"
    if deleted:
        assert frozen.company.status == "deleted"
    # Interfaces use the same stored canonical reason, including historical reads.
    from fastapi.testclient import TestClient

    from nordtrace.api.app import app

    monkeypatch.setattr("nordtrace.api.app.get_repo", lambda: repo)
    with TestClient(app) as client:
        historical = client.get(f"/companies/{ORG}?run_id={run.run_id}").json()
        assert historical["status_reason"] == "research_completed"
    export = batch_payload(run, [frozen], [{"index": 0, "supplied": ORG, "result_key": ORG}])
    assert export["results"][0]["status_reason"] == frozen.status_reason
    repo.close()


@pytest.mark.parametrize("state,code", [
    ("available", "research_completed"),
    ("not_available", "entity_not_found"),
    ("blocked", "registry_blocked"),
    ("ambiguous", "entity_ambiguous"),
    ("not_applicable", "invalid_organisation_number"),
    ("failed", "company_deadline_exceeded"),
])
def test_serializer_retains_actual_reason_for_every_terminal_state(state, code):
    outcome = CompanyOutcome(org_number=ORG, terminal_state=state)
    if state != "available":
        outcome.error_code, outcome.error = code, "Fixture terminal reason."
    result = build_result(outcome, "fixture", BudgetManager(), utcnow().isoformat())
    assert result.status_reason == code


def test_legacy_reason_stays_unknown_instead_of_being_inferred():
    historical = CompanyProfile.model_validate({
        "schema_version": "1.1", "run_id": "historical", "organisation_number": ORG,
        "status": "not_available", "coverage": {"identity": "found"},
    })
    assert historical.status_reason is None


@pytest.mark.parametrize("cap,reason,stage", [
    (1, "request_budget_exhausted", "branches"), (8, "acquisition_budget_limited", "website"),
])
def test_budget_truncated_identity_result_records_incomplete_execution(
    tmp_path, monkeypatch, cap, reason, stage,
):
    repo = Repository(tmp_path / "limited.db")
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=cap))

        def respond(request):
            if request.url.path.endswith("/enheter/" + ORG):
                return httpx.Response(200, json={"organisasjonsnummer": ORG, "navn": "FIXTURE AS",
                                                 "hjemmeside": "https://fixture.example"})
            return httpx.Response(404)

        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()

    outcome = asyncio.run(execute())
    assert outcome.terminal_state == "failed"
    frozen = repo.get_result(run.run_id, ORG)
    assert frozen.status_reason == reason
    assert frozen.errors[0].code == reason
    assert frozen.facts and frozen.company.legal_name == "FIXTURE AS"
    assert stage in frozen.errors[0].message
    repo.close()


@pytest.mark.parametrize("expired", [False, True])
def test_direct_pipeline_budget_gate_reports_typed_reason(tmp_path, expired):
    repo = Repository(tmp_path / "empty-budget.db")
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)

    async def execute():
        budget = BudgetManager(max_requests=1 if expired else 0, max_runtime_sec=1)
        if expired:
            budget.runtime.started_at -= 2
        pipeline = ResearchPipeline(repo, budget)
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()

    outcome = asyncio.run(execute())
    result = repo.get_result(run.run_id, ORG)
    expected = "deadline_exceeded" if expired else "request_budget_exhausted"
    assert outcome.terminal_state == "failed" and result.status_reason == expected
    assert result.research_metadata.request_count == 0
    repo.close()


@pytest.mark.parametrize("self_link", [False, True])
def test_ignored_homepage_self_link_cannot_be_reported_as_budget_skip(tmp_path, monkeypatch, self_link):
    repo = Repository(tmp_path / "self-link.db")
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    calls = []
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    def respond(request):
        calls.append(str(request.url))
        if request.url.path.endswith("/enheter/" + ORG):
            return httpx.Response(200, json={"organisasjonsnummer": ORG, "navn": "FIXTURE AS",
                                             "hjemmeside": "https://fixture.example/"})
        if request.url.host == "fixture.example":
            if request.url.path == "/":
                return httpx.Response(302, headers={"location": "/about"})
            if request.url.path == "/about":
                link = '<a href="https://fixture.example/">Home</a>' if self_link else ""
                return httpx.Response(200, text=f"<p>FIXTURE AS Org.nr. {ORG}</p>{link}")
        return httpx.Response(404)

    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=10, max_runtime_sec=10))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()

    outcome = asyncio.run(execute())
    # Four registry operations, robots, homepage and its redirect. NAV is a
    # local policy block, so it cannot consume a request reservation.
    assert len(calls) == 7
    assert repo.get_result(run.run_id, ORG).research_metadata.request_count == 7
    assert all("arbeidsplassen.nav.no" not in url for url in calls)
    assert outcome.terminal_state == "available"
    assert repo.get_result(run.run_id, ORG).status_reason == "research_completed"
    repo.close()

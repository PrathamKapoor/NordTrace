"""Persisted company assertions and verification times must agree with evidence."""

import asyncio
from datetime import datetime

import httpx
import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.models import ResearchRun, utcnow
from nordtrace.core.repository import Repository
from nordtrace.engine.pipeline import ResearchPipeline

ORG = "982463718"
CAPTURE_TIME = "2026-01-01T12:00:00+00:00"


def research(repo, run, monkeypatch):
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    def respond(request):
        if request.url.path.endswith("/enheter/" + ORG):
            return httpx.Response(200, json={
                "organisasjonsnummer": ORG, "navn": "FIXTURE AS", "antallAnsatte": 0,
            })
        return httpx.Response(404)

    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=30))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()

    return asyncio.run(execute())


@pytest.mark.parametrize("field, value", [
    ("legal_name", "UNSUPPORTED AS"), ("employee_count", 999999),
    ("share_capital", 999999.0), ("is_part_of_concern", False),
])
def test_publisher_rejects_company_drift_after_canonical_build(tmp_path, monkeypatch, field, value):
    repo = Repository(tmp_path / "structured-boundary.db")
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    original = repo.publish_result

    def drift(result, **kwargs):
        setattr(result.company, field, value)
        return original(result, **kwargs)

    monkeypatch.setattr(repo, "publish_result", drift)
    try:
        with pytest.raises(ValueError, match="structured identity"):
            research(repo, run, monkeypatch)
        assert repo.get_result(run.run_id, ORG) is None
        assert repo.get_company(ORG) is None
        assert repo.get_run(run.run_id).company_states == {}
        assert repo.conn.execute("SELECT COUNT(*) FROM source_captures").fetchone()[0] > 0
    finally:
        repo.close()


def test_identity_time_compares_actual_instants_and_ignores_other_subjects_and_families():
    from nordtrace.core.contracts import project_identity
    from nordtrace.core.models import CompanyIdentity, Fact

    # Projection arithmetic only; these constructed facts are not source-verification fixtures.
    facts = [Fact(
        org_number=org, category=category, field=field, value=value, status="PUBLISHED",
        source_id="fixture", evidence_id="fixture", subject_scope="legal_entity", retrieved_at=observed,
    ) for org, category, field, value, observed in [
        (ORG, "identity", "legal_name", "FIXTURE AS", "2026-01-01T11:30:00+02:00"),
        (ORG, "identity", "employee_count", 0, "2026-01-01T10:00:00+00:00"),
        ("958973306", "identity", "legal_name", "OTHER AS", "2099-01-01T00:00:00+00:00"),
        (ORG, "jobs", "careers_url", "https://example.no/jobs", "2099-01-01T00:00:00+00:00"),
    ]]
    identity = CompanyIdentity(organisation_number=ORG, legal_name="FIXTURE AS")
    projected = project_identity(identity, [], facts)
    assert projected.last_verified_at == "2026-01-01T10:00:00+00:00"
    assert projected.employee_count == 0


@pytest.mark.parametrize("timestamp", [None, "invalid-time", "2026-01-01T12:00:00"])
def test_unknown_identity_time_cannot_fall_back_to_parse_time(timestamp):
    from nordtrace.core.contracts import project_identity
    from nordtrace.core.models import CompanyIdentity, Fact

    identity = CompanyIdentity(
        organisation_number=ORG, legal_name="FIXTURE AS", last_verified_at="2099-01-01T00:00:00+00:00",
    )
    fact = Fact(
        org_number=ORG, category="identity", field="legal_name", value="FIXTURE AS", status="PUBLISHED",
        source_id="fixture", evidence_id="fixture", subject_scope="legal_entity", retrieved_at=timestamp,
    )
    assert project_identity(identity, [], [fact]).last_verified_at is None


@pytest.mark.parametrize("reverse", [False, True])
def test_corroborating_observation_order_cannot_change_identity_time(reverse):
    from nordtrace.core.contracts import project_identity
    from nordtrace.core.models import CompanyIdentity, Fact

    facts = [Fact(
        org_number=ORG, category="identity", field="legal_name", value="FIXTURE AS", status="PUBLISHED",
        source_id=str(index), evidence_id=str(index), subject_scope="legal_entity", retrieved_at=timestamp,
    ) for index, timestamp in enumerate(["2026-10-17T00:00:00+00:00", CAPTURE_TIME])]
    if reverse:
        facts.reverse()
    identity = CompanyIdentity(organisation_number=ORG, legal_name="FIXTURE AS")
    assert project_identity(identity, [], facts).last_verified_at == "2026-10-17T00:00:00+00:00"


@pytest.mark.parametrize("view", ["canonical", "company_index"])
def test_identity_verification_uses_observation_time(tmp_path, monkeypatch, view):
    repo = Repository(tmp_path / "freshness.db")
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    # Retained evidence cutoff intentionally precedes parsing/publication.
    monkeypatch.setattr("nordtrace.core.request_gateway.utcnow", lambda: datetime.fromisoformat(CAPTURE_TIME))
    try:
        research(repo, run, monkeypatch)
        result = repo.get_result(run.run_id, ORG)
        assert all(fact.retrieved_at == CAPTURE_TIME for fact in result.facts)
        if view == "canonical":
            assert result.company.last_verified_at == CAPTURE_TIME
        else:
            row = repo.conn.execute(
                "SELECT last_verified_at FROM companies WHERE org_number=?", (ORG,),
            ).fetchone()
            assert row[0] == CAPTURE_TIME
        assert repo.get_result(run.run_id, ORG).research_metadata.completed_at != CAPTURE_TIME
    finally:
        repo.close()


def test_cache_hit_preserves_the_original_captured_retrieval_timestamp(tmp_path, monkeypatch):
    from nordtrace.core.request_gateway import RequestGateway

    repo = Repository(tmp_path / "cache-time.db")
    budget = BudgetManager(max_requests=2)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    monkeypatch.setattr("nordtrace.core.request_gateway.utcnow", lambda: datetime.fromisoformat(CAPTURE_TIME))
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"organisasjonsnummer": ORG, "navn": "FIXTURE AS"})

    async def execute():
        # Explicitly retain the simulated older cutoff; no hidden live revalidation.
        gateway = RequestGateway(budget, cache_ttl_sec=1e12, repository=repo)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            url = "https://data.brreg.no/enhetsregisteret/api/enheter/" + ORG
            original = await gateway.fetch(url, company=ORG)
            cached = await gateway.fetch(url, company=ORG)
            assert cached.cache_hit and not original.cache_hit
            assert original.retrieved_at == cached.retrieved_at == CAPTURE_TIME
            assert repo.read_capture(cached.source_id)[0].retrieved_at == CAPTURE_TIME
        finally:
            await gateway.aclose()

    try:
        asyncio.run(execute())
        assert len(calls) == budget.requests.total_used == 1
    finally:
        repo.close()

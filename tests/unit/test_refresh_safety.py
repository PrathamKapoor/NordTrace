"""Outages and incomplete extraction cannot establish a business fact's removal."""

import asyncio

import httpx
import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.changes import detect_changes
from nordtrace.core.models import Fact, ResearchRun, utcnow
from nordtrace.core.repository import Repository
from nordtrace.engine.pipeline import ResearchPipeline

ORG = "982463718"


def test_missing_published_observation_is_not_affirmative_removal():
    before = Fact(
        org_number=ORG, category="identity", field="employee_count", value=12,
        normalized_value=12, source_id="prior-source", evidence_id="prior-evidence",
        status="PUBLISHED", entity_verdict="VERIFIED", subject_scope="legal_entity",
    )
    for source_ok in (False, True):
        changes = detect_changes(ORG, "refresh", [before], [], current_sources_ok=source_ok)
        assert [change.change_type for change in changes] == ["SOURCE_UNAVAILABLE"]
        assert changes[0].previous_source_id == "prior-source"
        assert changes[0].current_value is None


@pytest.mark.parametrize("refresh_kind", ["blocked", "incomplete", "failed", "not_available"])
def test_real_pipeline_retains_supported_history_through_outage_then_recovery(
    tmp_path, monkeypatch, refresh_kind,
):
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    repo = Repository(tmp_path / "refresh.db")
    runs = []
    entity_url = "https://data.brreg.no/enhetsregisteret/api/enheter/" + ORG

    async def execute():
        profiles = []
        for stage in ("initial", refresh_kind, "recovery"):
            run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
            runs.append(run)
            repo.create_run(run)

            def respond(request, stage=stage):
                if str(request.url) == entity_url:
                    if stage == "blocked":
                        return httpx.Response(403)
                    if stage == "not_available":
                        return httpx.Response(404)
                    if stage == "failed":
                        return httpx.Response(200, content=b"not valid registry JSON")
                    document = {"organisasjonsnummer": ORG, "navn": "TARGET AS"}
                    if stage != "incomplete":
                        document["antallAnsatte"] = 12
                    return httpx.Response(200, json=document)
                return httpx.Response(404)

            pipeline = ResearchPipeline(repo, BudgetManager(max_requests=30))
            pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            try:
                await pipeline.research_company(ORG, run.run_id)
                profiles.append(repo.get_result(run.run_id, ORG))
            finally:
                await pipeline.aclose()
        return profiles

    first, stale, recovered = asyncio.run(execute())
    assert len(first.facts) == 2
    original = next(fact for fact in first.facts if fact.field == "employee_count")
    assert all(change.change_type != "RETRACTED" for change in stale.changes)
    last_known = next(fact for fact in stale.last_known if fact.field == "employee_count")
    assert last_known.status == "SOURCE_UNAVAILABLE"
    assert last_known.fact_id == original.fact_id and last_known.run_id == runs[0].run_id
    assert last_known.retrieved_at == original.retrieved_at and last_known.value == 12
    assert last_known.claim_id not in {fact.claim_id for fact in stale.facts}
    assert stale.previous_run_id == runs[0].run_id
    assert {change.change_type for change in stale.changes} <= {"SOURCE_UNAVAILABLE", "UNCHANGED"}
    assert any(item.requested_url == entity_url for item in stale.refresh_outcomes)
    attempt = next(item for item in stale.refresh_outcomes if item.requested_url == entity_url)
    assert attempt.completeness == "unknown"
    assert attempt.state == ("available" if refresh_kind == "incomplete" else refresh_kind)
    assert "last-known" in stale.summary.lower()
    sources = {source.source_id: source for source in stale.sources}
    evidence = {item.evidence_id: item for item in stale.evidence}
    assert evidence[last_known.evidence_id].source_id == last_known.source_id
    assert sources[last_known.source_id].retrieved_at == original.retrieved_at
    assert repo.read_capture(last_known.source_id)[1]
    assert recovered.last_known == []
    assert {change.change_type for change in recovered.changes} == {"UNCHANGED"}
    for change in recovered.changes:
        assert change.previous_evidence_id in {item.evidence_id for item in recovered.evidence}
        assert change.current_evidence_id in {item.evidence_id for item in recovered.evidence}
    # Subsequent observations cannot change either historical envelope.
    assert repo.get_result(runs[0].run_id, ORG).model_dump() == first.model_dump()
    assert repo.get_result(runs[1].run_id, ORG).model_dump() == stale.model_dump()
    from fastapi.testclient import TestClient

    from nordtrace.api.app import app

    monkeypatch.setattr("nordtrace.api.app.get_repo", lambda: repo)
    with TestClient(app) as api:
        historical = api.get(f"/companies/{ORG}?run_id={runs[1].run_id}").json()
        assert historical["run_id"] == runs[1].run_id
        assert historical["last_known"] == stale.model_dump(mode="json")["last_known"]
    repo.close()


def test_same_timestamp_completed_predecessor_is_available_but_concurrent_completion_is_excluded(tmp_path):
    from nordtrace.core.models import CompanyProfile

    repo = Repository(tmp_path / "ordering.db")
    timestamp = "2026-01-01T00:00:00+00:00"
    first, concurrent, current = [ResearchRun(companies=[ORG], started_at=timestamp) for _ in range(3)]
    repo.create_run(first)
    repo.save_result(CompanyProfile(run_id=first.run_id, organisation_number=ORG))
    repo.create_run(concurrent)
    repo.create_run(current)
    repo.save_result(CompanyProfile(run_id=concurrent.run_id, organisation_number=ORG))
    assert repo.previous_result(ORG, current.run_id).run_id == first.run_id
    repo.close()


def test_previous_result_never_reads_a_later_run(tmp_path):
    from nordtrace.core.models import CompanyProfile

    repo = Repository(tmp_path / "cutoff.db")
    older, current, future = [ResearchRun(companies=[ORG], started_at=date) for date in (
        "2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00", "2026-03-01T00:00:00+00:00",
    )]
    repo.create_run(older)
    repo.save_result(CompanyProfile(run_id=older.run_id, organisation_number=ORG))
    repo.create_run(current)
    repo.create_run(future)
    repo.save_result(CompanyProfile(run_id=future.run_id, organisation_number=ORG))
    assert repo.previous_result(ORG, current.run_id).run_id == older.run_id
    assert repo.previous_result(ORG, older.run_id) is None
    repo.close()

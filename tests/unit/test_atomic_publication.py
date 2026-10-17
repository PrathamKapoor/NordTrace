"""A production company publication is all-or-nothing; captures remain retained."""

import asyncio
import sqlite3

import httpx
import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.models import CompanyIdentity, CompanyProfile, ResearchRun, utcnow
from nordtrace.core.repository import Repository, TaskOwnershipError
from nordtrace.engine.pipeline import ResearchPipeline

ORG = "982463718"


def execute(repo, run, monkeypatch, identity_status=200, legal_name="FIXTURE AS"):
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    def respond(request):
        if request.url.path.endswith("/enheter/" + ORG):
            return httpx.Response(identity_status, json={"organisasjonsnummer": ORG, "navn": legal_name})
        return httpx.Response(404)

    async def research():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=30))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()

    return asyncio.run(research())


@pytest.mark.parametrize("failure_point", ["facts", "envelope"])
@pytest.mark.parametrize("existing", [False, True])
def test_failure_after_a_real_write_rolls_back_every_publication_row(
    tmp_path, monkeypatch, failure_point, existing,
):
    repo = Repository(tmp_path / "rollback.db")
    old_result = None
    old_company = None
    if existing:
        old_run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
        repo.create_run(old_run)
        old_company = CompanyIdentity(organisation_number=ORG, legal_name="OLD COMPANY AS")
        repo.upsert_company(old_company, old_run.run_id)
        old_result = CompanyProfile(
            run_id=old_run.run_id, organisation_number=ORG, company=old_company, status="available",
        )
        repo.save_result(old_result)
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    method = "insert_facts_bulk" if failure_point == "facts" else "save_result"
    original = getattr(repo, method)

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected publication failure")

    monkeypatch.setattr(repo, method, fail_after_write)
    try:
        with pytest.raises(RuntimeError, match="injected publication failure"):
            execute(repo, run, monkeypatch)
        assert repo.get_result(run.run_id, ORG) is None
        assert repo.get_company(ORG) == old_company
        if existing:
            assert repo.get_result(old_result.run_id, ORG) == old_result
        for table in ("sources", "evidence", "facts", "changes"):
            assert repo.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
        assert repo.get_run(run.run_id).company_states == {}
        assert repo.conn.execute("SELECT COUNT(*) FROM source_captures").fetchone()[0] > 0
        assert repo.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        repo.close()


def test_foreign_lease_rejection_cannot_leave_current_company_or_ledger_rows(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "ownership.db")
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    assert repo.try_claim_company(run.run_id, ORG, "other-owner", 60)
    try:
        with pytest.raises(TaskOwnershipError):
            execute(repo, run, monkeypatch)
        assert repo.get_company(ORG) is None
        assert repo.get_result(run.run_id, ORG) is None
        assert repo.get_facts(ORG) == []
        assert repo.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
        assert repo.conn.execute("SELECT owner FROM company_claims").fetchone()[0] == "other-owner"
    finally:
        repo.close()


def test_separate_reader_cannot_observe_partial_publication(tmp_path, monkeypatch):
    path = tmp_path / "visibility.db"
    repo = Repository(path)
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    original = repo.insert_facts_bulk
    observations = []

    def inspect_after_write(*args, **kwargs):
        original(*args, **kwargs)
        with sqlite3.connect(path) as observer:
            tables = ("companies", "sources", "evidence", "facts", "company_results")
            observations.append([observer.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                                 for table in tables])

    monkeypatch.setattr(repo, "insert_facts_bulk", inspect_after_write)
    try:
        execute(repo, run, monkeypatch)
        assert observations == [[0, 0, 0, 0, 0]]
        result = repo.get_result(run.run_id, ORG)
        assert result.company.legal_name == "FIXTURE AS"
        assert len(result.facts) == 1
        assert len(repo.get_facts(ORG, run.run_id)) == 1
    finally:
        repo.close()


@pytest.mark.parametrize("drift", ["hidden_observation", "evidence_collision"])
def test_publication_rejects_observation_disagreement_and_evidence_id_reuse(tmp_path, monkeypatch, drift):
    repo = Repository(tmp_path / "drift.db")
    old_run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(old_run)
    execute(repo, old_run, monkeypatch)
    old_result = repo.get_result(old_run.run_id, ORG)
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    original = ResearchPipeline._finalize_ledger

    def drift_after_validation(self, outcome, *args):
        original(self, outcome, *args)
        if drift == "hidden_observation":
            outcome.observations.append(outcome.facts[0].model_copy(update={
                "fact_id": "unrepresented-published-observation", "value": "UNSUPPORTED VALUE",
            }))
        else:
            old_id = old_result.facts[0].evidence_id
            replaced_id = outcome.facts[0].evidence_id
            for item in outcome.evidence:
                if item.evidence_id == replaced_id:
                    item.evidence_id = old_id
            for fact in outcome.observations:
                if fact.evidence_id == replaced_id:
                    fact.evidence_id = old_id

    monkeypatch.setattr(ResearchPipeline, "_finalize_ledger", drift_after_validation)
    try:
        with pytest.raises(ValueError):
            execute(repo, run, monkeypatch)
        assert repo.get_result(run.run_id, ORG) is None
        assert repo.get_result(old_run.run_id, ORG) == old_result
        assert repo.get_evidence(old_result.facts[0].evidence_id).source_id == old_result.facts[0].source_id
        assert repo.get_facts(ORG, run.run_id) == []
    finally:
        repo.close()


def test_no_identity_refresh_keeps_failure_projections_and_prior_company(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "failed-refresh.db")
    previous = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(previous)
    execute(repo, previous, monkeypatch)
    prior_identity = repo.get_company(ORG)
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    try:
        execute(repo, run, monkeypatch, identity_status=403)
        result = repo.get_result(run.run_id, ORG)
        assert result.status == "blocked" and result.company is None
        assert result.last_known and result.changes
        projected_changes = [item for item in repo.get_changes(ORG) if item.run_id == run.run_id]
        assert projected_changes == result.changes
        sources = repo.get_sources(ORG, run.run_id)
        assert len(sources) == 1 and sources[0].http_status == 403
        assert repo.get_company(ORG) == prior_identity
    finally:
        repo.close()


@pytest.mark.parametrize("drift", ["collision", "foreign_subject", "foreign_run", "duplicate"])
def test_changes_cannot_replace_history_or_disagree_with_publication(tmp_path, monkeypatch, drift):
    from nordtrace.engine.pipeline import apply_refresh

    repo = Repository(tmp_path / "change-drift.db")
    previous = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(previous)
    execute(repo, previous, monkeypatch, legal_name="OLD AS")
    old_result = repo.get_result(previous.run_id, ORG)
    prior_changes = repo.get_changes(ORG)
    assert prior_changes
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)

    def drift_after_refresh(repository, outcome, run_id):
        apply_refresh(repository, outcome, run_id)
        assert outcome.changes
        change = outcome.changes[0]
        if drift == "collision":
            change.change_id = prior_changes[0].change_id
        elif drift == "foreign_subject":
            change.org_number = "958973306"
        elif drift == "foreign_run":
            change.run_id = previous.run_id
        else:
            outcome.changes.append(change.model_copy(deep=True))

    monkeypatch.setattr("nordtrace.engine.pipeline.apply_refresh", drift_after_refresh)
    try:
        with pytest.raises(ValueError, match="change"):
            execute(repo, run, monkeypatch, legal_name="NEW AS")
        assert repo.get_result(run.run_id, ORG) is None
        assert repo.get_result(previous.run_id, ORG) == old_result
        assert repo.get_changes(ORG) == prior_changes
        assert repo.get_company(ORG).legal_name == "OLD AS"
    finally:
        repo.close()

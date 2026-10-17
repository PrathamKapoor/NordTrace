"""Canonical-result regressions; synthetic outcomes are not live research."""

import asyncio
import json
import sqlite3

import pytest
from click.testing import CliRunner

from nordtrace.cli import cli
from nordtrace.core.budget import BudgetManager
from nordtrace.core.models import CompanyIdentity, CompanyProfile, ResearchRun, utcnow
from nordtrace.core.repository import Repository
from nordtrace.engine.pipeline import CompanyOutcome, ResearchPipeline
from nordtrace.engine.runner import BatchRunner


def test_batch_exports_invalid_inputs_instead_of_dropping_them(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "batch.db")
    monkeypatch.setattr("nordtrace.cli._repo", lambda: repo)
    inputs = tmp_path / "input.csv"
    inputs.write_text("orgnr\nbad\n12345\nbad\n", encoding="utf-8")
    output = tmp_path / "results.json"
    result = CliRunner().invoke(cli, ["batch", str(inputs), "--output", str(output)])
    assert output.exists(), result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert len(payload["results"]) == 2
    assert [entry["result_key"] for entry in payload["inputs"]] == ["bad", "12345", "bad"]
    assert all(entry["status"] == "not_applicable" for entry in payload["results"])
    assert all(entry["errors"][0]["code"] == "invalid_organisation_number" for entry in payload["results"])
    assert result.exit_code == 2


def test_resume_only_invokes_unfinished_companies(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "resume.db")
    run = ResearchRun(companies=["982463718", "958973306"], started_at=utcnow().isoformat())
    repo.create_run(run)
    BudgetManager().bind_run(repo, run.run_id, initialize=True)
    repo.mark_company_state(run.run_id, "982463718", "available")
    calls = []

    async def research(self, org, run_id):
        calls.append(org)
        return CompanyOutcome(org_number=org, terminal_state="not_available")

    monkeypatch.setattr(ResearchPipeline, "research_company", research)
    resumed = asyncio.run(BatchRunner(repo).run_batch(run.companies, resume_run_id=run.run_id))
    assert calls == ["958973306"]
    assert resumed.company_states == {"982463718": "available", "958973306": "not_available"}
    repo.close()


def test_one_company_exception_does_not_omit_other_results(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "failures.db")

    async def research(self, org, run_id):
        if org == "982463718":
            raise RuntimeError("injected acquisition failure")
        return CompanyOutcome(org_number=org, terminal_state="not_available")

    monkeypatch.setattr(ResearchPipeline, "research_company", research)
    run = asyncio.run(BatchRunner(repo).run_batch(["982463718", "958973306"]))
    assert run.company_states == {"982463718": "failed", "958973306": "not_available"}
    results = repo.get_results(run.run_id)
    assert len(results) == 2
    assert results[0].errors[0].code == "research_failed"
    repo.close()


def test_canonical_history_retains_summary_identity_and_failure_without_company(tmp_path):
    from nordtrace.api.app import _company_payload

    repo = Repository(tmp_path / "history.db")
    for run_id in ("old", "new", "missing"):
        repo.create_run(ResearchRun(run_id=run_id, companies=["982463718"]))
    old = CompanyProfile(
        run_id="old", organisation_number="982463718", status="available",
        company=CompanyIdentity(organisation_number="982463718", legal_name="OLD LEGAL NAME AS"),
        summary="Old verified observations.", coverage={"identity": "found"},
    )
    repo.save_result(old)
    new = old.model_copy(deep=True)
    new.run_id = "new"
    new.company.legal_name = "NEW LEGAL NAME AS"
    new.summary = "New verified observations."
    repo.upsert_company(new.company, "new")
    repo.save_result(new)
    missing = CompanyProfile(run_id="missing", organisation_number="958973306", status="not_available")
    repo.save_result(missing)
    assert _company_payload(repo, "982463718", "old")["summary"] == "Old verified observations."
    assert _company_payload(repo, "982463718", "old")["company"]["legal_name"] == "OLD LEGAL NAME AS"
    assert _company_payload(repo, "982463718")["summary"] == "New verified observations."
    assert repo.get_result("missing", "958973306").status == "not_available"
    with pytest.raises(ValueError, match="immutable"):
        repo.save_result(old.model_copy(update={"summary": "altered history"}))
    repo.close()


def test_pipeline_persists_invalid_outcome_without_identity(tmp_path):
    repo = Repository(tmp_path / "invalid.db")
    run = ResearchRun(companies=["bad"])
    repo.create_run(run)

    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=0))
        try:
            return await pipeline.research_company("bad", run.run_id)
        finally:
            await pipeline.aclose()

    outcome = asyncio.run(execute())
    assert outcome.terminal_state == "not_applicable"
    result = repo.get_result(run.run_id, "bad")
    assert result.errors[0].code == "invalid_organisation_number"
    assert result.company is None
    repo.close()


def test_api_batch_tracks_returned_run_and_preserves_every_input(tmp_path):
    from fastapi.testclient import TestClient

    from nordtrace.api.app import app, get_repo

    repo = Repository(tmp_path / "api-contract.db")
    app.dependency_overrides[get_repo] = lambda: repo
    # get_repo is also called by worker functions; replace that shared boundary.
    from unittest.mock import patch

    with patch("nordtrace.api.app.get_repo", return_value=repo), TestClient(app) as client:
        started = client.post("/batch", json={"organisation_numbers": ["bad", "12345", "bad"]})
        assert started.status_code == 200
        run_id = started.json()["run_id"]
        result = client.get(f"/research/{run_id}").json()
        assert result["state"] == "completed"
        assert result["company_states"] == {"bad": "not_applicable", "12345": "not_applicable"}
        assert len(result["results"]) == 2
        assert len(repo.list_runs()) == 1
        assert len(repo.get_run_inputs(run_id)) == 3
    app.dependency_overrides.clear()
    repo.close()


def test_migration_backs_up_legacy_database_and_preserves_records(tmp_path):
    from nordtrace.core.repository import _SCHEMA

    database = tmp_path / "legacy.db"
    identity = CompanyIdentity(organisation_number="982463718", legal_name="LEGACY AS")
    with sqlite3.connect(database) as connection:
        connection.executescript(_SCHEMA)
        connection.execute(
            "INSERT INTO companies (org_number, legal_name, identity_json) VALUES (?,?,?)",
            ("982463718", "LEGACY AS", identity.model_dump_json()),
        )
        connection.execute(
            "INSERT INTO snapshots VALUES ('legacy-hash', 'https://example.no', 'old', 'old bytes')"
        )
    repo = Repository(database)
    assert repo.get_company("982463718").legal_name == "LEGACY AS"
    assert repo.get_snapshot("legacy-hash", "https://example.no") == "old bytes"
    assert repo.conn.execute("PRAGMA user_version").fetchone()[0] == 6
    backups = list(tmp_path.glob("legacy.db.pre-v1-*.bak"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 0
        assert backup.execute("SELECT legal_name FROM companies").fetchone()[0] == "LEGACY AS"
    repo.close()
    reopened = Repository(database)
    assert len(list(tmp_path.glob("legacy.db.pre-v1-*.bak"))) == 1
    reopened.close()


def test_versioned_validator_rejects_dangling_claim_and_invalid_state():
    from nordtrace.validate import validate_result

    malformed = {
        "schema_version": "1.1", "run_id": "r", "organisation_number": "982463718",
        "status": "available", "facts": [{
            "fact_id": "f", "org_number": "982463718", "category": "business_description",
            "field": "description", "value": "Unsupported", "source_id": "missing", "evidence_id": "missing",
        }],
    }
    assert any("dangling" in error for error in validate_result(malformed))
    malformed["facts"] = []
    malformed["status"] = "pretend_success"
    assert any("terminal" in error for error in validate_result(malformed))


def test_repeating_completed_pipeline_call_is_idempotent(tmp_path):
    repo = Repository(tmp_path / "repeat.db")
    run = ResearchRun(companies=["bad"])
    repo.create_run(run)

    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=0))
        try:
            first = await pipeline.research_company("bad", run.run_id)
            payload = repo.get_result(run.run_id, "bad").model_dump_json()
            second = await pipeline.research_company("bad", run.run_id)
            assert second.terminal_state == first.terminal_state
            assert repo.get_result(run.run_id, "bad").model_dump_json() == payload
        finally:
            await pipeline.aclose()

    asyncio.run(execute())
    repo.close()


def test_concurrent_resume_does_not_repeat_work_or_corrupt_checkpoint(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "concurrent.db")
    run = ResearchRun(companies=["982463718"], started_at=utcnow().isoformat())
    repo.create_run(run)
    BudgetManager().bind_run(repo, run.run_id, initialize=True)
    calls = []

    async def acquire(self, org, run_id):
        calls.append(org)
        await asyncio.sleep(0.05)
        return CompanyOutcome(
            org_number=org, terminal_state="available",
            identity=CompanyIdentity(organisation_number=org, legal_name="FIXTURE AS"),
        )

    monkeypatch.setattr(ResearchPipeline, "_research_company", acquire)

    async def execute():
        await asyncio.gather(
            BatchRunner(repo).run_batch(run.companies, resume_run_id=run.run_id),
            BatchRunner(repo).run_batch(run.companies, resume_run_id=run.run_id),
        )

    asyncio.run(execute())
    assert calls == ["982463718"]
    assert repo.get_run(run.run_id).company_states == {"982463718": "available"}
    assert repo.get_result(run.run_id, "982463718").status == "available"
    repo.close()


def test_api_single_execution_exception_has_a_failure_envelope(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from nordtrace.api.app import app

    repo = Repository(tmp_path / "api-failure.db")
    monkeypatch.setattr("nordtrace.api.app.get_repo", lambda: repo)

    async def fail(self, org, run_id):
        raise RuntimeError("injected pipeline failure")

    monkeypatch.setattr(ResearchPipeline, "research_company", fail)
    with TestClient(app) as client:
        started = client.post("/research", json={"organisation_number": "982463718"}).json()
        response = client.get(f"/research/{started['run_id']}").json()
        assert len(response["results"]) == 1
        assert response["result"]["status"] == "failed"
        assert response["result"]["errors"][0]["code"] == "research_failed"
    repo.close()


def test_stale_run_update_cannot_erase_other_connection_publication(tmp_path):
    database = tmp_path / "stale.db"
    reader = Repository(database)
    publisher = Repository(database)
    run = ResearchRun(companies=["982463718"])
    reader.create_run(run)
    stale_run = reader.get_run(run.run_id)
    publisher.save_result(CompanyProfile(
        run_id=run.run_id, organisation_number="982463718", status="available",
        company=CompanyIdentity(organisation_number="982463718", legal_name="FIXTURE AS"),
    ))
    reader.update_run(stale_run)
    assert reader.get_run(run.run_id).company_states == {"982463718": "available"}
    # An outdated error finalizer must not contradict the committed envelope either.
    stale_run.company_states = {"982463718": "failed"}
    reader.update_run(stale_run)
    assert reader.get_run(run.run_id).company_states == {"982463718": "available"}
    reader.mark_company_state(run.run_id, "982463718", "failed")
    assert reader.get_run(run.run_id).company_states == {"982463718": "available"}
    reader.close()
    publisher.close()

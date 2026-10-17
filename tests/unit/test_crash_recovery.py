"""An expired crashed-worker lease must not prevent honest terminal finalization."""

import asyncio
import itertools
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.models import CompanyProfile, ResearchRun, utcnow
from nordtrace.core.repository import Repository, TaskOwnershipError
from nordtrace.engine.runner import BatchRunner

ORG = "982463718"


@pytest.mark.parametrize("condition, elapsed, reason", [
    ("requests", 2, "request_budget_exhausted"),
    ("deadline", 61, "deadline_exceeded"),
    ("unknown", 2, "run_budget_unavailable"),
])
def test_expired_crash_lease_does_not_strand_a_run_without_acquisition_allowance(
    tmp_path, monkeypatch, condition, elapsed, reason,
):
    repo = Repository(tmp_path / "crashed.db")
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    original = BudgetManager(max_requests=1, max_runtime_sec=60, max_cost=0)
    original.bind_run(repo, run.run_id, initialize=True)
    assert original.requests.try_acquire()
    assert repo.try_claim_company(run.run_id, ORG, "crashed-worker", lease_seconds=1)
    if condition == "unknown":
        repo.conn.execute("UPDATE runs SET budget_json=NULL WHERE run_id=?", (run.run_id,))
        repo.conn.commit()
    real_time = time.time
    monkeypatch.setattr("nordtrace.core.repository.time.time", lambda: real_time() + elapsed)
    calls = []

    async def forbidden_acquisition(*args):
        calls.append(args)
        pytest.fail("Resume cannot acquire a fresh allowance to recover a crashed task")

    monkeypatch.setattr("nordtrace.engine.runner.ResearchPipeline.research_company", forbidden_acquisition)
    try:
        resumed = asyncio.run(BatchRunner(repo).run_batch([ORG], resume_run_id=run.run_id))
        results = repo.get_results(run.run_id)
        assert len(results) == 1, "Expired foreign lease must not strand required output cardinality"
        assert results[0].status == "failed" and results[0].errors[0].code == reason
        assert resumed.completed_at is not None and resumed.request_count == 1
        assert calls == []
        frozen = results[0].model_dump()
        with pytest.raises((TaskOwnershipError, ValueError)):
            repo.save_result(CompanyProfile(
                run_id=run.run_id, organisation_number=ORG, status="available",
            ), owner="crashed-worker")
        assert repo.get_result(run.run_id, ORG).model_dump() == frozen
        repeated = asyncio.run(BatchRunner(repo).run_batch([ORG], resume_run_id=run.run_id))
        assert repeated.completed_at is not None and repeated.request_count == 1
        assert repo.get_result(run.run_id, ORG).model_dump() == frozen
        assert calls == []
    finally:
        repo.close()


@pytest.mark.parametrize("condition", ["unknown", "requests"])
def test_concurrent_finalizers_adopt_the_first_immutable_result(tmp_path, monkeypatch, condition):
    path = tmp_path / "concurrent.db"
    repo = Repository(path)
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat(), request_count=1)
    repo.create_run(run)
    repo.conn.execute("UPDATE runs SET request_count=1 WHERE run_id=?", (run.run_id,))
    repo.conn.commit()
    if condition == "requests":
        # Initialize before simulating the consumed request and crash.
        repo.conn.execute("UPDATE runs SET request_count=0 WHERE run_id=?", (run.run_id,))
        repo.conn.commit()
        budget = BudgetManager(max_requests=1, max_runtime_sec=60)
        budget.bind_run(repo, run.run_id, initialize=True)
        assert budget.requests.try_acquire()
    assert repo.try_claim_company(run.run_id, ORG, "crashed-worker", lease_seconds=1)
    real_time = time.time
    monkeypatch.setattr("nordtrace.core.repository.time.time", lambda: real_time() + 2)
    original = Repository.save_result
    barrier = threading.Barrier(2)
    sequence = itertools.count(1)
    first_calls = threading.local()

    def synchronize(self, result, owner=None):
        if not getattr(first_calls, "entered", False):
            first_calls.entered = True
            # Legitimately distinct finalization timestamps must not be treated as identical payloads.
            result.research_metadata.completed_at = f"2026-10-17T12:00:00.{next(sequence):06d}+00:00"
            barrier.wait(timeout=5)
        return original(self, result, owner=owner)

    monkeypatch.setattr(Repository, "save_result", synchronize)

    def finalize(_):
        worker = Repository(path)
        try:
            return asyncio.run(BatchRunner(worker).run_batch([ORG], resume_run_id=run.run_id))
        finally:
            worker.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(finalize, range(2)))
        assert all(outcome.completed_at is not None and outcome.request_count == 1 for outcome in outcomes)
        results = repo.get_results(run.run_id)
        reason = "run_budget_unavailable" if condition == "unknown" else "request_budget_exhausted"
        assert len(results) == 1 and results[0].errors[0].code == reason
        assert repo.get_run(run.run_id).company_states == {ORG: "failed"}
    finally:
        repo.close()


@pytest.mark.parametrize("elapsed, owner, status", [
    (0, "new-worker", "failed"),  # Live foreign owner remains protected.
    (2, None, "failed"),  # An unowned direct caller cannot retire a lease.
    (2, "new-worker", "available"),  # Recovery cannot manufacture successful research.
])
def test_recovery_does_not_bypass_live_ownership_or_allow_unclaimed_success(
    tmp_path, monkeypatch, elapsed, owner, status,
):
    repo = Repository(tmp_path / "guards.db")
    run = ResearchRun(companies=[ORG])
    repo.create_run(run)
    assert repo.try_claim_company(run.run_id, ORG, "original-worker", lease_seconds=1)
    real_time = time.time
    monkeypatch.setattr("nordtrace.core.repository.time.time", lambda: real_time() + elapsed)
    try:
        with pytest.raises(TaskOwnershipError):
            repo.save_result(CompanyProfile(
                run_id=run.run_id, organisation_number=ORG, status=status,
            ), owner=owner)
        assert repo.get_result(run.run_id, ORG) is None
        assert repo.conn.execute("SELECT owner FROM company_claims").fetchone()[0] == "original-worker"
    finally:
        repo.close()


def test_failed_recovery_commit_restores_the_expired_lease(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "rollback.db")
    run = ResearchRun(companies=[ORG])
    repo.create_run(run)
    assert repo.try_claim_company(run.run_id, ORG, "crashed-worker", lease_seconds=1)
    real_time = time.time
    monkeypatch.setattr("nordtrace.core.repository.time.time", lambda: real_time() + 2)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            with repo._publication_transaction():
                repo.save_result(CompanyProfile(
                    run_id=run.run_id, organisation_number=ORG, status="failed",
                ), owner="recovery-worker")
                raise RuntimeError("injected failure before outer commit")
        assert repo.get_result(run.run_id, ORG) is None
        assert repo.get_run(run.run_id).company_states == {}
        assert repo.conn.execute("SELECT owner FROM company_claims").fetchone()[0] == "crashed-worker"
    finally:
        repo.close()


def test_new_task_owner_fences_late_publisher_before_and_after_finalization(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "takeover.db")
    run = ResearchRun(companies=[ORG])
    repo.create_run(run)
    assert repo.try_claim_company(run.run_id, ORG, "old-worker", lease_seconds=1)
    real_time = time.time
    monkeypatch.setattr("nordtrace.core.repository.time.time", lambda: real_time() + 2)
    try:
        assert repo.try_claim_company(run.run_id, ORG, "new-worker", lease_seconds=60)
        late = CompanyProfile(run_id=run.run_id, organisation_number=ORG, status="available")
        with pytest.raises(TaskOwnershipError):
            repo.publish_result(late, owner="old-worker")
        assert repo.get_result(run.run_id, ORG) is None
        terminal = CompanyProfile(run_id=run.run_id, organisation_number=ORG, status="failed")
        repo.publish_result(terminal, owner="new-worker")
        repo.release_company(run.run_id, ORG, "new-worker")
        with pytest.raises(ValueError, match="immutable"):
            repo.publish_result(late, owner="old-worker")
        assert repo.get_result(run.run_id, ORG) == terminal
        assert not repo.try_claim_company(run.run_id, ORG, "late-worker", lease_seconds=60)
    finally:
        repo.close()

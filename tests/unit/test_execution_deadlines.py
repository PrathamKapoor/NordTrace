"""Deadline and cancellation behavior at real orchestration boundaries."""

import asyncio
import time

import httpx
import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.contracts import batch_payload
from nordtrace.core.models import ResearchRun, utcnow
from nordtrace.core.repository import Repository
from nordtrace.engine.pipeline import CompanyOutcome, ResearchPipeline
from nordtrace.engine.runner import BatchRunner

ORGS = ["982463718", "958973306", "923609016"]


def test_per_company_deadline_cancels_work_and_releases_next_company(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "company-timeout.db")
    calls, stopped, cancelled = [], [], []

    async def slow(self, org, run_id):
        calls.append(org)
        try:
            await asyncio.sleep(0.5)
            return CompanyOutcome(org_number=org, terminal_state="available")
        except asyncio.CancelledError:
            cancelled.append(org)
            raise
        finally:
            stopped.append(org)

    monkeypatch.setattr(ResearchPipeline, "research_company", slow)
    budget = BudgetManager(max_runtime_sec=5, per_company_soft_sec=0.05)
    started = time.monotonic()
    run = asyncio.run(BatchRunner(repo, budget, concurrency=1).run_batch(ORGS[:2]))
    assert time.monotonic() - started < 2.0
    assert calls == stopped == cancelled == ORGS[:2]
    assert [r.errors[0].code for r in repo.get_results(run.run_id)] == ["company_deadline_exceeded"] * 2
    assert repo.conn.execute("SELECT count(*) FROM company_claims").fetchone()[0] == 0
    repo.close()


def test_global_deadline_finalizes_queued_inputs_without_starting_them(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "global-timeout.db")
    calls, cancelled = [], []

    async def slow(self, org, run_id):
        calls.append(org)
        try:
            await asyncio.sleep(0.6)
            return CompanyOutcome(org_number=org, terminal_state="available")
        except asyncio.CancelledError:
            cancelled.append(org)
            raise

    monkeypatch.setattr(ResearchPipeline, "research_company", slow)
    budget = BudgetManager(max_runtime_sec=0.12, per_company_soft_sec=2)
    started = time.monotonic()
    run = asyncio.run(BatchRunner(repo, budget, concurrency=1).run_batch(ORGS))
    assert time.monotonic() - started < 1.5
    assert calls == cancelled == ORGS[:1]
    results = repo.get_results(run.run_id)
    assert len(results) == len(ORGS)
    assert all(r.status == "failed" and r.errors[0].code == "deadline_exceeded" for r in results)
    assert run.state == "interrupted"
    assert batch_payload(run, results, repo.get_run_inputs(run.run_id))["completion"]["complete"]
    assert repo.conn.execute("SELECT count(*) FROM company_claims").fetchone()[0] == 0
    repo.close()


def test_external_cancellation_persists_all_envelopes_before_propagating(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "cancel.db")

    async def execute():
        entered = asyncio.Event()
        stopped = asyncio.Event()

        async def slow(self, org, run_id):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        monkeypatch.setattr(ResearchPipeline, "research_company", slow)
        runner = BatchRunner(repo, BudgetManager(max_runtime_sec=5), concurrency=1)
        task = asyncio.create_task(runner.run_batch(ORGS))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set()
        run = repo.get_run(repo.list_runs()[0]["run_id"])
        results = repo.get_results(run.run_id)
        assert len(results) == len(ORGS)
        assert all(r.status == "failed" and r.errors[0].code == "research_cancelled" for r in results)
        assert run.state == "interrupted"
        assert repo.conn.execute("SELECT count(*) FROM company_claims").fetchone()[0] == 0

    asyncio.run(execute())
    repo.close()


def test_direct_pipeline_deadline_preserves_supported_partial_ledger(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "partial.db")
    run = ResearchRun(companies=ORGS[:1], started_at=utcnow().isoformat())
    repo.create_run(run)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    async def execute():
        budget = BudgetManager(max_runtime_sec=5, per_company_soft_sec=0.25)
        pipeline = ResearchPipeline(repo, budget)
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"organisasjonsnummer": ORGS[0], "navn": "FIXTURE AS"})
        ))

        async def slow_branches(*args):
            await asyncio.sleep(0.9)
            raise AssertionError("cancelled branch acquisition must not continue")

        monkeypatch.setattr(pipeline.brreg, "fetch_underenheter", slow_branches)
        try:
            result = await pipeline.research_company(ORGS[0], run.run_id)
            assert result.terminal_state == "failed"
        finally:
            await pipeline.aclose()

    asyncio.run(execute())
    frozen = repo.get_result(run.run_id, ORGS[0])
    assert frozen.errors[0].code == "company_deadline_exceeded"
    assert frozen.facts and frozen.company.legal_name == "FIXTURE AS"
    for fact in frozen.facts:
        assert repo.read_capture(fact.source_id)[1]
    repo.close()


def test_finalization_reserve_stops_acquisition_while_time_remains(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "reserve.db")

    async def slow(self, org, run_id):
        await asyncio.sleep(1)
        return CompanyOutcome(org_number=org, terminal_state="available")

    monkeypatch.setattr(ResearchPipeline, "research_company", slow)
    budget = BudgetManager(max_runtime_sec=0.5, per_company_soft_sec=3, finalization_reserve_sec=0.3)
    run = asyncio.run(BatchRunner(repo, budget).run_batch(ORGS[:1]))
    assert budget.runtime.time_remaining() > 0.15
    assert repo.get_result(run.run_id, ORGS[0]).errors[0].code == "deadline_exceeded"
    assert run.state == "interrupted"
    repo.close()


def test_legacy_terminal_checkpoint_without_envelope_is_not_invented(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "legacy-checkpoint.db")
    run = ResearchRun(companies=ORGS[:1], started_at=utcnow().isoformat())
    repo.create_run(run)
    BudgetManager(max_runtime_sec=5).bind_run(repo, run.run_id, initialize=True)
    repo.mark_company_state(run.run_id, ORGS[0], "available")
    calls = []

    async def research(self, org, run_id):
        calls.append(org)
        return CompanyOutcome(org_number=org, terminal_state="available")

    monkeypatch.setattr(ResearchPipeline, "research_company", research)
    resumed = asyncio.run(BatchRunner(repo).run_batch(run.companies, resume_run_id=run.run_id))
    assert not calls
    frozen = repo.get_result(run.run_id, ORGS[0])
    assert frozen.status == "failed" and frozen.errors[0].code == "legacy_result_unavailable"
    assert len(repo.get_results(resumed.run_id)) == 1
    repo.close()


def test_finalization_reserve_must_leave_acquisition_time():
    from pydantic import ValidationError

    from nordtrace.core.models import RunConfiguration

    with pytest.raises(ValidationError, match="reserve"):
        RunConfiguration(max_requests=1, max_runtime_sec=1.0, max_cost_usd=0.0, finalization_reserve_sec=1.0)


def test_provider_timeout_error_is_not_misreported_as_runner_deadline(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "provider-timeout.db")

    async def fail(self, org, run_id):
        raise TimeoutError("provider operation failed before runner deadline")

    monkeypatch.setattr(ResearchPipeline, "research_company", fail)
    run = asyncio.run(BatchRunner(repo, BudgetManager(max_runtime_sec=5)).run_batch(ORGS[:1]))
    result = repo.get_result(run.run_id, ORGS[0])
    assert result.errors[0].code == "research_failed"
    assert "provider operation failed" in result.errors[0].message
    repo.close()


def test_cancelling_follower_cannot_publish_failure_for_live_owner(tmp_path, monkeypatch):
    from nordtrace.core.models import CompanyIdentity

    repo = Repository(tmp_path / "follower.db")
    run = ResearchRun(companies=ORGS[:1], started_at=utcnow().isoformat())
    repo.create_run(run)
    BudgetManager(max_runtime_sec=5).bind_run(repo, run.run_id, initialize=True)

    async def execute():
        entered, release, waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original_claim = repo.try_claim_company

        def claim(*args):
            acquired = original_claim(*args)
            if not acquired and repo.get_result(run.run_id, ORGS[0]) is None:
                waiting.set()
            return acquired

        monkeypatch.setattr(repo, "try_claim_company", claim)

        async def acquire(self, org, run_id):
            entered.set()
            await release.wait()
            return CompanyOutcome(org_number=org, terminal_state="available",
                                  identity=CompanyIdentity(organisation_number=org, legal_name="FIXTURE AS"))

        monkeypatch.setattr(ResearchPipeline, "_research_company", acquire)
        leader = asyncio.create_task(BatchRunner(repo).run_batch(ORGS[:1], resume_run_id=run.run_id))
        await entered.wait()
        follower = asyncio.create_task(BatchRunner(repo).run_batch(ORGS[:1], resume_run_id=run.run_id))
        await waiting.wait()
        follower.cancel()
        with pytest.raises(asyncio.CancelledError):
            await follower
        assert repo.get_result(run.run_id, ORGS[0]) is None
        release.set()
        await leader
        assert repo.get_result(run.run_id, ORGS[0]).status == "available"
        assert repo.conn.execute("SELECT count(*) FROM company_claims").fetchone()[0] == 0

    asyncio.run(execute())
    repo.close()


def test_checkpoint_error_drains_siblings_before_pipeline_cleanup(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "checkpoint-failure.db")

    async def execute():
        entered, stopped = asyncio.Event(), asyncio.Event()

        async def acquire(self, org, run_id):
            if org == ORGS[0]:
                await entered.wait()
                return CompanyOutcome(org_number=org, terminal_state="available")
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        monkeypatch.setattr(ResearchPipeline, "research_company", acquire)
        runner = BatchRunner(repo, BudgetManager(max_runtime_sec=5), concurrency=2)
        original = runner._checkpoint
        failures = []

        def checkpoint(run):
            if not failures:
                failures.append(True)
                raise RuntimeError("injected checkpoint storage failure")
            original(run)

        monkeypatch.setattr(runner, "_checkpoint", checkpoint)
        with pytest.raises(RuntimeError, match="checkpoint storage"):
            await runner.run_batch(ORGS[:2])
        assert stopped.is_set(), "A sibling must stop before run cleanup returns"
        run = repo.get_run(repo.list_runs()[0]["run_id"])
        assert len(repo.get_results(run.run_id)) == 2
        assert run.state == "failed"
        assert repo.conn.execute("SELECT count(*) FROM company_claims").fetchone()[0] == 0

    asyncio.run(execute())
    repo.close()


def test_legacy_unknown_budget_still_exports_missing_terminal_envelope(tmp_path):
    repo = Repository(tmp_path / "legacy-no-budget.db")
    run = ResearchRun(companies=ORGS[:1], started_at=utcnow().isoformat())
    repo.create_run(run)
    repo.mark_company_state(run.run_id, ORGS[0], "available")
    resumed = asyncio.run(BatchRunner(repo).run_batch(run.companies, resume_run_id=run.run_id))
    results = repo.get_results(run.run_id)
    assert len(results) == 1
    assert results[0].status == "failed" and results[0].errors[0].code == "legacy_result_unavailable"
    assert results[0].research_metadata.run_configuration is None
    assert batch_payload(resumed, results, [{"index": 0, "supplied": ORGS[0], "result_key": ORGS[0]}])
    repo.close()


def test_unwritable_result_storage_still_closes_pipeline_and_releases_lease(tmp_path, monkeypatch):
    import sqlite3

    repo = Repository(tmp_path / "unwritable.db")
    closed = []
    original_close = ResearchPipeline.aclose

    async def acquire(self, org, run_id):
        return CompanyOutcome(org_number=org, terminal_state="available")

    async def close(self):
        try:
            await original_close(self)
        finally:
            closed.append(True)

    def unwritable(*args, **kwargs):
        raise sqlite3.OperationalError("injected readonly result storage")

    monkeypatch.setattr(ResearchPipeline, "research_company", acquire)
    monkeypatch.setattr(ResearchPipeline, "aclose", close)
    monkeypatch.setattr(repo, "save_result", unwritable)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        asyncio.run(BatchRunner(repo).run_batch(ORGS[:1]))
    assert closed == [True]
    assert repo.conn.execute("SELECT count(*) FROM company_claims").fetchone()[0] == 0
    repo.close()


@pytest.mark.parametrize("checkpoint_failure", [False, True])
def test_storage_cleanup_error_does_not_mask_external_cancellation(tmp_path, monkeypatch, checkpoint_failure):
    import sqlite3

    repo = Repository(tmp_path / "cancel-storage-error.db")

    async def execute():
        entered = asyncio.Event()

        async def slow(self, org, run_id):
            entered.set()
            await asyncio.Event().wait()

        def unwritable(*args, **kwargs):
            raise sqlite3.OperationalError("injected cancellation cleanup storage failure")

        monkeypatch.setattr(ResearchPipeline, "research_company", slow)
        runner = BatchRunner(repo)
        if checkpoint_failure:
            monkeypatch.setattr(runner, "_checkpoint", unwritable)
        else:
            monkeypatch.setattr(repo, "save_result", unwritable)
        task = asyncio.create_task(runner.run_batch(ORGS[:1]))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()
        assert repo.conn.execute("SELECT count(*) FROM company_claims").fetchone()[0] == 0

    asyncio.run(execute())
    repo.close()


def test_direct_pipeline_storage_error_preserves_external_cancellation(tmp_path, monkeypatch):
    import sqlite3

    repo = Repository(tmp_path / "pipeline-cancel-error.db")
    run = ResearchRun(companies=ORGS[:1], started_at=utcnow().isoformat())
    repo.create_run(run)

    async def execute():
        entered = asyncio.Event()
        pipeline = ResearchPipeline(repo, BudgetManager(max_runtime_sec=5))

        async def slow_identity(*args):
            entered.set()
            await asyncio.Event().wait()

        def unwritable(*args, **kwargs):
            raise sqlite3.OperationalError("injected pipeline cancellation storage failure")

        monkeypatch.setattr(pipeline.brreg, "fetch_entity", slow_identity)
        monkeypatch.setattr(repo, "save_result", unwritable)
        task = asyncio.create_task(pipeline.research_company(ORGS[0], run.run_id))
        try:
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert task.cancelled()
        finally:
            await pipeline.aclose()

    asyncio.run(execute())
    repo.close()

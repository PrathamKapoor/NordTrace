"""A resumed or concurrent worker cannot acquire a fresh run allowance."""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.models import CompanyProfile, ResearchRun, utcnow
from nordtrace.core.repository import Repository
from nordtrace.engine.pipeline import CompanyOutcome
from nordtrace.engine.runner import BatchRunner

ORG = "982463718"
OTHER = "958973306"


def test_replacement_worker_restores_original_limits_and_consumed_requests(tmp_path):
    path = tmp_path / "persistent.db"
    repo = Repository(path)
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    original = BudgetManager(max_requests=3, max_runtime_sec=60, max_cost=0.5, per_company_soft_sec=7)
    original.bind_run(repo, run.run_id, initialize=True)
    assert original.requests.try_acquire(2)
    replacement = BudgetManager(max_requests=1000, max_runtime_sec=3600, max_cost=10)
    replacement.bind_run(repo, run.run_id)
    assert replacement.requests.global_limit == 3
    assert replacement.requests.total_used == 2 and replacement.requests.remaining() == 1
    assert replacement.cost.limit == 0.5
    assert replacement.runtime.total_limit_sec == 60 and replacement.runtime.per_company_soft_sec == 7
    assert replacement.requests.try_acquire()
    assert original.requests.total_used == 3  # Read through another worker's committed reservation.
    assert not original.requests.try_acquire()
    repo.close()


def test_independent_connections_cannot_overspend_the_same_run(tmp_path):
    path = tmp_path / "shared.db"
    repo = Repository(path)
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    budget = BudgetManager(max_requests=17, max_runtime_sec=60)
    budget.bind_run(repo, run.run_id, initialize=True)

    def consume(_):
        connection = Repository(path)
        worker = BudgetManager(max_requests=999)
        worker.bind_run(connection, run.run_id)
        count = 0
        try:
            while worker.requests.try_acquire():
                count += 1
            return count
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        counts = list(pool.map(consume, range(4)))
    assert sum(counts) == 17
    assert repo.get_run(run.run_id).request_count == budget.requests.total_used == 17
    repo.close()


def test_resume_does_not_reset_budget_or_invoke_completed_work(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "resume.db")
    run = ResearchRun(companies=[ORG, OTHER], started_at=utcnow().isoformat())
    repo.create_run(run)
    original = BudgetManager(max_requests=2, max_runtime_sec=60, max_cost=0)
    original.bind_run(repo, run.run_id, initialize=True)
    original.requests.try_acquire(2)  # Simulate a crash after durable reservations.
    repo.save_result(CompanyProfile(run_id=run.run_id, organisation_number=ORG))
    calls = []

    async def research(self, org, run_id):
        calls.append(org)
        return CompanyOutcome(org_number=org, terminal_state="not_available")

    monkeypatch.setattr("nordtrace.engine.runner.ResearchPipeline.research_company", research)
    runner = BatchRunner(repo, BudgetManager(max_requests=999, max_runtime_sec=3600))
    resumed = asyncio.run(runner.run_batch(run.companies, resume_run_id=run.run_id))
    assert calls == []
    assert resumed.request_count == 2 and runner.budget.requests.global_limit == 2
    assert len(repo.get_results(run.run_id)) == 2
    assert repo.get_result(run.run_id, OTHER).errors[0].code == "request_budget_exhausted"
    repo.close()


def test_legacy_unknown_budget_emits_honest_failure_without_fresh_requests(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "legacy-budget.db")
    run = ResearchRun(companies=[ORG, OTHER], started_at=utcnow().isoformat(), request_count=42)
    repo.create_run(run)
    repo.save_result(CompanyProfile(run_id=run.run_id, organisation_number=ORG))
    # An old checkpoint can contain usage without a recoverable original allowance.
    repo.conn.execute("UPDATE runs SET request_count=42 WHERE run_id=?", (run.run_id,))
    repo.conn.commit()
    calls = []

    async def research(self, org, run_id):
        calls.append(org)
        return CompanyOutcome(org_number=org, terminal_state="not_available")

    monkeypatch.setattr("nordtrace.engine.runner.ResearchPipeline.research_company", research)
    resumed = asyncio.run(BatchRunner(repo).run_batch(run.companies, resume_run_id=run.run_id))
    assert calls == [] and resumed.request_count == 42
    assert repo.get_result(run.run_id, OTHER).errors[0].code == "run_budget_unavailable"
    assert repo.get_result(run.run_id, OTHER).research_metadata.request_budget is None
    repo.close()


def test_gateway_hops_and_cache_agree_with_durable_counter_after_replacement(tmp_path, monkeypatch):
    import httpx

    from nordtrace.core.budget import BudgetExceededError
    from nordtrace.core.request_gateway import RequestGateway

    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    repo = Repository(tmp_path / "transport.db")
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    calls = []

    def respond(request):
        calls.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(200, text="Fixture bytes")

    async def execute():
        first = BudgetManager(max_requests=3, max_runtime_sec=60)
        first.bind_run(repo, run.run_id, initialize=True)
        gateway = RequestGateway(first, repository=repo)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            assert (await gateway.fetch("https://public.example/start", retries=0)).access_status == "success"
            assert (await gateway.fetch("https://public.example/start", retries=0)).cache_hit
        finally:
            await gateway.aclose()
        replacement = BudgetManager(max_requests=999)
        replacement.bind_run(repo, run.run_id)
        gateway = RequestGateway(replacement, repository=repo)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            assert (await gateway.fetch("https://public.example/other", retries=0)).access_status == "success"
            with pytest.raises(BudgetExceededError):
                await gateway.fetch("https://public.example/over-limit", retries=0)
        finally:
            await gateway.aclose()
        return replacement

    budget = asyncio.run(execute())
    assert budget.requests.total_used == repo.get_run(run.run_id).request_count == len(calls) == 3
    assert budget.requests.snapshot()["successful"] == 3
    assert budget.requests.snapshot()["unresolved_reservations"] == 0
    assert budget.requests.snapshot()["by_domain"] == {"public.example": 3}
    repo.close()


def test_elapsed_allowance_cannot_be_reset_by_a_new_runtime_setting(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "deadline.db")
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    original = BudgetManager(max_requests=10, max_runtime_sec=60)
    original.bind_run(repo, run.run_id, initialize=True)
    # A persisted expired deadline, as after a process was stopped overnight.
    state, _, _ = repo.get_run_budget(run.run_id)
    state.deadline_unix = time.time() - 1
    repo.conn.execute("UPDATE runs SET budget_json=? WHERE run_id=?", (state.model_dump_json(), run.run_id))
    repo.conn.commit()
    calls = []

    async def research(self, org, run_id):
        calls.append(org)
        return CompanyOutcome(org_number=org, terminal_state="not_available")

    monkeypatch.setattr("nordtrace.engine.runner.ResearchPipeline.research_company", research)
    replacement = BudgetManager(max_runtime_sec=3600)
    resumed = asyncio.run(BatchRunner(repo, replacement).run_batch(run.companies, resume_run_id=run.run_id))
    assert calls == [] and replacement.runtime.time_remaining() == 0
    assert resumed.request_count == 0
    profile = repo.get_result(run.run_id, ORG)
    assert profile.errors[0].code == "deadline_exceeded"
    assert profile.research_metadata.run_configuration.max_runtime_sec == 60
    repo.close()


def test_already_bound_worker_cannot_ignore_another_workers_elapsed_checkpoint(tmp_path):
    repo = Repository(tmp_path / "shared-deadline.db")
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    first = BudgetManager(max_requests=10, max_runtime_sec=60)
    first.bind_run(repo, run.run_id, initialize=True)
    concurrent = BudgetManager()
    concurrent.bind_run(repo, run.run_id)
    first.runtime.started_at -= 61  # Inject elapsed monotonic time at its authoritative checkpoint.
    first.checkpoint()
    assert not concurrent.requests.try_acquire()
    assert concurrent.requests.total_used == 0
    repo.close()


@pytest.mark.parametrize("amount", [-1, 0, True, 1.5])
def test_request_reservations_cannot_reduce_or_fractionally_change_usage(amount):
    budget = BudgetManager(max_requests=2)
    with pytest.raises(ValueError):
        budget.requests.try_acquire(amount)
    assert budget.requests.total_used == 0


def test_resume_cli_signals_unrecoverable_budget_failure(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from nordtrace.cli import cli

    repo = Repository(tmp_path / "cli-budget.db")
    run = ResearchRun(companies=[ORG, OTHER], started_at=utcnow().isoformat())
    repo.create_run(run)
    repo.save_result(CompanyProfile(run_id=run.run_id, organisation_number=ORG))
    monkeypatch.setattr("nordtrace.cli._repo", lambda: repo)
    result = CliRunner().invoke(cli, ["resume", run.run_id])
    assert result.exit_code == 1
    # A second resume still reports the stored execution failure, even with no pending work.
    assert CliRunner().invoke(cli, ["resume", run.run_id]).exit_code == 1


def test_accounting_storage_failure_cannot_strand_domain_permits(tmp_path, monkeypatch):
    import sqlite3

    import httpx

    from nordtrace.core.rate_limiter import RateLimiter, SourcePolicy
    from nordtrace.core.request_gateway import RequestGateway

    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    path = tmp_path / "contention.db"
    repo = Repository(path)
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    budget = BudgetManager(max_requests=3, max_runtime_sec=2)
    budget.bind_run(repo, run.run_id, initialize=True)
    blocker = sqlite3.connect(path)
    calls = []

    def respond(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            blocker.execute("BEGIN IMMEDIATE")
        return httpx.Response(200, text="Fixture body")

    async def execute():
        limiter = RateLimiter(default_policy=SourcePolicy(max_concurrent=1, min_interval=0))
        gateway = RequestGateway(budget, rate_limiter=limiter, repository=repo)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            with pytest.raises(sqlite3.OperationalError):
                await gateway._exchange("https://public.example/first", "public.example",
                                        stage="fixture", company=ORG, max_bytes=1024, retry=False)
            blocker.rollback()
            async with asyncio.timeout(1):
                return await gateway._exchange("https://public.example/second", "public.example",
                                               stage="fixture", company=ORG, max_bytes=1024, retry=False)
        finally:
            await gateway.aclose()

    try:
        result = asyncio.run(execute())
        assert result.status_code == 200 and len(calls) == 2
        assert budget.requests.snapshot()["unresolved_reservations"] == 1
    finally:
        blocker.rollback()
        blocker.close()
        repo.close()


def test_reservation_commit_after_deadline_cannot_start_transport(tmp_path, monkeypatch):
    from contextlib import contextmanager

    import httpx

    from nordtrace.core.request_gateway import RequestGateway

    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    wall_clock, monotonic_clock = time.time, time.monotonic
    clock_advance = [0]
    monkeypatch.setattr(time, "time", lambda: wall_clock() + clock_advance[0])
    monkeypatch.setattr(time, "monotonic", lambda: monotonic_clock() + clock_advance[0])
    repo = Repository(tmp_path / "slow-commit.db")
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    budget = BudgetManager(max_requests=2, max_runtime_sec=60)
    budget.bind_run(repo, run.run_id, initialize=True)
    original = repo._budget_transaction
    delays = []

    @contextmanager
    def slow_commit(deadline):
        with original(deadline) as connection:
            yield connection
            if not delays:
                assert connection.execute(
                    "SELECT request_count FROM runs WHERE run_id=?", (run.run_id,),
                ).fetchone()[0] == 1, "Fault must occur after a real request reservation"
                delays.append(True)
                clock_advance[0] = 61  # Both absolute clocks expire before durable commit returns.

    monkeypatch.setattr(repo, "_budget_transaction", slow_commit)
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(200, text="Late body")

    async def execute():
        gateway = RequestGateway(budget)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            result = await gateway.fetch("https://public.example/late", retries=0)
            assert gateway.rate_limiter.state_for("public.example").consecutive_failures == 0
            return result
        finally:
            await gateway.aclose()

    result = asyncio.run(execute())
    assert delays == [True]
    assert calls == [] and result.access_status == "timeout"
    assert budget.requests.total_used == 1  # Conservatively charged; never refunded after uncertain commit.
    assert budget.requests.snapshot()["unstarted_reservations"] == 1
    assert budget.requests.snapshot()["transport_operations"] == 0
    repo.close()

"""Real SQLite contention must recover without replaying transaction bodies."""

import sqlite3
import threading
import time

import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.models import ResearchRun
from nordtrace.core.repository import Repository


def test_budget_reservation_recovers_after_one_bounded_sqlite_lock_timeout(tmp_path, monkeypatch):
    path = tmp_path / "contended.db"
    repo = Repository(path)
    run = ResearchRun(companies=["982463718"])
    repo.create_run(run)
    budget = BudgetManager(max_requests=1, max_runtime_sec=60)
    budget.bind_run(repo, run.run_id, initialize=True)
    real_connect = sqlite3.connect
    ready, release = threading.Event(), threading.Event()
    attempts = []

    def hold_writer():
        connection = real_connect(path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            ready.set()
            assert release.wait(5), "Test did not release its writer"
            connection.rollback()
        finally:
            connection.close()

    class ObservedConnection(sqlite3.Connection):
        def execute(self, statement, parameters=()):
            if statement == "BEGIN IMMEDIATE":
                attempts.append(statement)
                try:
                    return super().execute(statement, parameters)
                except sqlite3.OperationalError:
                    # Only release AFTER the real first SQLite busy timeout.
                    release.set()
                    raise
            return super().execute(statement, parameters)

    def connect(*args, **kwargs):
        return real_connect(*args, **kwargs, factory=ObservedConnection)

    writer = threading.Thread(target=hold_writer)
    writer.start()
    assert ready.wait(5)
    monkeypatch.setattr(sqlite3, "connect", connect)
    try:
        assert budget.requests.try_acquire()
        assert not budget.requests.try_acquire()
        assert len(attempts) >= 2
        assert repo.get_run(run.run_id).request_count == 1
    finally:
        release.set()
        writer.join(5)
        repo.close()
    assert not writer.is_alive()


def test_busy_error_inside_budget_body_rolls_back_without_replaying(tmp_path):
    repo = Repository(tmp_path / "body.db")
    run = ResearchRun(companies=["982463718"])
    repo.create_run(run)
    calls = []
    busy = sqlite3.OperationalError("injected transaction-body busy error")
    busy.sqlite_errorcode = sqlite3.SQLITE_BUSY
    try:
        with pytest.raises(sqlite3.OperationalError, match="transaction-body"):
            with repo._budget_transaction(time.time() + 5) as connection:
                calls.append("body")
                connection.execute("UPDATE runs SET request_count=1 WHERE run_id=?", (run.run_id,))
                raise busy
        assert calls == ["body"]
        assert repo.get_run(run.run_id).request_count == 0
    finally:
        repo.close()


def test_budget_lock_wait_cannot_extend_the_supplied_deadline(tmp_path):
    path = tmp_path / "deadline.db"
    repo = Repository(path)
    writer = sqlite3.connect(path)
    try:
        writer.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            with repo._budget_transaction(time.time() + 0.06):
                pytest.fail("Held writer must prevent entering the transaction body")
        assert time.monotonic() - started < 1, "Lock wait ignored its absolute deadline"
    finally:
        writer.rollback()
        writer.close()
        repo.close()


def test_non_contention_acquisition_error_is_not_retried(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "readonly.db")
    real_connect = sqlite3.connect
    statements = []

    def connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connection.execute("PRAGMA query_only=ON")
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            with repo._budget_transaction(time.time() + 5):
                pytest.fail("Read-only failure must prevent entering the transaction body")
        assert statements.count("BEGIN IMMEDIATE") == 1
    finally:
        repo.close()

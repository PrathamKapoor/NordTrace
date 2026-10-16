"""Retained transport bytes are independently readable without network access."""

import asyncio
import hashlib

import httpx
import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.repository import Repository
from nordtrace.core.request_gateway import RequestGateway


@pytest.mark.parametrize("body,content_type", [
    (b"%PDF-1.4\n\xff\x00\x81binary", "application/pdf"),
    (b"\xe6" * 210000, "text/plain; charset=iso-8859-1"),
], ids=["binary-pdf", "large-latin1-text"])
def test_gateway_retains_exact_bytes_and_replays_offline(tmp_path, monkeypatch, body, content_type):
    repo = Repository(tmp_path / "capture.db")
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=body, headers={"content-type": content_type})

    async def execute():
        gw = RequestGateway(BudgetManager(), repository=repo)
        gw._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            source = await gw.fetch("https://example.no/document", retries=0)
            cached = await gw.fetch("https://example.no/document", retries=0)
            assert cached.cache_hit
            assert repo.read_capture(cached.source_id)[1] == body
            return source
        finally:
            await gw.aclose()

    source = asyncio.run(execute())
    repo.close()
    repo = Repository(tmp_path / "capture.db")
    assert source.content_hash == hashlib.sha256(body).hexdigest()
    assert source.snapshot_representation == "http-response-body-v1"
    stored, restored = repo.read_capture(source.source_id)
    assert stored == source
    assert restored == body
    replay = RequestGateway(BudgetManager(max_requests=0), repository=repo)
    replayed = replay.load_capture(source.source_id)
    assert replayed.content == body
    assert replayed.text == httpx.Response(200, headers={"content-type": content_type}, content=body).text
    assert replayed.content_hash == source.content_hash
    assert replayed.retrieved_at == pytest.approx(source_time(source.retrieved_at))
    assert replay.budget.requests.total_used == 0
    assert len(calls) == 1
    repo.close()


def source_time(value):
    from datetime import datetime

    return datetime.fromisoformat(value).timestamp()


def test_missing_and_tampered_capture_abstain(tmp_path):
    from nordtrace.core.models import SourceRecord

    repo = Repository(tmp_path / "capture.db")
    source = SourceRecord(url="https://example.no", content_hash=hashlib.sha256(b"original").hexdigest(),
                          access_status="success", snapshot_representation="http-response-body-v1")
    repo.save_capture(source, b"original")
    with pytest.raises(ValueError, match="hash"):
        repo.save_capture(source, b"wrong")
    repo.conn.execute("UPDATE snapshot_blobs SET content=?", (b"tampered",))
    repo.conn.commit()
    with pytest.raises(ValueError, match="integrity"):
        repo.read_capture(source.source_id)
    with pytest.raises(KeyError):
        repo.read_capture("absent")
    repo.close()


def test_real_pipeline_retains_identity_even_when_later_acquisition_fails(tmp_path, monkeypatch):
    from nordtrace.core.models import ResearchRun
    from nordtrace.engine.pipeline import ResearchPipeline

    repo = Repository(tmp_path / "pipeline.db")
    run = ResearchRun(companies=["982463718"])
    repo.create_run(run)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    registry = b'{"organisasjonsnummer":"982463718","navn":"TARGET AS"}'

    def respond(request):
        if str(request.url).endswith("/enheter/982463718"):
            return httpx.Response(200, content=registry, headers={"content-type": "application/json"})
        return httpx.Response(404)

    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager())
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            await pipeline.research_company("982463718", run.run_id)
        finally:
            await pipeline.aclose()

    asyncio.run(execute())
    result = repo.get_result(run.run_id, "982463718")
    assert result.company.organisation_number == "982463718"
    successful = [source for source in result.sources if source.access_status == "success"]
    assert successful
    for source in successful:
        assert repo.read_capture(source.source_id)[1] == registry
    repo.close()


def test_offline_cli_verifies_and_exports_without_overwriting_on_tamper(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from nordtrace.cli import cli
    from nordtrace.core.contracts import build_result
    from nordtrace.core.models import ResearchRun, SourceRecord, utcnow
    from nordtrace.engine.pipeline import CompanyOutcome

    db = tmp_path / "cli-capture.db"
    repo = Repository(db)
    run = ResearchRun(companies=["982463718"])
    repo.create_run(run)
    body = b"captured bytes\xff"
    source = SourceRecord(
        url="https://example.no", content_hash=hashlib.sha256(body).hexdigest(),
        access_status="success", snapshot_representation="http-response-body-v1",
        retrieved_at=utcnow().isoformat(),
    )
    repo.save_capture(source, body)
    outcome = CompanyOutcome(org_number="982463718", terminal_state="failed", sources=[source])
    repo.save_result(build_result(outcome, run.run_id, BudgetManager(), utcnow().isoformat()))
    monkeypatch.setattr("nordtrace.cli._repo", lambda: Repository(db))

    def forbid_network(*args, **kwargs):
        raise AssertionError("offline operation tried DNS")

    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", forbid_network)
    runner = CliRunner()
    assert runner.invoke(cli, ["verify-snapshots", run.run_id]).exit_code == 0
    output = tmp_path / "source.bin"
    assert runner.invoke(cli, ["replay-source", source.source_id, "--output", str(output)]).exit_code == 0
    assert output.read_bytes() == body
    repo.conn.execute("UPDATE snapshot_blobs SET content=?", (b"wrong",))
    repo.conn.commit()
    assert runner.invoke(cli, ["verify-snapshots", run.run_id]).exit_code == 1
    assert runner.invoke(cli, ["replay-source", source.source_id, "--output", str(output)]).exit_code == 1
    assert output.read_bytes() == body
    repo.close()


def test_upgrade_v2_preserves_outcomes_and_creates_one_backup(tmp_path):
    import sqlite3

    from nordtrace.core.models import ResearchRun

    db = tmp_path / "upgrade.db"
    repo = Repository(db)
    run = ResearchRun(companies=["invalid"])
    repo.create_run(run)
    # Construct the immediately previous schema on this isolated fixture only.
    repo.conn.execute("DROP TABLE source_captures")
    repo.conn.execute("DROP TABLE snapshot_blobs")
    repo.conn.execute("PRAGMA user_version=2")
    repo.conn.commit()
    repo.close()
    upgraded = Repository(db)
    assert upgraded.get_run(run.run_id).companies == ["invalid"]
    assert upgraded.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    upgraded.close()
    backups = list(tmp_path.glob("upgrade.db.pre-v3-*.bak"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 2
        assert backup.execute("SELECT run_id FROM runs").fetchone()[0] == run.run_id
    Repository(db).close()
    assert len(list(tmp_path.glob("upgrade.db.pre-v3-*.bak"))) == 1


def test_snapshot_write_contention_cannot_return_late_success(tmp_path, monkeypatch):
    import sqlite3
    import time

    repo = Repository(tmp_path / "locked.db")
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    blocker = sqlite3.connect(repo.db_path)
    blocker.execute("BEGIN IMMEDIATE")
    budget = BudgetManager(max_runtime_sec=0.03)

    async def execute():
        gw = RequestGateway(budget, repository=repo)
        gw._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="ok")
        ))
        try:
            return await gw.fetch("https://example.no/locked", retries=0)
        finally:
            await gw.aclose()

    started = time.monotonic()
    try:
        result = asyncio.run(execute())
        assert result.access_status in ("failed", "timeout")
        assert time.monotonic() - started < 0.3
        assert repo.conn.execute("SELECT count(*) FROM source_captures").fetchone()[0] == 0
    finally:
        blocker.rollback()
        blocker.close()
        repo.close()


def test_capture_metadata_conflict_rolls_back_new_blob(tmp_path):
    from nordtrace.core.models import SourceRecord

    repo = Repository(tmp_path / "atomic.db")
    original = SourceRecord(
        url="https://example.no", content_hash=hashlib.sha256(b"original").hexdigest(),
        snapshot_representation="http-response-body-v1", access_status="success",
    )
    repo.save_capture(original, b"original")
    altered = original.model_copy(update={"content_hash": hashlib.sha256(b"altered").hexdigest()})
    with pytest.raises(ValueError, match="immutable"):
        repo.save_capture(altered, b"altered")
    assert repo.conn.execute("SELECT count(*) FROM snapshot_blobs").fetchone()[0] == 1
    assert repo.read_capture(original.source_id)[1] == b"original"
    repo.close()

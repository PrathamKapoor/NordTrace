"""Observed smoke artifacts use the production runner and an independent HTTP boundary."""
import asyncio
import hashlib
import json
import time

import httpx
import pytest

from nordtrace.core.config import settings
from nordtrace.core.export import verify_bundle
from nordtrace.core.models import RunConfiguration


def test_smoke_retains_complete_results_and_reconciles_transport(tmp_path, monkeypatch):
    from nordtrace.smoke import run_smoke

    source = tmp_path / "supplied.jsonl"
    raw = b'{"organisation_number":"982463718"}\n' * 2
    raw += b'{"organisation_number":"invalid"}\n'
    source.write_bytes(raw)
    calls = []
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda _: ["8.8.8.8"])
    original = settings.model_dump()
    monkeypatch.setattr(settings, "llm_api_key", "must-never-be-used")

    async def transport(self, request):
        calls.append(request)
        if request.url.path.endswith("/enheter/982463718"):
            return httpx.Response(200, json={"organisasjonsnummer": "982463718", "navn": "FIXTURE AS"})
        return httpx.Response(404)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", transport)
    try:
        manifest, exit_code = asyncio.run(run_smoke(
            source, tmp_path / "run", configuration=RunConfiguration(
                max_requests=30, max_runtime_sec=30, max_cost_usd=0,
                per_company_sec=20, finalization_reserve_sec=2,
            ), concurrency=2, revision="fixture-revision",
        ))
        assert exit_code == 2  # Invalid input remains an envelope and programmatic error.
        # Registry-only smoke blocks guessed sites before DNS/robots/transport.
        assert len(calls) == 4
        assert manifest["transport"]["dispatches"] == manifest["transport"]["gateway_operations"] == 4
        assert all(request.headers["host"] == "data.brreg.no" for request in calls)
        assert manifest["configuration"]["allowed_source_origins"] == ["https://data.brreg.no"]
        assert manifest["mode"] == "deterministic_registry_only_no_models"
        assert manifest["transport"]["matches"] is True
        assert manifest["input_count"] == 3 and manifest["unique_results"] == 2
        assert manifest["independent_accuracy"]["measured"] is False
        assert manifest["configuration"]["max_cost_usd"] == 0
        assert manifest["effective_settings"]["respect_robots"] is True
        output = tmp_path / "run"
        assert (output / "inputs.jsonl").read_bytes() == raw
        assert manifest["input_sha256"] == hashlib.sha256(raw).hexdigest()
        payload = json.loads((output / "results.json").read_text())
        assert len(payload["results"]) == 2 and len(payload["inputs"]) == 3
        bundle = verify_bundle(output / "evidence.zip")
        assert bundle["completion"]["complete"] is True
        assert bundle["captures"]
        assert "must-never-be-used" not in (output / "manifest.json").read_text()
        assert settings.llm_api_key == "must-never-be-used"
        assert httpx.AsyncHTTPTransport.handle_async_request is transport
    finally:
        for key, value in original.items():
            setattr(settings, key, value)


def test_smoke_refuses_existing_output_and_paid_budget_before_network(tmp_path):
    from nordtrace.smoke import run_smoke

    source = tmp_path / "input.jsonl"
    source.write_text('{"organisation_number":"invalid"}\n')
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "manifest.json"
    sentinel.write_text("user data")
    with pytest.raises(FileExistsError):
        asyncio.run(run_smoke(source, output, configuration=RunConfiguration(
            max_requests=10, max_runtime_sec=30, max_cost_usd=0),
                              concurrency=1, revision="fixture"))
    assert sentinel.read_text() == "user data"
    with pytest.raises(ValueError, match="zero"):
        asyncio.run(run_smoke(source, tmp_path / "paid", configuration=RunConfiguration(
            max_requests=10, max_runtime_sec=30, max_cost_usd=1),
                              concurrency=1, revision="fixture"))
    assert not (tmp_path / "paid").exists()


def test_transport_observer_counts_failed_dispatch_and_restores_on_error(monkeypatch):
    from nordtrace.smoke import TransportAudit

    async def failing(self, request):
        raise httpx.ConnectError("fixture", request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", failing)

    async def execute():
        with TransportAudit() as audit:
            async with httpx.AsyncClient(trust_env=False) as client:
                with pytest.raises(httpx.ConnectError):
                    await client.get("https://fixture.example/secret?token=do-not-retain")
            assert len(audit.operations) == 1
            assert audit.operations[0]["outcome"] == "ConnectError"
            assert "do-not-retain" not in json.dumps(audit.operations)
            raise RuntimeError("after transport")

    with pytest.raises(RuntimeError, match="after transport"):
        asyncio.run(execute())
    assert httpx.AsyncHTTPTransport.handle_async_request is failing


def test_transport_observer_rejects_authorized_requests_before_dispatch(monkeypatch):
    from nordtrace.smoke import TransportAudit

    calls = []
    async def transport(self, request):
        calls.append(request)
        return httpx.Response(200)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", transport)

    async def execute():
        with TransportAudit() as audit:
            async with httpx.AsyncClient(trust_env=False) as client:
                with pytest.raises(ValueError, match="credential"):
                    await client.get("https://fixture.example/", headers={"Authorization": "secret"})
            assert audit.operations == []
    asyncio.run(execute())
    assert not calls


def test_smoke_cli_requires_live_opt_in_and_exports_invalid_input(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from nordtrace.cli import cli

    source = tmp_path / "inputs.jsonl"
    source.write_text('{"organisation_number":"invalid"}\n')
    output = tmp_path / "result"
    arguments = ["smoke", str(source), "--output", str(output), "--max-requests", "0",
                 "--max-runtime-sec", "30", "--per-company-sec", "10", "--finalization-reserve-sec", "2"]
    runner = CliRunner()
    denied = runner.invoke(cli, arguments)
    assert denied.exit_code != 0 and "--live" in denied.output
    assert not output.exists()
    monkeypatch.setattr("nordtrace.smoke.source_revision", lambda: "fixture")
    result = runner.invoke(cli, arguments + ["--live"])
    assert result.exit_code == 2, result.output
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["transport"]["dispatches"] == 0
    assert manifest["revision"] == "fixture"


def test_smoke_export_failure_keeps_durable_result_without_completion_manifest(tmp_path, monkeypatch):
    from nordtrace.smoke import run_smoke

    source = tmp_path / "input.jsonl"
    source.write_text('{"organisation_number":"invalid"}\n')
    original_settings = settings.model_dump()
    def failed_verification(*args, **kwargs):
        raise ValueError("injected export integrity failure")
    monkeypatch.setattr("nordtrace.smoke.verify_bundle", failed_verification)
    with pytest.raises(ValueError, match="integrity"):
        asyncio.run(run_smoke(source, tmp_path / "output", configuration=RunConfiguration(
            max_requests=0, max_runtime_sec=30, max_cost_usd=0), concurrency=1, revision="fixture"))
    assert not (tmp_path / "output/manifest.json").exists()
    assert (tmp_path / "output/research.db").exists()
    assert json.loads((tmp_path / "output/results.json").read_text())["results"]
    assert settings.model_dump() == original_settings


def test_smoke_reports_unaccounted_dispatch_as_failure(tmp_path, monkeypatch):
    from nordtrace.benchmark import BenchmarkHarness
    from nordtrace.smoke import run_smoke

    source = tmp_path / "input.jsonl"
    source.write_text('{"organisation_number":"invalid"}\n')
    original = BenchmarkHarness.evaluate_batch
    async def with_hidden_request(self, *args, **kwargs):
        report = await original(self, *args, **kwargs)
        async with httpx.AsyncClient(trust_env=False) as client:
            await client.get("https://fixture.example/")
        return report
    async def transport(self, request):
        return httpx.Response(200)
    monkeypatch.setattr(BenchmarkHarness, "evaluate_batch", with_hidden_request)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", transport)
    manifest, code = asyncio.run(run_smoke(source, tmp_path / "output", configuration=RunConfiguration(
        max_requests=0, max_runtime_sec=30, max_cost_usd=0), concurrency=1, revision="fixture"))
    assert code == 1
    assert manifest["transport"]["dispatches"] == 1
    assert manifest["transport"]["gateway_operations"] == 0
    assert manifest["transport"]["matches"] is False


def test_smoke_fails_observed_runtime_overrun_during_finalization(tmp_path, monkeypatch):
    from nordtrace.core.repository import Repository
    from nordtrace.smoke import run_smoke

    source = tmp_path / "input.jsonl"
    source.write_text('{"organisation_number":"982463718"}\n')
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda _: ["8.8.8.8"])
    original = Repository.publish_result
    def delayed(self, *args, **kwargs):
        time.sleep(.3)
        return original(self, *args, **kwargs)
    async def transport(self, request):
        return httpx.Response(404)
    monkeypatch.setattr(Repository, "publish_result", delayed)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", transport)
    manifest, code = asyncio.run(run_smoke(source, tmp_path / "output", configuration=RunConfiguration(
        max_requests=2, max_runtime_sec=.2, max_cost_usd=0), concurrency=1, revision="fixture"))
    assert manifest["terminal_counts"] == {"not_available": 1}
    assert code == 1
    assert manifest["budget_adherence"]["runtime_ok"] is False


def test_smoke_runtime_includes_bundle_verification(tmp_path, monkeypatch):
    from nordtrace.smoke import run_smoke

    source = tmp_path / "input.jsonl"
    source.write_text('{"organisation_number":"invalid"}\n')
    def delayed(*args, **kwargs):
        time.sleep(.3)
        return verify_bundle(*args, **kwargs)
    monkeypatch.setattr("nordtrace.smoke.verify_bundle", delayed)
    manifest, code = asyncio.run(run_smoke(source, tmp_path / "output", configuration=RunConfiguration(
        max_requests=0, max_runtime_sec=.2, max_cost_usd=0), concurrency=1, revision="fixture"))
    assert json.loads((tmp_path / "output/report.json").read_text())["budgets"]["runtime_ok"] is True
    assert code == 1
    assert manifest["budget_adherence"]["runtime_ok"] is False

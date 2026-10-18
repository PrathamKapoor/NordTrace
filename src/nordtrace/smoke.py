"""Dedicated-process deterministic smoke runs; no official accuracy/score claims."""
from __future__ import annotations

import hashlib
import math
import subprocess
import threading
import time
from pathlib import Path

import httpx

from nordtrace.benchmark import BenchmarkHarness
from nordtrace.core.budget import BudgetManager
from nordtrace.core.config import settings
from nordtrace.core.contracts import batch_payload, write_json_atomic
from nordtrace.core.export import export_run, verify_bundle
from nordtrace.core.models import RunConfiguration, utcnow
from nordtrace.core.repository import Repository

_AUDIT_LOCK = threading.Lock()
SMOKE_SETTINGS = {
    "brreg_base_url": "https://data.brreg.no/enhetsregisteret/api",
    "brreg_regnskap_url": "https://data.brreg.no/regnskapsregisteret/regnskap",
    "brreg_timeout": 8.0, "crawl_timeout": 8.0, "max_pages_per_company": 2,
    "max_response_bytes": 1024 * 1024, "max_pdf_bytes": 4 * 1024 * 1024,
    "max_redirects": 5, "brreg_branch_page_size": 20, "brreg_branch_max_pages": 10,
    "respect_robots": True,
    "user_agent": "NordTrace/1.0 (Norwegian company research agent; research use; contact via repository)",
    "max_api_cost_usd": 0.0, "llm_max_cost_usd": 0.0,
}


def source_revision() -> str:
    """A release smoke must be traceable to the installed checkout's clean HEAD."""
    root = Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        raise ValueError("smoke requires an installed source checkout with Git provenance")
    status = subprocess.run(["git", "status", "--porcelain"], cwd=root, check=True,
                            capture_output=True, text=True).stdout
    if status.strip():
        raise ValueError("smoke requires a clean committed checkout; preserve unrelated work before running")
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                          capture_output=True, text=True).stdout.strip()


class TransportAudit:
    """Observe HTTPX transport dispatch, below the gateway's pinned DNS transport.

    Dedicated process only: the patch covers every async HTTPX operation in this
    process, including unrelated clients. It does not measure DNS or TCP packets.
    No query values, response bodies or headers are retained here.
    """

    def __init__(self):
        self.operations: list[dict] = []

    def __enter__(self):
        if not _AUDIT_LOCK.acquire(blocking=False):
            raise RuntimeError("transport audit already active")
        self.original = httpx.AsyncHTTPTransport.handle_async_request
        original = self.original
        operations = self.operations

        async def observed(transport, request):
            if any(name in request.headers for name in ("authorization", "proxy-authorization", "cookie")):
                raise ValueError("credential-bearing transport is forbidden in a public smoke run")
            started = time.monotonic()
            operation = {
                "index": len(operations), "started_at": utcnow().isoformat(),
                "method": request.method, "host": request.headers.get("host", request.url.host),
                "destination": request.url.host, "path": request.url.path,
                "query_sha256": hashlib.sha256(request.url.query).hexdigest(),
                "outcome": "pending",
            }
            operations.append(operation)
            try:
                response = await original(transport, request)
                operation["outcome"] = "response_headers"
                operation["http_status"] = response.status_code
                return response
            except BaseException as error:
                operation["outcome"] = type(error).__name__
                raise
            finally:
                # Dispatch-to-headers/error duration excludes response streaming.
                operation["duration_sec"] = time.monotonic() - started

        httpx.AsyncHTTPTransport.handle_async_request = observed  # type: ignore[method-assign]
        return self

    def __exit__(self, *args):
        httpx.AsyncHTTPTransport.handle_async_request = self.original  # type: ignore[method-assign]
        _AUDIT_LOCK.release()


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


async def run_smoke(
    input_file: Path, output: Path, *, configuration: RunConfiguration,
    concurrency: int, revision: str,
) -> tuple[dict, int]:
    """Retain artifacts even for normal company failures; manifest is written last.

    Caller owns a dedicated process, an explicit live opt-in and revision provenance.
    Unexpected errors leave durable DB/artifacts without a completion manifest.
    """
    from nordtrace.cli import _read_batch_inputs, _result_exit_code

    if configuration.max_cost_usd != 0:
        raise ValueError("public smoke requires a zero model/API cost allowance")
    if type(concurrency) is not int or not 1 <= concurrency <= 16:
        raise ValueError("smoke concurrency must be between 1 and 16")
    if not revision:
        raise ValueError("revision provenance is required")
    if input_file.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("smoke input exceeds 16 MiB")
    raw = input_file.read_bytes()
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("smoke input exceeds 16 MiB")
    output.mkdir(parents=True, exist_ok=False)
    # Parse the exact retained bytes rather than reopening a mutable external file.
    retained = output / ("inputs.jsonl" if input_file.suffix.lower() == ".jsonl" else "inputs.csv")
    with retained.open("xb") as stream:
        stream.write(raw)
    inputs = _read_batch_inputs(str(retained))
    if not inputs or len(inputs) > 10000:
        raise ValueError("smoke requires between 1 and 10000 supplied inputs")
    started = utcnow().isoformat()
    wall_start = time.monotonic()
    original_settings = settings.model_dump()
    repo = None
    try:
        for name, value in SMOKE_SETTINGS.items():
            setattr(settings, name, value)
        settings.llm_api_key = None
        settings.data_dir = str(output)
        settings.database_path = str(output / "research.db")
        repo = Repository(settings.database_path)
        budget = BudgetManager(
            max_requests=configuration.max_requests, max_runtime_sec=configuration.max_runtime_sec,
            max_cost=0, per_company_soft_sec=configuration.per_company_sec,
            finalization_reserve_sec=configuration.finalization_reserve_sec,
        )
        audit = TransportAudit()
        try:
            with audit:
                report = await BenchmarkHarness(repo).evaluate_batch(inputs, concurrency, budget=budget)
        finally:
            write_json_atomic(output / "transport.json", {
                "schema_version": "nordtrace-transport-observation-v1",
                "definition": "HTTPX async dispatches, not DNS/TCP packets; durations to headers/error",
                "operations": audit.operations,
            })
        run = repo.get_run(report["run_id"])
        if run is None:
            raise ValueError("smoke run disappeared")
        profiles = repo.get_results(run.run_id)
        write_json_atomic(output / "results.json", batch_payload(
            run, profiles, repo.get_run_inputs(run.run_id),
        ))
        write_json_atomic(output / "report.json", report)
        bundle = export_run(repo, run.run_id, output / "evidence.zip")
        if verify_bundle(output / "evidence.zip") != bundle:
            raise ValueError("offline bundle verification disagrees with export")
        telemetry = report["budgets"]["request_telemetry"]
        matches = len(audit.operations) == telemetry["transport_operations"]
        durations = sorted(p.research_metadata.duration_sec for p in profiles
                           if p.research_metadata.duration_sec is not None
                           and math.isfinite(p.research_metadata.duration_sec)
                           and p.research_metadata.duration_sec >= 0)
        artifacts = {name: _digest(output / name) for name in (
            retained.name, "transport.json", "results.json", "report.json", "evidence.zip",
        )}
        wall_duration = time.monotonic() - wall_start
        manifest = {
            "schema_version": "nordtrace-observed-smoke-v1", "artifacts_complete": True,
            "revision": revision, "run_id": run.run_id, "started_at": started,
            "completed_at": utcnow().isoformat(), "wall_duration_sec": wall_duration,
            "input_sha256": hashlib.sha256(raw).hexdigest(), "input_count": len(inputs),
            "unique_results": len(profiles), "configuration": configuration.model_dump(mode="json"),
            "concurrency": concurrency, "effective_settings": SMOKE_SETTINGS,
            "mode": "deterministic_public_sources_no_models", "third_party_api_cost_usd": 0,
            "cost_basis": "No authenticated/paid source or model enabled; excludes infrastructure costs",
            "terminal_counts": report["terminal_counts"], "transport": {
                "dispatches": len(audit.operations), "gateway_operations": telemetry["transport_operations"],
                "matches": matches, "precision": "exact dispatch count; not network packets",
                "charged_reservations": report["budgets"]["requests_used"],
                "unresolved_reservations": telemetry["unresolved_reservations"],
            },
            "budget_adherence": {
                "requests_ok": report["budgets"]["requests_ok"], "cost_ok": report["budgets"]["cost_ok"],
                "research_runtime_ok": report["budgets"]["runtime_ok"],
                "runtime_ok": wall_duration <= configuration.max_runtime_sec,
                "runtime_scope": "research, support validation, export and offline bundle verification",
            },
            "latency": {"definition": "company duration; excludes queue waits; nearest-rank quantiles",
                        "measured": len(durations), "missing": len(profiles) - len(durations),
                        "p50_sec": durations[math.ceil(len(durations) * .5) - 1] if durations else None,
                        "p95_sec": durations[math.ceil(len(durations) * .95) - 1] if durations else None},
            "independent_accuracy": report["independent_accuracy"], "artifact_sha256": artifacts,
            "limitations": ["Local smoke configuration, not confirmed organizer limits/schema",
                            "Support replay is not independent factual accuracy or recall",
                            "Synchronous parsing/storage/export are not hard deadline bounded",
                            "Database contains captured public content; inspect rights before sharing"],
        }
        exit_code = _result_exit_code(profiles)
        if (not matches or telemetry["unresolved_reservations"] or report["support_validation"]["failures"]
                or not all(manifest["budget_adherence"][name] for name in (
                    "requests_ok", "cost_ok", "research_runtime_ok", "runtime_ok",
                ))):
            exit_code = 1
        manifest["exit_code"] = exit_code
        write_json_atomic(output / "manifest.json", manifest)
        return manifest, exit_code
    finally:
        if repo is not None:
            repo.close()
        for name, value in original_settings.items():
            setattr(settings, name, value)

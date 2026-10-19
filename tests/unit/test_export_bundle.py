"""Portable local audit bundles; fixture transport is not live research."""

import asyncio
import hashlib
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.contracts import map_inputs
from nordtrace.core.models import ResearchRun, utcnow
from nordtrace.core.repository import Repository
from nordtrace.engine.pipeline import ResearchPipeline

ORG = "982463718"


def test_versioned_schemas_preserve_v1_and_bind_current_contract_without_shared_mutation():
    from nordtrace.core.export import result_schema
    from nordtrace.core.models import CompanyProfile

    original = result_schema("1.3")
    assert original == CompanyProfile.model_json_schema()
    schemas = Path(__file__).parents[2] / "src/nordtrace/core/schemas"
    for name, digest in (
        ("result-1.1.json", "82654e3f43a005feb3c339c000d1c601043de11dbff9ec6ac48a83bd31b3f403"),
        ("result-1.2.json", "c0dcf61b0ca58bc984a27c1df3172fff275c4547c442b7e17222d9446b4189b1"),
    ):
        assert hashlib.sha256((schemas / name).read_bytes()).hexdigest() == digest
    assert "JsonNumberLocator" not in result_schema("1.2")["$defs"]
    original["$defs"]["RunConfiguration"]["properties"].clear()
    assert result_schema("1.3") == CompanyProfile.model_json_schema()


@pytest.mark.parametrize("version", [
    "1.4", "../models.py", "", "https://untrusted.example/schema", "1.1\x00",
])
def test_unknown_contract_versions_cannot_select_a_resource_path(version):
    from nordtrace.core.export import result_schema

    with pytest.raises(ValueError, match="unsupported local result schema version"):
        result_schema(version)


def test_versioned_export_schema_does_not_drift_with_runtime_generator(researched, tmp_path, monkeypatch):
    from nordtrace.core.export import export_run
    from nordtrace.core.models import CompanyProfile

    repo, run_id = researched
    baseline = tmp_path / "baseline.zip"
    export_run(repo, run_id, baseline)
    with zipfile.ZipFile(baseline) as archive:
        original_schema = archive.read("result-schema.json")
    future_schema = json.loads(original_schema)
    future_schema["properties"]["future_field"] = {"type": "string"}
    monkeypatch.setattr(CompanyProfile, "model_json_schema", lambda: future_schema)
    output = tmp_path / "after-model-drift.zip"
    export_run(repo, run_id, output)
    with zipfile.ZipFile(output) as archive:
        assert archive.read("result-schema.json") == original_schema


def test_retained_bundle_remains_readable_when_runtime_generator_changes(researched, tmp_path, monkeypatch):
    from nordtrace.core.export import export_run, verify_bundle
    from nordtrace.core.models import CompanyProfile

    repo, run_id = researched
    output = tmp_path / "retained.zip"
    export_run(repo, run_id, output)
    future_schema = CompanyProfile.model_json_schema()
    future_schema["properties"]["future_field"] = {"type": "string"}
    monkeypatch.setattr(CompanyProfile, "model_json_schema", lambda: future_schema)
    assert verify_bundle(output)["completion"]["complete"] is True


@pytest.fixture
def researched(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "research.db")
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    repo.save_run_inputs(run.run_id, [item.model_dump() for item in map_inputs([ORG, ORG])])
    budget = BudgetManager(max_requests=20)
    budget.bind_run(repo, run.run_id, initialize=True)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    def respond(request):
        if request.url.path.endswith("/enheter/" + ORG):
            return httpx.Response(200, json={
                "organisasjonsnummer": ORG, "navn": "PORTABLE FIXTURE AS", "antallAnsatte": 0,
            })
        return httpx.Response(404)

    async def execute():
        pipeline = ResearchPipeline(repo, budget)
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()

    asyncio.run(execute())
    yield repo, run.run_id
    repo.close()


def test_bundle_retains_canonical_jsonl_and_revalidates_offline_after_database_closes(
    researched, tmp_path, monkeypatch,
):
    from nordtrace.core.export import export_run, verify_bundle

    repo, run_id = researched
    result = repo.get_result(run_id, ORG)
    output = tmp_path / "audit.zip"
    manifest = export_run(repo, run_id, output)
    assert manifest["completion"] == {"complete": True, "input_count": 2, "result_count": 1}
    assert [item["supplied"] for item in manifest["inputs"]] == [ORG, ORG]
    assert manifest["operations"]["scope"] == "whole_run"
    assert manifest["operations"]["requests"] == repo.get_run_budget(run_id)[1]
    telemetry = manifest["operations"]["budget"]["telemetry"]
    assert telemetry["total_used"] == manifest["operations"]["requests"]
    assert telemetry["remaining"] == 20 - telemetry["total_used"]
    assert telemetry["transport_operations"] == telemetry["successful"] + telemetry["failed"]
    with zipfile.ZipFile(output) as archive:
        body = archive.read("results.jsonl")
        assert len(body.splitlines()) == 1
        assert json.loads(body) == result.model_dump(mode="json")
        assert hashlib.sha256(body).hexdigest() == manifest["results_sha256"]
        assert archive.namelist()[-1] == "manifest.json"
        assert all(archive.read(item["path"]) for item in manifest["captures"].values())
    repo.close()
    monkeypatch.setattr("nordtrace.core.request_gateway.RequestGateway.fetch", forbidden_network)
    assert verify_bundle(output)["completion"] == manifest["completion"]


async def forbidden_network(*args, **kwargs):
    pytest.fail("offline verification attempted acquisition")


@pytest.mark.parametrize("extra_policy", [False, True])
def test_legacy_schema_bundle_replays_without_admitting_new_policy_fields(tmp_path, extra_policy):
    from nordtrace.core.export import export_run, verify_bundle
    from nordtrace.engine.runner import BatchRunner

    repo = Repository(tmp_path / "legacy.db")
    try:
        run = asyncio.run(BatchRunner(repo).run_batch(["invalid"]))
        current = tmp_path / "current.zip"
        export_run(repo, run.run_id, current)
    finally:
        repo.close()
    with zipfile.ZipFile(current) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    schema = json.loads(entries["result-schema.json"])
    schema["$defs"]["RunConfiguration"]["properties"].pop("allowed_source_origins")
    entries["result-schema.json"] = json.dumps(schema).encode()
    for name in ("results.jsonl", "starter-example.jsonl"):
        result = json.loads(entries[name])
        config = result["research_metadata"]["run_configuration"]
        config.pop("allowed_source_origins")
        if extra_policy and name == "results.jsonl":
            config["allowed_source_origins"] = ["https://data.brreg.no"]
        entries[name] = (json.dumps(result) + "\n").encode()
    manifest = json.loads(entries["manifest.json"])
    manifest["schema_sha256"] = hashlib.sha256(entries["result-schema.json"]).hexdigest()
    manifest["results_sha256"] = hashlib.sha256(entries["results.jsonl"]).hexdigest()
    manifest["projections"]["starter-example-v1"]["sha256"] = hashlib.sha256(
        entries["starter-example.jsonl"]).hexdigest()
    entries["manifest.json"] = json.dumps(manifest).encode()
    legacy = tmp_path / "legacy.zip"
    with zipfile.ZipFile(legacy, "w") as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    if extra_policy:
        with pytest.raises(ValueError, match="legacy.*policy"):
            verify_bundle(legacy)
    else:
        assert verify_bundle(legacy)["completion"]["complete"] is True


@pytest.mark.parametrize("failure", ["missing_blob", "unsupported_value", "missing_result", "bad_mapping"])
def test_incomplete_or_unsupported_bundle_never_appears_complete(researched, tmp_path, failure):
    from nordtrace.core.export import export_run

    repo, run_id = researched
    if failure == "missing_blob":
        # Deliberate corruption fixture bypasses FK protection on this temporary DB only.
        repo.conn.execute("PRAGMA foreign_keys=OFF")
        repo.conn.execute("DELETE FROM snapshot_blobs")
    elif failure == "missing_result":
        repo.conn.execute("DELETE FROM company_results")
    elif failure == "bad_mapping":
        repo.conn.execute("UPDATE run_inputs SET inputs_json='[]'")
    else:
        result = repo.get_result(run_id, ORG).model_dump(mode="json")
        result["facts"][0]["value"] = "INVENTED"
        repo.conn.execute("UPDATE company_results SET payload_json=?", (json.dumps(result),))
    repo.conn.commit()
    output = tmp_path / "incomplete.zip"
    with pytest.raises((ValueError, KeyError)):
        export_run(repo, run_id, output)
    assert not output.exists()
    assert not list(tmp_path.glob("incomplete.zip.*.tmp"))


def test_existing_output_is_preserved_and_capacity_failure_is_atomic(researched, tmp_path):
    from nordtrace.core.export import export_run

    repo, run_id = researched
    output = tmp_path / "existing.zip"
    output.write_bytes(b"user artifact")
    with pytest.raises(FileExistsError):
        export_run(repo, run_id, output)
    assert output.read_bytes() == b"user artifact"
    limited = tmp_path / "limited.zip"
    with pytest.raises(ValueError, match="capacity"):
        export_run(repo, run_id, limited, max_bytes=10)
    assert not limited.exists()


def test_tampered_portable_snapshot_is_rejected(researched, tmp_path):
    from nordtrace.core.export import export_run, verify_bundle

    repo, run_id = researched
    output = tmp_path / "audit.zip"
    export_run(repo, run_id, output)
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(output) as original, zipfile.ZipFile(tampered, "w") as changed:
        for item in original.infolist():
            body = original.read(item.filename)
            changed.writestr(item.filename, b"tampered" if item.filename.startswith("objects/") else body)
    with pytest.raises(ValueError, match="integrity"):
        verify_bundle(tampered)


def test_cli_batch_bundle_and_offline_verifier_share_canonical_results(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from nordtrace.cli import cli

    database = tmp_path / "cli.db"
    monkeypatch.setattr("nordtrace.cli._repo", lambda: Repository(database))
    source = tmp_path / "input.jsonl"
    source.write_text('{"organisation_number":"invalid"}\n', encoding="utf-8")
    bundle = tmp_path / "bundle.zip"
    runner = CliRunner()
    result = runner.invoke(cli, ["batch", str(source), "--bundle", str(bundle)])
    assert result.exit_code == 2, result.output
    assert bundle.exists()
    with zipfile.ZipFile(bundle) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    # Offline verification must not open the original database at all.
    monkeypatch.setattr("nordtrace.cli._repo", lambda: pytest.fail("database opened"))
    checked = runner.invoke(cli, ["verify-bundle", str(bundle)])
    assert checked.exit_code == 0, checked.output
    assert json.loads(checked.output)["run_id"] == manifest["run_id"]


def test_cli_export_run_uses_only_durable_results(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from nordtrace.cli import cli
    from nordtrace.engine.runner import BatchRunner

    database = tmp_path / "durable.db"
    repo = Repository(database)
    run = asyncio.run(BatchRunner(repo).run_batch(["invalid"]))
    repo.close()
    monkeypatch.setattr("nordtrace.cli._repo", lambda: Repository(database))
    monkeypatch.setattr("nordtrace.core.request_gateway.RequestGateway.fetch", forbidden_network)
    output = tmp_path / "durable.zip"
    result = CliRunner().invoke(cli, ["export-run", run.run_id, "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert output.exists()


@pytest.mark.parametrize("mutation", ["unsupported_claim", "unsafe_object_path", "unknown_member"])
def test_bundle_verifier_rejects_semantic_or_reference_tampering(researched, tmp_path, mutation):
    from nordtrace.core.export import export_run, verify_bundle

    repo, run_id = researched
    output = tmp_path / "original.zip"
    export_run(repo, run_id, output)
    with zipfile.ZipFile(output) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(entries["manifest.json"])
    if mutation == "unsupported_claim":
        result = json.loads(entries["results.jsonl"])
        fact = next(item for item in result["facts"] if item["field"] == "legal_name")
        fact["value"] = fact["normalized_value"] = "INVENTED AS"
        result["company"]["legal_name"] = "INVENTED AS"
        entries["results.jsonl"] = (json.dumps(result) + "\n").encode()
        # A recomputed file hash must not bypass actual retained-value support checks.
        manifest["results_sha256"] = hashlib.sha256(entries["results.jsonl"]).hexdigest()
    elif mutation == "unsafe_object_path":
        next(iter(manifest["captures"].values()))["path"] = "../../outside.bin"
    else:
        entries["../../outside.bin"] = b"not extracted"
    entries["manifest.json"] = json.dumps(manifest).encode()
    tampered = tmp_path / "semantic.zip"
    with zipfile.ZipFile(tampered, "w") as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    with pytest.raises(ValueError):
        verify_bundle(tampered)
    assert not (tmp_path.parent / "outside.bin").exists()


def test_legacy_budget_failure_still_exports_without_inventing_accounting(tmp_path):
    from nordtrace.core.export import export_run, verify_bundle
    from nordtrace.core.models import CompanyProfile, ResearchError

    repo = Repository(tmp_path / "legacy.db")
    run = ResearchRun(companies=[ORG])
    repo.create_run(run)
    repo.save_run_inputs(run.run_id, [item.model_dump() for item in map_inputs([ORG])])
    repo.save_result(CompanyProfile(
        run_id=run.run_id, organisation_number=ORG, status="failed",
        errors=[ResearchError(code="run_budget_unavailable", message="Original budget missing")],
    ))
    try:
        output = tmp_path / "legacy.zip"
        manifest = export_run(repo, run.run_id, output)
        assert manifest["operations"]["accounting_state"] == "unavailable"
        assert manifest["operations"]["requests"] is None
        assert manifest["operations"]["estimated_cost_usd"] is None
        assert manifest["operations"]["budget"] is None
        assert verify_bundle(output)["completion"]["result_count"] == 1
    finally:
        repo.close()


def test_batch_refuses_overlapping_export_targets_before_research(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from nordtrace.cli import cli

    source = tmp_path / "input.jsonl"
    source.write_text('{"organisation_number":"invalid"}\n', encoding="utf-8")
    target = tmp_path / "same.zip"
    monkeypatch.setattr("nordtrace.cli._repo", lambda: pytest.fail("repository opened"))
    result = CliRunner().invoke(cli, [
        "batch", str(source), "--bundle", str(target), "--output", str(target),
    ])
    assert result.exit_code == 2 and "different" in result.output
    assert not target.exists()


@pytest.mark.parametrize("mutation", [
    "missing_operations", "false_accounting", "schema_label", "schema_file", "stale_telemetry",
])
def test_bundle_verifier_checks_required_manifest_and_schema(tmp_path, mutation):
    from nordtrace.core.export import export_run, verify_bundle
    from nordtrace.engine.runner import BatchRunner

    repo = Repository(tmp_path / "manifest.db")
    run = asyncio.run(BatchRunner(repo).run_batch(["invalid"]))
    original = tmp_path / "original.zip"
    export_run(repo, run.run_id, original)
    repo.close()
    with zipfile.ZipFile(original) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(entries["manifest.json"])
    if mutation == "missing_operations":
        del manifest["operations"]
    elif mutation == "false_accounting":
        manifest["operations"]["accounting_state"] = "unavailable"  # But still has non-null totals/budget.
    elif mutation == "schema_label":
        manifest["result_schema"] = "invented-official-format"
    elif mutation == "stale_telemetry":
        manifest["operations"]["budget"]["telemetry"]["total_used"] = 99
    else:
        entries["result-schema.json"] = b'{}'
    entries["manifest.json"] = json.dumps(manifest).encode()
    output = tmp_path / "bad-manifest.zip"
    with zipfile.ZipFile(output, "w") as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    with pytest.raises((ValueError, KeyError)):
        verify_bundle(output)

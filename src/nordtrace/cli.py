"""NordTrace CLI — real commands wired to the research engine.

python -m nordtrace research <orgnr> [--output FILE]
python -m nordtrace batch <csv> [--concurrency N] [--resume RUN_ID]
python -m nordtrace resume <run_id>
python -m nordtrace benchmark --orgnr-file FILE
python -m nordtrace validate <result-file>
python -m nordtrace serve [--port N]
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import logging
import math
import sys
import zipfile
from pathlib import Path
from typing import List, Optional

import click

from nordtrace.core.budget import BudgetManager
from nordtrace.core.config import settings
from nordtrace.core.contracts import batch_payload, build_result, write_bytes_atomic, write_json_atomic
from nordtrace.core.export import DEFAULT_MAX_BYTES, export_run, verify_bundle
from nordtrace.core.models import CompanyProfile
from nordtrace.core.repository import Repository
from nordtrace.engine.runner import BatchRunner
from nordtrace.sampling import PUBLIC_SHA256, PUBLIC_UNCOMPRESSED_SHA256, sample_universe


def _repo() -> Repository:
    return Repository(settings.database_path)


def _result_json(outcome, run_id: str, budget: BudgetManager, started_at: str) -> dict:
    return build_result(outcome, run_id, budget, started_at).model_dump(mode="json")


def _result_exit_code(results: List[CompanyProfile]) -> int:
    if any(result.status == "failed" for result in results):
        return 1
    if any(error.code == "invalid_organisation_number" for result in results for error in result.errors):
        return 2
    return 0


@click.group()
@click.option("--debug", is_flag=True, default=False, help="Verbose logging")
@click.pass_context
def cli(ctx, debug: bool):
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)


@cli.command("replay-source")
@click.argument("source_id")
@click.option("--output", required=True, type=click.Path(dir_okay=False))
def replay_source(source_id: str, output: str):
    """Export integrity-verified retained response bytes, entirely offline."""
    repo = _repo()
    try:
        source, body = repo.read_capture(source_id)
        write_bytes_atomic(output, body)
        click.echo(json.dumps({
            "source_id": source_id, "content_hash": source.content_hash,
            "representation": source.snapshot_representation,
            "retrieved_at": source.retrieved_at, "bytes": len(body), "output": output,
        }))
    except (KeyError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    finally:
        repo.close()


@cli.command("sample-universe")
@click.argument("source", type=click.Path(exists=True, dir_okay=False))
@click.option("--output", required=True, type=click.Path(file_okay=False))
@click.option("--seed", required=True)
@click.option("--development-size", type=click.IntRange(min=0), default=100, show_default=True)
@click.option("--held-out-size", type=click.IntRange(min=0), default=100, show_default=True)
@click.option("--expected-sha256", default=PUBLIC_SHA256, show_default=True)
@click.option("--expected-uncompressed-sha256", default=PUBLIC_UNCOMPRESSED_SHA256, show_default=True)
@click.option("--max-uncompressed-bytes", type=click.IntRange(min=1), default=256 * 1024 * 1024)
def sample_universe_command(source: str, output: str, seed: str, development_size: int, held_out_size: int,
                            expected_sha256: str, expected_uncompressed_sha256: str,
                            max_uncompressed_bytes: int):
    """Select disjoint reproducible metadata samples offline; no company research."""
    try:
        manifest = sample_universe(
            source, output, seed=seed, development_size=development_size, held_out_size=held_out_size,
            expected_sha256=expected_sha256, expected_uncompressed_sha256=expected_uncompressed_sha256,
            max_uncompressed_bytes=max_uncompressed_bytes,
        )
    except (OSError, EOFError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(json.dumps({"output": output, "source_record_count": manifest["source_record_count"],
                           "splits": {split: info["count"] for split, info in manifest["splits"].items()}}))


@cli.command("export-run")
@click.argument("run_id")
@click.option("--output", required=True, type=click.Path(dir_okay=False))
@click.option("--max-bytes", type=click.IntRange(min=1), default=DEFAULT_MAX_BYTES, show_default=True)
def export_run_command(run_id: str, output: str, max_bytes: int):
    """Export complete durable canonical JSONL results and retained bytes offline."""
    repo = _repo()
    try:
        manifest = export_run(repo, run_id, output, max_bytes=max_bytes)
    except (OSError, ValueError, KeyError) as error:
        raise click.ClickException(str(error)) from error
    finally:
        repo.close()
    click.echo(json.dumps({"run_id": run_id, "output": output, "completion": manifest["completion"]}))


@cli.command("verify-bundle")
@click.argument("bundle", type=click.Path(exists=True, dir_okay=False))
@click.option("--max-bytes", type=click.IntRange(min=1), default=DEFAULT_MAX_BYTES, show_default=True)
def verify_bundle_command(bundle: str, max_bytes: int):
    """Verify portable canonical evidence offline without opening a database."""
    try:
        manifest = verify_bundle(bundle, max_bytes=max_bytes)
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        raise click.ClickException(str(error)) from error
    click.echo(json.dumps({"run_id": manifest["run_id"], "completion": manifest["completion"]}))


@cli.command("verify-snapshots")
@click.argument("run_id")
@click.pass_context
def verify_snapshots(ctx, run_id: str):
    """Verify captures referenced by a run; this does not prove claim support."""
    repo = _repo()
    checks = []
    try:
        if repo.get_run(run_id) is None:
            raise click.ClickException("run not found")
        sources = {
            source.source_id: source for result in repo.get_results(run_id)
            for source in result.sources if source.access_status == "success"
        }
        for source_id, expected in sources.items():
            try:
                captured, body = repo.read_capture(source_id)
                if captured.content_hash != expected.content_hash:
                    raise ValueError("result and capture hashes disagree")
                checks.append({"source_id": source_id, "status": "verified", "bytes": len(body)})
            except (KeyError, ValueError) as error:
                checks.append({"source_id": source_id, "status": "failed", "error": str(error)})
    finally:
        repo.close()
    click.echo(json.dumps({"run_id": run_id, "sources": checks}))
    if any(check["status"] == "failed" for check in checks):
        ctx.exit(1)


@cli.command()
@click.argument("org_number")
@click.option("--output", type=str, default=None, help="Write result JSON to file")
@click.pass_context
def research(ctx, org_number: str, output: Optional[str]):
    """Research a single Norwegian company by organisation number."""
    repo = _repo()
    runner = BatchRunner(repo)
    try:
        run = asyncio.run(runner.run_batch([org_number]))
        result = repo.get_results(run.run_id)[0]
    finally:
        repo.close()
    if output:
        write_json_atomic(output, result.model_dump(mode="json"))
        click.echo(f"Result written to {output}")
    click.echo(f"Company: {result.company.legal_name if result.company else '(not found)'}")
    click.echo(f"Status: {result.status}")
    click.echo(
        f"Published facts: {len(result.facts)} | Evidence: {len(result.evidence)} | "
        f"Sources: {len(result.sources)}"
    )
    click.echo(
        f"Requests: {run.request_count}/{runner.budget.requests.global_limit} | "
        f"Cost: ${run.estimated_cost_usd:.4f}"
    )
    if result.summary:
        click.echo(f"\nSummary: {result.summary}")
    for error in result.errors:
        click.echo(f"{error.code}: {error.message}", err=True)
    ctx.exit(_result_exit_code([result]))


def _read_csv(path: str) -> List[str]:
    """Read first-column inputs; only an exact first-record label is a header."""
    orgs: List[str] = []
    headers = {"orgnr", "org_number", "organisation_number", "organization_number", "organisasjonsnummer"}
    first_record = True
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f, strict=True):
                if not row:  # Physical blank lines are separators, not supplied empty fields.
                    continue
                val = row[0].strip()
                is_header = first_record and val.casefold() in headers
                first_record = False
                if not is_header:
                    orgs.append(val)
    except (OSError, UnicodeError, csv.Error) as error:
        raise click.ClickException(f"Cannot read company input: {error}") from error
    return orgs


def _json_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError("non-finite JSON constant")


def _finite_json_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON number exceeds finite float range")
    return number


def _read_batch_inputs(path: str, input_format: str = "auto") -> List[str]:
    """Validate the entire input container before starting any research."""
    if input_format == "auto":
        input_format = "jsonl" if Path(path).suffix.casefold() == ".jsonl" else "csv"
    if input_format == "csv":
        return _read_csv(path)
    orgs: List[str] = []
    try:
        with open(path, encoding="utf-8-sig") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(
                        line, object_pairs_hook=_json_object, parse_constant=_reject_json_constant,
                        parse_float=_finite_json_float,
                    )
                    if not isinstance(record, dict) or not isinstance(
                        record.get("organisation_number"), str,
                    ):
                        raise ValueError("expected an object with a string organisation_number")
                    record["organisation_number"].encode("utf-8")
                except (ValueError, RecursionError) as error:
                    raise click.ClickException(
                        f"Invalid JSONL line {line_number}: expected strict JSON with a string "
                        "UTF-8 organisation_number, finite numbers and unique object keys"
                    ) from error
                # Other fields are selection metadata, never identity or run configuration.
                orgs.append(record["organisation_number"])
    except (OSError, UnicodeError) as error:
        raise click.ClickException(f"Cannot read company input: {error}") from error
    return orgs


@cli.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option("--input-format", type=click.Choice(["auto", "csv", "jsonl"]), default="auto",
              show_default=True, help="Auto selects JSONL for .jsonl files; otherwise CSV/TXT")
@click.option("--concurrency", type=int, default=4)
@click.option("--resume", "resume_run_id", type=str, default=None, help="Resume an existing run id")
@click.option("--output", type=str, default=None)
@click.option("--bundle", type=click.Path(dir_okay=False), default=None,
              help="Also export portable canonical JSONL, snapshots and manifest as a ZIP")
@click.option("--export-max-bytes", type=click.IntRange(min=1), default=DEFAULT_MAX_BYTES, show_default=True)
@click.pass_context
def batch(ctx, input_file: str, input_format: str, concurrency: int,
          resume_run_id: Optional[str], output: Optional[str], bundle: Optional[str], export_max_bytes: int):
    """Batch research from CSV/TXT identifiers or JSONL objects."""
    if bundle and output and Path(bundle).resolve() == Path(output).resolve():
        raise click.UsageError("Bundle and JSON output must use different paths")
    orgs = _read_batch_inputs(input_file, input_format)
    click.echo(f"{len(orgs)} inputs")
    if not orgs:
        click.echo("Nothing to research.", err=True)
        sys.exit(2)
    repo = _repo()
    runner = BatchRunner(repo, concurrency=concurrency)
    try:
        run = asyncio.run(runner.run_batch(orgs, resume_run_id=resume_run_id))
        results = repo.get_results(run.run_id)
        payload = batch_payload(run, results, repo.get_run_inputs(run.run_id))
        if bundle:
            try:
                export_run(repo, run.run_id, bundle, max_bytes=export_max_bytes)
            except (OSError, ValueError, KeyError) as error:
                raise click.ClickException(f"Research retained; bundle export failed: {error}") from error
    finally:
        repo.close()
    counts: dict = {}
    for state in run.company_states.values():
        counts[state] = counts.get(state, 0) + 1
    click.echo(f"Run {run.run_id}: state={run.state}")
    for state, n in sorted(counts.items()):
        click.echo(f"  {state}: {n}")
    request_limit = (
        "unknown" if any(error.code == "run_budget_unavailable"
                         for result in results for error in result.errors)
        else str(runner.budget.requests.global_limit)
    )
    click.echo(
        f"Requests: {run.request_count}/{request_limit} | "
        f"Cost: ${run.estimated_cost_usd:.4f} | "
        f"Time: {run.completed_at and 'done'}"
    )
    if output:
        write_json_atomic(output, payload)
        click.echo(f"Complete results written to {output}")
    ctx.exit(_result_exit_code(results))


@cli.command()
@click.argument("run_id")
@click.pass_context
def resume(ctx, run_id: str):
    """Resume an interrupted run (continues with unfinished companies)."""
    repo = _repo()
    run = repo.get_run(run_id)
    if run is None:
        click.echo(f"Run {run_id} not found.", err=True)
        sys.exit(1)
    unfinished = repo.unfinished_companies(run_id)
    click.echo(f"Run {run_id}: {len(run.company_states)} finished, {len(unfinished)} unfinished")
    if not unfinished:
        click.echo("Nothing to resume.")
        results = repo.get_results(run_id)
        repo.close()
        ctx.exit(_result_exit_code(results))
    runner = BatchRunner(repo)
    try:
        run2 = asyncio.run(runner.run_batch(unfinished, resume_run_id=run_id))
        results = repo.get_results(run_id)
    finally:
        repo.close()
    click.echo(f"Resumed: {len(run2.company_states)} companies now have terminal states")
    ctx.exit(_result_exit_code(results))


@cli.command()
@click.option(
    "--orgnr-file", type=click.Path(exists=True, dir_okay=False), required=True,
    help="Supplied reproducible CSV/TXT/JSONL organisation-number sample",
)
@click.option("--input-format", type=click.Choice(["auto", "csv", "jsonl"]), default="auto")
@click.option("--limit", type=click.IntRange(min=1), default=None,
              help="Explicitly select first N input occurrences; default processes every supplied input")
@click.option("--output", type=str, default="benchmark_result.json")
@click.pass_context
def benchmark(ctx, orgnr_file: str, input_format: str, limit: Optional[int], output: str):
    """Measure canonical output and limits on an explicit sample; no implicit discovery."""
    from nordtrace.benchmark import BenchmarkHarness

    if Path(output).resolve() == Path(orgnr_file).resolve():
        raise click.UsageError("Report and supplied input must use different paths")
    try:
        with open(orgnr_file, "rb") as supplied:
            input_hash = hashlib.file_digest(supplied, "sha256").hexdigest()
    except OSError as error:
        raise click.ClickException(f"Cannot hash supplied input: {error}") from error
    orgs = _read_batch_inputs(orgnr_file, input_format)
    if not orgs:
        raise click.UsageError("Nothing to research")
    supplied_count = len(orgs)
    if limit is not None:
        orgs = orgs[:limit]
    try:
        with open(orgnr_file, "rb") as supplied:
            final_hash = hashlib.file_digest(supplied, "sha256").hexdigest()
    except OSError as error:
        raise click.ClickException(f"Cannot recheck supplied input: {error}") from error
    if final_hash != input_hash:
        raise click.ClickException("Supplied input changed during parsing; no research started")
    repo = _repo()
    harness = BenchmarkHarness(repo)
    try:
        click.echo(f"Benchmarking {len(orgs)} companies...")
        report = asyncio.run(harness.evaluate_batch(orgs))
        results = repo.get_results(report["run_id"])
    finally:
        repo.close()
    report["selection"] = {"supplied_input_count": supplied_count, "selected_input_count": len(orgs),
                           "policy": "all_inputs" if limit is None else "explicit_first_n", "limit": limit,
                           "excluded_input_indices": list(range(len(orgs), supplied_count)),
                           "input_file_sha256": input_hash}
    write_json_atomic(output, report)
    _print_benchmark(report)
    click.echo(f"\nReport written to {output}")
    invalid_measurement = report["support_validation"]["failures"] or not all(
        report["budgets"][key] for key in ("requests_ok", "cost_ok", "runtime_ok")
    )
    ctx.exit(1 if invalid_measurement else _result_exit_code(results))


def _print_benchmark(report: dict) -> None:
    b = report.get("budgets", {})
    click.echo(f"Completion: {report.get('completed')}/{report.get('batch_size')}")
    click.echo(f"Entity resolved: {report.get('entity_resolved')}/{report.get('batch_size')}")
    click.echo(f"Ambiguous: {report.get('ambiguous')} | Failed: {report.get('failed')}")
    click.echo(f"Supported claims: {report.get('total_supported_claims')} | "
               f"Evidence: {report.get('total_evidence')}")
    click.echo(f"Non-registry supported claims: {report.get('total_external_supported_claims')}")
    click.echo(f"Rejected candidates: {report.get('total_rejected')}")
    click.echo(
        f"Requests: {b.get('requests_used')}/{b.get('requests_limit')} | "
        f"Cost: ${b.get('cost_used', 0):.4f}/${b.get('cost_limit')} | "
        f"Runtime: {b.get('runtime_sec', 0):.1f}s/{b.get('runtime_limit_sec')}s"
    )
    click.echo(
        f"Budget adherence: requests={'OK' if b.get('requests_ok') else 'EXCEEDED'}, "
        f"cost={'OK' if b.get('cost_ok') else 'EXCEEDED'}, "
        f"runtime={'OK' if b.get('runtime_ok') else 'EXCEEDED'}"
    )
    click.echo("Independent accuracy: not measured (no adjudicated reference)")


@cli.command()
@click.argument("result_file", type=click.Path(exists=True))
@click.pass_context
def validate(ctx, result_file: str):
    """Validate a result file against the result schema."""
    from nordtrace.validate import validate_result

    data = json.loads(Path(result_file).read_text(encoding="utf-8"))
    errors = validate_result(data)
    if errors:
        for e in errors:
            click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)
    click.echo("Validation passed.")


@cli.command("validate-db")
@click.pass_context
def validate_db(ctx):
    """Check database integrity (FKs, duplicates, orphans, contamination)."""
    repo = _repo()
    try:
        issues = repo.integrity_check()
    finally:
        repo.close()
    ok = issues.pop("ok")
    for k, v in issues.items():
        mark = "OK" if v == 0 else "FAIL"
        click.echo(f"  {k}: {v} [{mark}]")
    if not ok:
        click.echo(
            "  (FAIL rows may reflect data written before schema/slot fixes;"
            " a fresh database passes — see VERIFICATION_REPORT.md)"
        )
    if ok:
        click.echo("Database integrity: PASS")
    else:
        click.echo("Database integrity: FAIL", err=True)
        sys.exit(1)


@cli.command()
@click.option("--port", type=int, default=8000)
@click.option("--host", type=str, default="127.0.0.1")
@click.pass_context
def serve(ctx, port: int, host: str):
    """Start the REST API + dashboard."""
    import uvicorn

    uvicorn.run("nordtrace.api.app:app", host=host, port=port, reload=False)


def main():
    cli()


if __name__ == "__main__":
    main()

"""NordTrace CLI — real commands wired to the research engine.

python -m nordtrace research <orgnr> [--output FILE]
python -m nordtrace batch <csv> [--concurrency N] [--resume RUN_ID]
python -m nordtrace resume <run_id>
python -m nordtrace benchmark [--orgnr-file FILE | --fixture]
python -m nordtrace validate <result-file>
python -m nordtrace serve [--port N]
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional

import click

from nordtrace.core.budget import BudgetManager
from nordtrace.core.config import settings
from nordtrace.core.contracts import batch_payload, build_result, write_bytes_atomic, write_json_atomic
from nordtrace.core.models import CompanyProfile
from nordtrace.core.repository import Repository
from nordtrace.engine.runner import BatchRunner


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
    orgs: List[str] = []
    with open(path, encoding="utf-8-sig") as f:
        sample = f.read(2048)
        f.seek(0)
        has_header = "org" in sample.lower().split(",")[0] if sample else False
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            val = row[0].strip()
            if has_header and val.lower().startswith("org"):
                continue
            orgs.append(val)
    return orgs


@cli.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option("--concurrency", type=int, default=4)
@click.option("--resume", "resume_run_id", type=str, default=None, help="Resume an existing run id")
@click.option("--output", type=str, default=None)
@click.pass_context
def batch(ctx, input_file: str, concurrency: int, resume_run_id: Optional[str], output: Optional[str]):
    """Batch research from a CSV/TXT file of organisation numbers."""
    orgs = _read_csv(input_file)
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
    "--orgnr-file", type=click.Path(exists=True), default=None, help="CSV/TXT of orgnrs to benchmark"
)
@click.option("--limit", type=int, default=10, help="Max companies for live benchmark")
@click.option("--output", type=str, default="benchmark_result.json")
@click.pass_context
def benchmark(ctx, orgnr_file: Optional[str], limit: int, output: str):
    """Benchmark harness. Uses real organisations if a file is given;
    otherwise fetches live companies from the registry."""
    from nordtrace.benchmark import BenchmarkHarness

    repo = _repo()
    harness = BenchmarkHarness(repo)
    try:
        if orgnr_file:
            orgs = _read_csv(orgnr_file)[:limit]
        else:
            click.echo("No orgnr file given — fetching live companies from Brreg search...")
            orgs = asyncio.run(harness.fetch_live_companies(limit))
        click.echo(f"Benchmarking {len(orgs)} companies...")
        report = asyncio.run(harness.evaluate_batch(orgs))
    finally:
        repo.close()
    Path(output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    _print_benchmark(report)
    click.echo(f"\nReport written to {output}")


def _print_benchmark(report: dict) -> None:
    b = report.get("budgets", {})
    click.echo(f"Completion: {report.get('completed')}/{report.get('batch_size')}")
    click.echo(f"Entity resolved: {report.get('entity_resolved')}/{report.get('batch_size')}")
    click.echo(f"Ambiguous: {report.get('ambiguous')} | Failed: {report.get('failed')}")
    click.echo(f"Verified facts: {report.get('total_facts')} | Evidence: {report.get('total_evidence')}")
    click.echo(f"Rejected sources: {report.get('total_rejected')}")
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
    correctness = report.get("correctness", {})
    click.echo(f"Correctness: {json.dumps(correctness)}")


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

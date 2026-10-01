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
from nordtrace.core.models import ResearchRun, utcnow
from nordtrace.core.orgnr import validate_orgnr
from nordtrace.core.repository import Repository
from nordtrace.engine.pipeline import ResearchPipeline
from nordtrace.engine.runner import BatchRunner


def _repo() -> Repository:
    return Repository(settings.database_path)


def _result_json(outcome, run_id: str, budget: BudgetManager, started_at: str) -> dict:
    from nordtrace.core.models import CompanyProfile, ResearchMetadata

    meta = ResearchMetadata(
        started_at=started_at,
        completed_at=utcnow().isoformat(),
        duration_sec=getattr(outcome, "duration_sec", None),
        request_count=budget.requests.total_used,
        request_budget=budget.requests.global_limit,
        estimated_cost_usd=round(budget.cost.total_used, 6),
        cost_budget_usd=budget.cost.limit,
        time_remaining_sec=round(budget.runtime.time_remaining(), 1),
        stages_executed=outcome.stages,
        llm_calls=budget.cost.calls,
    )
    profile = CompanyProfile(
        run_id=run_id,
        organisation_number=outcome.org_number,
        status=outcome.terminal_state,
        company=outcome.identity,
        facts=outcome.facts,
        changes=outcome.changes,
        summary=outcome.summary,
        unknowns=outcome.unknowns,
        sources=outcome.sources,
        rejected_sources=outcome.rejected,
        coverage=outcome.coverage,
        research_metadata=meta,
        last_researched_at=utcnow().isoformat(),
    )
    return json.loads(profile.model_dump_json())


@click.group()
@click.option("--debug", is_flag=True, default=False, help="Verbose logging")
@click.pass_context
def cli(ctx, debug: bool):
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)


@cli.command()
@click.argument("org_number")
@click.option("--output", type=str, default=None, help="Write result JSON to file")
@click.pass_context
def research(ctx, org_number: str, output: Optional[str]):
    """Research a single Norwegian company by organisation number."""
    started_at = utcnow().isoformat()
    check = validate_orgnr(org_number)
    if not check.valid:
        click.echo(f"Invalid organisation number: {check.reason}", err=True)
        sys.exit(2)
    repo = _repo()
    budget = BudgetManager(
        max_requests=settings.max_requests,
        max_runtime_sec=settings.max_runtime_sec,
        max_cost=settings.max_api_cost_usd,
        per_company_soft_sec=settings.per_company_soft_deadline_sec,
    )
    run = ResearchRun(started_at=started_at, companies=[check.value])
    repo.create_run(run)
    pipeline = ResearchPipeline(repo, budget)

    async def go():
        try:
            return await pipeline.research_company(check.value, run.run_id)
        finally:
            await pipeline.aclose()

    try:
        outcome = asyncio.run(go())
    finally:
        repo.close()
    run.completed_at = utcnow().isoformat()
    run.state = "completed"
    run.request_count = budget.requests.total_used
    run.estimated_cost_usd = round(budget.cost.total_used, 6)
    repo2 = _repo()
    repo2.mark_company_state(run.run_id, check.value, outcome.terminal_state)
    repo2.update_run(run)
    repo2.close()

    payload = _result_json(outcome, run.run_id, budget, started_at)
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if output:
        Path(output).write_text(text, encoding="utf-8")
        click.echo(f"Result written to {output}")
    click.echo(f"Company: {outcome.identity.legal_name if outcome.identity else '(not found)'}")
    click.echo(f"Status: {outcome.terminal_state}")
    click.echo(
        f"Verified facts: {len(outcome.facts)} | Evidence: {len(outcome.evidence)} | "
        f"Sources: {len(outcome.sources)} | Rejected: {len(outcome.rejected)}"
    )
    click.echo(
        f"Requests: {budget.requests.total_used}/{budget.requests.global_limit} | "
        f"Cost: ${budget.cost.total_used:.4f} | Time: {getattr(outcome, 'duration_sec', 0):.1f}s"
    )
    if outcome.summary:
        click.echo(f"\nSummary: {outcome.summary}")


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
    valid: list = []
    invalid: list = []
    for o in orgs:
        check = validate_orgnr(o)
        (valid if check.valid else invalid).append(o)
    click.echo(f"{len(orgs)} inputs: {len(valid)} valid, {len(invalid)} invalid (skipped)")
    if not valid:
        click.echo("Nothing to research.", err=True)
        sys.exit(2)
    repo = _repo()
    runner = BatchRunner(repo, concurrency=concurrency)
    try:
        run = asyncio.run(runner.run_batch(valid, resume_run_id=resume_run_id))
    finally:
        repo.close()
    counts: dict = {}
    for state in run.company_states.values():
        counts[state] = counts.get(state, 0) + 1
    click.echo(f"Run {run.run_id}: state={run.state}")
    for state, n in sorted(counts.items()):
        click.echo(f"  {state}: {n}")
    click.echo(
        f"Requests: {run.request_count}/{settings.max_requests} | "
        f"Cost: ${run.estimated_cost_usd:.4f} | "
        f"Time: {run.completed_at and 'done'}"
    )
    if output:
        payload = {
            "run_id": run.run_id,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "state": run.state,
            "company_states": run.company_states,
            "request_count": run.request_count,
            "estimated_cost_usd": run.estimated_cost_usd,
        }
        Path(output).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        click.echo(f"Run summary written to {output}")


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
        repo.close()
        return
    runner = BatchRunner(repo)
    try:
        run2 = asyncio.run(runner.run_batch(unfinished, resume_run_id=run_id))
    finally:
        repo.close()
    click.echo(f"Resumed: {len(run2.company_states)} companies now have terminal states")


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
        click.echo("  (FAIL rows may reflect data written before schema/slot fixes;"
                   " a fresh database passes — see VERIFICATION_REPORT.md)")
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

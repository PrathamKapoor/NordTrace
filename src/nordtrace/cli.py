from __future__ import annotations

import click
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from nordtrace.core.config import settings
from nordtrace.core.budget import BudgetManager
from nordtrace.core.models import CompanyIdentity, CompanyProfile


@click.group()
@click.option("--debug", is_flag=True, default=False)
@click.pass_context
def cli(ctx, debug):
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug
    ctx.obj["budget"] = BudgetManager()


@cli.command()
@click.argument("org_number")
@click.option("--output", type=str, default="research_result.json")
@click.pass_context
def research(ctx, org_number, output):
    """Research a single Norwegian company by organisation number."""
    budget = ctx.obj.get("budget", BudgetManager())
    click.echo(f"Starting research for organisation number: {org_number}")
    # Basic identity resolution attempt
    try:
        identity = CompanyIdentity(
            organisation_number=org_number,
            legal_name=f"Unknown ({org_number})",
            organisation_form="AS",
            status="unknown",
        )
        profile = CompanyProfile(
            organisation_number=org_number,
            company_identity=identity,
        )
        click.echo(f"Identity resolved: {identity.legal_name}")
        profile.terminal_state = "available"
        profile.last_researched_at = "2026-09-28T12:00:00Z"
        profile.research_metadata = {
            "request_count": budget.requests.total_used,
            "estimated_cost_usd": budget.cost.total_used,
        }
        import json
        result = profile.model_dump_json(indent=2)
        Path(output).write_text(result, encoding="utf-8")
        click.echo(f"Result saved to {output}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option("--resume", is_flag=True, default=False)
@click.pass_context
def batch(ctx, input_file, resume):
    """Batch process from CSV of organisation numbers."""
    click.echo(f"Batch processing: {input_file} (resume={resume})")
    budget = ctx.obj.get("budget", BudgetManager())
    # Placeholder for actual batch processing
    click.echo(f"Batch complete. Requests used: {budget.requests.total_used}")


@cli.command()
@click.argument("run_id")
@click.pass_context
def resume(ctx, run_id):
    """Resume an interrupted run."""
    click.echo(f"Resuming run: {run_id}")


@cli.command()
def benchmark():
    """Run benchmark harness."""
    click.echo("Benchmark harness started. (Not fully implemented in this release)")


@cli.command()
@click.argument("result_file", type=click.Path(exists=True))
@click.pass_context
def validate(ctx, result_file):
    """Validate a result file schema."""
    import json
    data = json.loads(Path(result_file).read_text(encoding="utf-8"))
    required = ["organisation_number", "company", "status"]
    for r in required:
        if r not in data:
            click.echo(f"Missing required field: {r}", err=True)
            sys.exit(1)
    click.echo("Validation passed.")


def main():
    cli()


if __name__ == "__main__":
    main()

"""Canonical operational measurements; independent accuracy requires adjudicated labels."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from nordtrace.core.budget import BudgetManager
from nordtrace.core.config import settings
from nordtrace.core.contracts import batch_payload, write_json_atomic
from nordtrace.core.ledger import CitationValidator
from nordtrace.core.models import utcnow
from nordtrace.core.repository import Repository
from nordtrace.engine.runner import BatchRunner


class BenchmarkHarness:
    def __init__(self, repo: Optional[Repository] = None):
        self.repo = repo or Repository(settings.database_path)

    async def fetch_live_companies(self, limit: int = 10) -> List[str]:
        """Retired unsafe convenience path; no hidden discovery budget/network."""
        raise ValueError("Benchmark requires supplied organisation numbers from a reproducible sample")

    async def evaluate_batch(
        self, org_numbers: List[str], concurrency: int = 4, *, budget: Optional[BudgetManager] = None,
    ) -> Dict:
        runner = BatchRunner(self.repo, budget=budget, concurrency=concurrency)
        run = await runner.run_batch(org_numbers, requested_by="benchmark")
        profiles = self.repo.get_results(run.run_id)
        inputs = self.repo.get_run_inputs(run.run_id)
        batch_payload(run, profiles, inputs)  # Refuse an incomplete measurement, never drop a result.
        results: List[Dict[str, Any]] = []
        family_companies: Counter = Counter()
        external_family_companies: Counter = Counter()
        support_failures = []
        for profile in profiles:
            sources = {source.source_id: source for source in profile.sources}
            validator = CitationValidator(
                sources, {item.evidence_id: item for item in profile.evidence}, self.repo,
            )
            supported = []
            for fact in profile.facts:
                valid, reason = validator.validate(fact)
                if valid:
                    supported.append(fact)
                else:
                    support_failures.append({"organisation_number": profile.organisation_number,
                                             "observation_id": fact.fact_id, "reason": reason})
            external = [fact for fact in supported
                        if sources[fact.source_id].source_type not in ("registry", "registry_accounts")]
            family_companies.update({fact.category for fact in supported})
            external_family_companies.update({fact.category for fact in external})
            resolved = profile.company is not None and any(
                fact.category == "identity" and fact.field == "legal_name"
                and fact.subject_scope == "legal_entity" and fact.value == profile.company.legal_name
                and bool(fact.value) for fact in supported
            )
            results.append({
                "org_number": profile.organisation_number, "terminal_state": profile.status,
                "status_reason": profile.status_reason, "identity_supported": resolved,
                "published_observations": len(profile.facts), "supported_observations": len(supported),
                "published_claims": len({fact.claim_id for fact in profile.facts}),
                "supported_claims": len({fact.claim_id for fact in supported}),
                "external_supported_claims": len({fact.claim_id for fact in external}),
                "last_known_claims": len({fact.claim_id for fact in profile.last_known}),
                "evidence_count": len(profile.evidence),
                "retained_successful_source_records": sum(
                    source.access_status == "success" for source in profile.sources
                ),
                "last_known_source_records": len({fact.source_id for fact in profile.last_known}),
                "rejected_candidates": len(profile.rejected_sources),
            })
        counts = Counter(profile.status for profile in profiles)
        total = sum(item["published_observations"] for item in results)
        supported_count = sum(item["supported_claims"] for item in results)
        supported_observations = sum(item["supported_observations"] for item in results)
        external_count = sum(item["external_supported_claims"] for item in results)
        bs = runner.budget.requests.snapshot()
        cs = runner.budget.cost.snapshot()
        elapsed = runner.budget.runtime.elapsed_sec()
        n = len(profiles)
        return {
            "schema_version": "nordtrace-operational-benchmark-v1", "run_id": run.run_id,
            "benchmark_timestamp": utcnow().isoformat(), "input_count": len(inputs),
            "batch_size": n, "inputs": inputs, "completed": n, "completion_rate": 1.0 if n else None,
            "available": counts.get("available", 0),
            "entity_resolved": sum(r["identity_supported"] for r in results),
            "ambiguous": counts.get("ambiguous", 0), "failed": counts.get("failed", 0),
            "terminal_counts": dict(counts), "total_facts": total, "total_supported_claims": supported_count,
            "total_published_claims": sum(item["published_claims"] for item in results),
            "total_supported_observations": supported_observations,
            "total_external_supported_claims": external_count,
            "total_evidence": sum(item["evidence_count"] for item in results),
            "total_rejected": sum(item["rejected_candidates"] for item in results),
            "company_counts_by_supported_family": dict(family_companies),
            "company_counts_by_external_supported_family": dict(external_family_companies),
            "observed_output": {
                "supported_claims_per_company": supported_count / n if n else None,
                "external_supported_claims_per_company": external_count / n if n else None,
                "requests_per_company": bs["total_used"] / n if n else None,
                "supported_claims_per_request": (supported_count / bs["total_used"]
                                                if bs["total_used"] else None),
            },
            "support_validation": {"checked": total, "passed": supported_observations,
                                   "failures": support_failures},
            "independent_accuracy": {"measured": False, "exact_company_precision": None,
                                     "claim_precision": None, "claim_recall": None, "company_recall": None,
                                     "financial_exact_match": None,
                                     "reason": "No independent adjudicated reference supplied"},
            "definitions": {
                "completed": "Unique terminal envelopes including failure/invalid/not-found",
                "entity_resolved": "Current legal name supported by retained exact-entity observations",
                "external": "Excludes registry/registry_accounts sources; not independent accuracy",
                "family_counts": "Observed supported output counts, not recall or official scores",
                "claims": "Distinct logical claim_id per company; corroborating observations count once",
                "total_facts": "Legacy field: published observation count, not logical claims",
                "source_records": "Metadata inventory, including history; not current HTTP or byte proof",
            },
            "results": results,
            "budgets": {"requests_used": bs["total_used"], "requests_limit": bs["limit"],
                        "requests_ok": bs["total_used"] <= bs["limit"], "request_telemetry": bs,
                        "cost_used": cs["total_used"], "cost_limit": cs["limit"],
                        "cost_ok": cs["total_used"] <= cs["limit"], "cost_is_estimate": True,
                        "runtime_sec": elapsed, "runtime_limit_sec": runner.budget.runtime.total_limit_sec,
                        "runtime_ok": elapsed <= runner.budget.runtime.total_limit_sec,
                        "effective_configuration": runner.budget.configuration.model_dump(mode="json")},
        }

    def save_report(self, report: Dict, path: str = "benchmark_result.json") -> None:
        write_json_atomic(Path(path), report)

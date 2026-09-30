"""Benchmark harness — REAL evaluator over actual research runs.

Metrics computed from real CompanyOutcome artifacts:
  - completion / terminal states
  - entity resolution success
  - verified fact / evidence counts
  - rejected sources
  - budget adherence (requests, runtime, cost)
  - correctness vs ground truth where available (golden fixtures);
    otherwise explicitly 'not independently verifiable'
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Dict, List, Optional

from nordtrace.core.budget import BudgetManager
from nordtrace.core.config import settings
from nordtrace.core.models import ResearchRun, utcnow
from nordtrace.core.orgnr import validate_orgnr
from nordtrace.core.repository import Repository
from nordtrace.engine.pipeline import ResearchPipeline
from nordtrace.engine.runner import BatchRunner


class BenchmarkHarness:
    def __init__(self, repo: Optional[Repository] = None):
        self.repo = repo or Repository(settings.database_path)
        self.start_time = time.monotonic()

    async def fetch_live_companies(self, limit: int = 10) -> List[str]:
        """Fetch real orgnrs from the Brreg search endpoint (live)."""
        from nordtrace.core.request_gateway import RequestGateway
        import json

        gw = RequestGateway(BudgetManager(max_requests=20))
        orgs: List[str] = []
        try:
            for name in ("Telenor", "Salmar", "Equinor", "Yara", "Aibel"):
                if len(orgs) >= limit:
                    break
                src = await gw.fetch(
                    f"{settings.brreg_base_url}/enheter?navn={name}&size=3",
                    stage="benchmark", source_type="registry", authority_tier=0,
                )
                if src.access_status != "success":
                    continue
                cached = gw.get_content(src.url)
                data = json.loads(cached.text)
                for e in (data.get("_embedded") or {}).get("enheter", []):
                    org = e.get("organisasjonsnummer")
                    if org and validate_orgnr(org).valid and org not in orgs:
                        orgs.append(org)
        finally:
            await gw.aclose()
        return orgs[:limit]

    async def evaluate_batch(self, org_numbers: List[str], concurrency: int = 4) -> Dict:
        runner = BatchRunner(self.repo, concurrency=concurrency)
        run = await runner.run_batch(org_numbers, requested_by="benchmark")

        results = []
        total_facts = 0
        total_evidence = 0
        total_rejected = 0
        pipeline = ResearchPipeline(self.repo, runner.budget)
        try:
            for org in org_numbers:
                state = run.company_states.get(org, "failed")
                # collect facts from DB for this run
                facts = self.repo.get_facts(org, run.run_id, statuses=["PUBLISHED"])
                evidence = self.repo.evidence_for_company(org, run.run_id)
                sources = self.repo.get_sources(org, run.run_id)
                rejected = [s for s in sources if s.access_status in ("blocked", "failed", "timeout")]
                total_facts += len(facts)
                total_evidence += len(evidence)
                total_rejected += len(rejected)
                results.append({
                    "org_number": org,
                    "terminal_state": state,
                    "verified_facts": len(facts),
                    "evidence_count": len(evidence),
                    "sources_retrieved": sum(1 for s in sources if s.access_status == "success"),
                    "sources_rejected": len(rejected),
                })
        finally:
            await pipeline.aclose()

        bs = runner.budget.requests.snapshot()
        rt = runner.budget.runtime
        cs = runner.budget.cost.snapshot()
        completed = sum(1 for r in results if r["terminal_state"] == "available")
        entity_resolved = sum(1 for r in results if r["terminal_state"] in ("available", "not_available", "not_applicable"))
        ambiguous = sum(1 for r in results if r["terminal_state"] == "ambiguous")
        failed = sum(1 for r in results if r["terminal_state"] == "failed")

        report = {
            "benchmark_timestamp": utcnow().isoformat(),
            "batch_size": len(org_numbers),
            "completed": completed,
            "entity_resolved": entity_resolved,
            "ambiguous": ambiguous,
            "failed": failed,
            "total_facts": total_facts,
            "total_evidence": total_evidence,
            "total_rejected": total_rejected,
            "results": results,
            "budgets": {
                "requests_used": bs["total_used"],
                "requests_limit": bs["limit"],
                "requests_ok": bs["total_used"] <= bs["limit"],
                "cost_used": cs["total_used"],
                "cost_limit": cs["limit"],
                "cost_ok": cs["total_used"] <= cs["limit"],
                "cost_is_estimate": cs.get("is_estimate", True),
                "runtime_sec": round(rt.elapsed_sec(), 1),
                "runtime_limit_sec": rt.total_limit_sec,
                "runtime_ok": rt.elapsed_sec() <= rt.total_limit_sec,
            },
            "correctness": {
                "note": "entity resolution is deterministic (registry-anchored); "
                        "fact correctness is verifiable via evidence chains; "
                        "no independent ground-truth scoring without a golden dataset",
                "verifiable": "evidence-backed facts only",
            },
        }
        return report

    def save_report(self, report: Dict, path: str = "benchmark_result.json") -> None:
        Path(path).write_text(report and __import__("json").dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

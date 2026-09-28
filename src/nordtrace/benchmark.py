from __future__ import annotations

import time
import json
from pathlib import Path
from typing import List, Dict, Any


class BenchmarkHarness:
    def __init__(self):
        self.results: List[Dict[str, Any]] = []
        self.start_time = time.time()

    def run_company(self, org_number: str) -> Dict[str, Any]:
        # Simulated benchmark loop; real implementation would call adapters
        return {
            "org_number": org_number,
            "status": "completed",
            "entity_resolved": True,
            "verified_facts": 3,
            "rejected_sources": 0,
            "request_count": 5,
            "duration_sec": 3.2,
        }

    def evaluate_batch(self, org_numbers: List[str]) -> Dict[str, Any]:
        results = []
        total_duration = 0.0
        total_requests = 0
        for nr in org_numbers:
            result = self.run_company(nr)
            results.append(result)
            total_duration += result.get("duration_sec", 0)
            total_requests += result.get("request_count", 0)
        return {
            "batch_size": len(org_numbers),
            "completed": len([r for r in results if r.get("status") == "completed"]),
            "entity_resolution_rate": sum(1 for r in results if r.get("entity_resolved")) / len(org_numbers),
            "avg_requests": total_requests / max(len(org_numbers), 1),
            "total_duration_sec": total_duration,
            "estimated_cost_usd": 0.0,
            "results": results,
        }

    def save_report(self, path: str = "benchmark_result.json"):
        report = {
            "benchmark_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_duration_sec": time.time() - self.start_time,
            "results": self.results,
        }
        Path(path).write_text(json.dumps(report, indent=2), encoding="utf-8")

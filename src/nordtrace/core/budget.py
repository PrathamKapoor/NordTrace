from __future__ import annotations

import time
from typing import Dict, Optional, List
from dataclasses import dataclass, field


@dataclass
class RequestBudget:
    global_limit: int = 2000
    total_used: int = 0
    by_company: Dict[str, int] = field(default_factory=dict)
    by_domain: Dict[str, int] = field(default_factory=dict)
    by_provider: Dict[str, int] = field(default_factory=dict)
    failed: int = 0
    successful: int = 0
    retries: int = 0

    def can_request(self, company: Optional[str] = None, cost_estimate: int = 1) -> bool:
        return (self.total_used + cost_estimate) < self.global_limit

    def record(self, company: Optional[str] = None, domain: Optional[str] = None,
               provider: Optional[str] = None, success: bool = True, retry: bool = False):
        self.total_used += 1
        if retry:
            self.retries += 1
        if company:
            self.by_company[company] = self.by_company.get(company, 0) + 1
        if domain:
            self.by_domain[domain] = self.by_domain.get(domain, 0) + 1
        if provider:
            self.by_provider[provider] = self.by_provider.get(provider, 0) + 1
        if success:
            self.successful += 1
        else:
            self.failed += 1

    def remaining(self) -> int:
        return max(0, self.global_limit - self.total_used)


@dataclass
class RuntimeBudget:
    start_time: float = field(default_factory=time.time)
    global_limit_sec: int = 45 * 60
    company_deadline_sec: int = 5 * 60  # Max per company

    def time_remaining(self) -> float:
        return max(0.0, self.global_limit_sec - (time.time() - self.start_time))

    def deadline_reached(self, company: Optional[str] = None) -> bool:
        if company is None:
            return self.time_remaining() <= 0
        # Per-company tracking could be added here
        return self.time_remaining() <= 120  # 2 min warning globally

    def should_stop_expensive(self) -> bool:
        return self.time_remaining() < 300  # 5 minutes left


@dataclass
class CostTracker:
    global_limit: float = 10.0
    total_used: float = 0.0
    by_provider: Dict[str, float] = field(default_factory=dict)
    by_model: Dict[str, float] = field(default_factory=dict)
    request_counts: Dict[str, int] = field(default_factory=dict)

    def add(self, provider: str, model: str, input_tokens: int, output_tokens: int, cost_estimate: float):
        self.total_used += cost_estimate
        self.by_provider[provider] = self.by_provider.get(provider, 0.0) + cost_estimate
        self.by_model[model] = self.by_model.get(model, 0.0) + cost_estimate
        self.request_counts[provider] = self.request_counts.get(provider, 0) + 1

    def remaining(self) -> float:
        return max(0.0, self.global_limit - self.total_used)


class BudgetManager:
    def __init__(self):
        self.requests = RequestBudget()
        self.runtime = RuntimeBudget()
        self.cost = CostTracker()

    def can_start_expensive(self) -> bool:
        if not self.requests.can_request():
            return False
        if self.runtime.should_stop_expensive():
            return False
        if self.cost.remaining() < 0.5:
            return False
        return True


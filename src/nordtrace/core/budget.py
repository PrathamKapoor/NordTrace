"""Budget manager: requests, runtime, cost.

Hard limits:
- 2,000 outbound requests per run
- 45 minutes per run (global deadline; per-company soft deadline)
- $10 declared external API cost

All outbound HTTP goes through RequestGateway, which consults these budgets.
No component may bypass the gateway.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional


class BudgetExceededError(RuntimeError):
    """Raised when the global request limit is exhausted."""


class DeadlineReachedError(RuntimeError):
    """Raised when the global runtime deadline is hit."""


@dataclass
class RequestBudget:
    """Thread-safe request counter. Enforces a hard global cap."""
    global_limit: int = 2000
    total_used: int = 0
    by_domain: Dict[str, int] = field(default_factory=dict)
    by_stage: Dict[str, int] = field(default_factory=dict)
    by_company: Dict[str, int] = field(default_factory=dict)
    failed: int = 0
    successful: int = 0
    retries: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def try_acquire(self, n: int = 1) -> bool:
        """Atomically reserve n requests. Returns False if it would exceed the limit."""
        with self._lock:
            if self.total_used + n > self.global_limit:
                return False
            self.total_used += n
            return True

    def remaining(self) -> int:
        with self._lock:
            return max(0, self.global_limit - self.total_used)

    def record_outcome(
        self,
        success: bool,
        retry: bool = False,
        domain: Optional[str] = None,
        stage: Optional[str] = None,
        company: Optional[str] = None,
    ) -> None:
        with self._lock:
            if success:
                self.successful += 1
            else:
                self.failed += 1
            if retry:
                self.retries += 1
            if domain:
                self.by_domain[domain] = self.by_domain.get(domain, 0) + 1
            if stage:
                self.by_stage[stage] = self.by_stage.get(stage, 0) + 1
            if company:
                self.by_company[company] = self.by_company.get(company, 0) + 1

    def snapshot(self) -> Dict[str, object]:
        with self._lock:
            return {
                "total_used": self.total_used,
                "limit": self.global_limit,
                "remaining": self.global_limit - self.total_used,
                "successful": self.successful,
                "failed": self.failed,
                "retries": self.retries,
                "by_domain": dict(self.by_domain),
                "by_stage": dict(self.by_stage),
            }


@dataclass
class RuntimeBudget:
    """Global run deadline. The global deadline always wins over per-company limits."""
    total_limit_sec: float = 45 * 60
    per_company_soft_sec: float = 90.0
    started_at: float = field(default_factory=time.monotonic)

    def elapsed_sec(self) -> float:
        return time.monotonic() - self.started_at

    def time_remaining(self) -> float:
        return max(0.0, self.total_limit_sec - self.elapsed_sec())

    def deadline_reached(self) -> bool:
        return self.time_remaining() <= 0

    def should_start_expensive_operation(self, est_sec: float = 30.0) -> bool:
        """Only start work we plausibly have time to finish."""
        return self.time_remaining() > est_sec

    def company_time_exceeded(self, company_started_at: float) -> bool:
        """Per-company soft deadline; used to move on to the next company."""
        return (time.monotonic() - company_started_at) > self.per_company_soft_sec

    def phase(self) -> str:
        """Priority guidance as the deadline approaches."""
        remaining = self.time_remaining()
        if remaining > 20 * 60:
            return "full_research"
        if remaining > 10 * 60:
            return "prioritize_high_value"
        if remaining > 2 * 60:
            return "finish_incomplete"
        return "serialize_results"


@dataclass
class CostBudget:
    """External API cost tracking (LLM etc.). Prices are estimates, labelled as such."""
    limit: float = 10.0
    total_used: float = 0.0
    by_model: Dict[str, float] = field(default_factory=dict)
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def estimate(self, input_tokens: int, output_tokens: int, price_in_per_m: float, price_out_per_m: float) -> float:
        return (input_tokens / 1_000_000) * price_in_per_m + (output_tokens / 1_000_000) * price_out_per_m

    def try_reserve(self, est_cost: float) -> bool:
        with self._lock:
            if self.total_used + est_cost > self.limit:
                return False
            return True  # reserved on record_add; conservative double-check happens there

    def record(self, model: str, input_tokens: int, output_tokens: int, cost: float) -> None:
        with self._lock:
            self.total_used += cost
            self.by_model[model] = self.by_model.get(model, 0.0) + cost
            self.calls += 1
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens

    def remaining(self) -> float:
        with self._lock:
            return max(0.0, self.limit - self.total_used)

    def can_afford(self, est_cost: float) -> bool:
        with self._lock:
            return (self.total_used + est_cost) <= self.limit

    def snapshot(self) -> Dict[str, object]:
        with self._lock:
            return {
                "total_used": round(self.total_used, 6),
                "limit": self.limit,
                "remaining": round(self.limit - self.total_used, 6),
                "calls": self.calls,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "by_model": dict(self.by_model),
                "is_estimate": True,
            }


class BudgetManager:
    """Facade bundling the three budgets for a single run."""

    def __init__(self, max_requests: int = 2000, max_runtime_sec: float = 45 * 60, max_cost: float = 10.0,
                 per_company_soft_sec: float = 90.0):
        self.requests = RequestBudget(global_limit=max_requests)
        self.runtime = RuntimeBudget(total_limit_sec=max_runtime_sec, per_company_soft_sec=per_company_soft_sec)
        self.cost = CostBudget(limit=max_cost)

    # -- gates used by the pipeline -----------------------------------------
    def can_make_request(self) -> bool:
        return self.requests.remaining() > 0 and not self.runtime.deadline_reached()

    def check(self) -> None:
        """Raise if hard limits hit; pipeline catches and finalizes gracefully."""
        if self.requests.remaining() <= 0:
            raise BudgetExceededError("request budget exhausted")
        if self.runtime.deadline_reached():
            raise DeadlineReachedError("runtime deadline reached")

    def snapshot(self) -> Dict[str, object]:
        return {
            "requests": self.requests.snapshot(),
            "runtime": {
                "elapsed_sec": round(self.runtime.elapsed_sec(), 1),
                "limit_sec": self.runtime.total_limit_sec,
                "remaining_sec": round(self.runtime.time_remaining(), 1),
                "phase": self.runtime.phase(),
            },
            "cost": self.cost.snapshot(),
        }

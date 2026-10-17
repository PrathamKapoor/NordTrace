"""Configured run allowances, with durable request reservations and resume.

The numeric constructor defaults are local development settings, not confirmed
organizer budgets. CLI/API/batch freeze their actual configuration per run.
Production acquisition uses RequestGateway. The dormant model helper's cost
reservations/transport remain unfinished; research does not call that helper.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional

from nordtrace.core.models import RunBudgetState, RunConfiguration

if TYPE_CHECKING:
    from nordtrace.core.repository import Repository


class BudgetExceededError(RuntimeError):
    """Raised when the global request limit is exhausted."""


class DeadlineReachedError(RuntimeError):
    """Raised when the global runtime deadline is hit."""


class RunBudgetUnavailable(ValueError):
    """A run's original allowance cannot be recovered without inventing limits."""


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
    unstarted: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def try_acquire(self, n: int = 1) -> bool:
        """Atomically reserve n requests. Returns False if it would exceed the limit."""
        if type(n) is not int or n <= 0:
            raise ValueError("request reservation must be a positive integer")
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
        started: bool = True,
    ) -> None:
        with self._lock:
            if not started:
                self.unstarted += 1
                return
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

    def snapshot(self) -> Dict[str, Any]:
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
                "transport_operations": self.successful + self.failed,
                "unstarted_reservations": self.unstarted,
                "unresolved_reservations": self.total_used - self.successful - self.failed - self.unstarted,
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

    def estimate(
        self, input_tokens: int, output_tokens: int, price_in_per_m: float, price_out_per_m: float
    ) -> float:
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

    def snapshot(self) -> Dict[str, Any]:
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


def request_telemetry_snapshot(telemetry: Dict[str, Any], used: int, limit: int) -> Dict[str, Any]:
    """Recompute derived counters from one durable reservation/outcome snapshot."""
    return telemetry | {
        "total_used": used, "limit": limit, "remaining": limit - used,
        "transport_operations": telemetry.get("successful", 0) + telemetry.get("failed", 0),
        "unresolved_reservations": used - telemetry.get("successful", 0)
        - telemetry.get("failed", 0) - telemetry.get("unstarted_reservations", 0),
    }


class PersistentRequestBudget:
    """Same request gate, with cross-process durable reservations before transport."""

    def __init__(self, repo: Repository, run_id: str, runtime: RuntimeBudget, limit: int):
        self.repo, self.run_id, self.runtime = repo, run_id, runtime
        self.global_limit = limit

    @property
    def total_used(self) -> int:
        return self.repo.get_run_budget(self.run_id)[1]

    def remaining(self) -> int:
        return max(0, self.global_limit - self.total_used)

    def try_acquire(self, n: int = 1) -> bool:
        if type(n) is not int or n <= 0:
            raise ValueError("request reservation must be a positive integer")
        acquired = self.repo.reserve_run_requests(self.run_id, n, self.runtime.elapsed_sec())
        if not acquired:
            state, _, _ = self.repo.get_run_budget(self.run_id)
            if (state.elapsed_floor_sec >= state.configuration.max_runtime_sec
                    or time.time() >= state.deadline_unix):
                self.runtime.started_at = min(
                    self.runtime.started_at, time.monotonic() - self.runtime.total_limit_sec,
                )
        return acquired

    def record_outcome(
        self, success: bool, retry: bool = False, domain: Optional[str] = None,
        stage: Optional[str] = None, company: Optional[str] = None,
        started: bool = True,
    ) -> None:
        self.repo.record_run_transport(
            self.run_id, success, retry, started=started, domain=domain, stage=stage, company=company,
        )

    def snapshot(self) -> Dict[str, Any]:
        state, used, _ = self.repo.get_run_budget(self.run_id)
        return request_telemetry_snapshot(state.telemetry, used, self.global_limit)


class BudgetManager:
    """Facade bundling the three budgets for a single run."""

    def __init__(
        self,
        max_requests: int = 2000,
        max_runtime_sec: float = 45 * 60,
        max_cost: float = 10.0,
        per_company_soft_sec: float = 90.0,
        finalization_reserve_sec: float = 0.0,
    ):
        self.configuration = RunConfiguration(
            max_requests=max_requests, max_runtime_sec=max_runtime_sec, max_cost_usd=max_cost,
            per_company_sec=per_company_soft_sec, finalization_reserve_sec=finalization_reserve_sec,
        )
        self.requests: RequestBudget | PersistentRequestBudget = RequestBudget(global_limit=max_requests)
        self.runtime = RuntimeBudget(
            total_limit_sec=max_runtime_sec, per_company_soft_sec=per_company_soft_sec
        )
        self.cost = CostBudget(limit=max_cost)
        self._repository: Optional[Repository] = None
        self._run_id: Optional[str] = None

    def bind_run(self, repo: Repository, run_id: str, initialize: bool = False) -> None:
        if self._run_id is not None and self._run_id != run_id:
            raise RunBudgetUnavailable("a budget manager cannot be reused for a different run")
        try:
            if initialize:
                now = time.time()
                state = RunBudgetState(
                    configuration=self.configuration, deadline_unix=now + self.runtime.time_remaining(),
                    elapsed_floor_sec=self.runtime.elapsed_sec(), last_seen_unix=now,
                    telemetry=self.requests.snapshot(),
                )
                repo.initialize_run_budget(run_id, state, self.requests.total_used, self.cost.total_used)
            saved, _, spent = repo.get_run_budget(run_id)
            now = time.time()
            if now < saved.last_seen_unix - 0.01:
                raise ValueError("wall clock moved backwards; deadline cannot be safely restored")
            self.configuration = saved.configuration
            remaining = max(0, min(
                saved.deadline_unix - now,
                self.configuration.max_runtime_sec - saved.elapsed_floor_sec,
            ))
            self.runtime.total_limit_sec = self.configuration.max_runtime_sec
            self.runtime.per_company_soft_sec = self.configuration.per_company_sec
            self.runtime.started_at = time.monotonic() - (self.runtime.total_limit_sec - remaining)
            self.cost.limit = self.configuration.max_cost_usd
            self.cost.total_used = max(self.cost.total_used, spent)
            self.requests = PersistentRequestBudget(
                repo, run_id, self.runtime, self.configuration.max_requests,
            )
            self._repository, self._run_id = repo, run_id
        except ValueError as error:
            raise RunBudgetUnavailable(str(error)) from error

    def checkpoint(self) -> None:
        if self._repository is not None and self._run_id is not None:
            self._repository.checkpoint_run_budget(
                self._run_id, self.runtime.elapsed_sec(), self.cost.total_used,
            )

    # -- gates used by the pipeline -----------------------------------------
    def work_time_remaining(self) -> float:
        """Acquisition stops before the optional result-finalization reserve."""
        return max(0.0, self.runtime.time_remaining() - self.configuration.finalization_reserve_sec)

    def can_make_request(self) -> bool:
        return self.requests.remaining() > 0 and self.work_time_remaining() > 0

    def check(self) -> None:
        """Raise if hard limits hit; pipeline catches and finalizes gracefully."""
        if self.requests.remaining() <= 0:
            raise BudgetExceededError("request budget exhausted")
        if self.work_time_remaining() <= 0:
            raise DeadlineReachedError("runtime deadline reached")

    def snapshot(self) -> Dict[str, Any]:
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

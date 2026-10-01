"""Rate limiter + circuit breaker: deterministic tests (no network)."""

import asyncio
import time

import pytest

from nordtrace.core.rate_limiter import (
    DomainState,
    RateLimited,
    RateLimiter,
    SourcePolicy,
)


def test_429_respects_retry_after():
    """429 → Retry-After handled by gateway (integration); limiter records it."""
    state = DomainState(policy=SourcePolicy(breaker_threshold=5))
    state.record_failure(rate_limited=True)
    assert state.rate_limited_events == 1
    assert not state.circuit_open  # below threshold


def test_repeated_429_opens_circuit():
    state = DomainState(policy=SourcePolicy(breaker_threshold=3, breaker_cooldown=60))
    for _ in range(3):
        state.record_failure(rate_limited=True)
    assert state.circuit_open


def test_circuit_blocks_requests():
    state = DomainState(policy=SourcePolicy(breaker_threshold=1, breaker_cooldown=60))
    state.record_failure(rate_limited=True)
    rl = RateLimiter()
    rl._domains["test.no"] = state
    with pytest.raises(RateLimited):
        asyncio.run(rl.acquire("test.no"))


def test_circuit_recovery_after_cooldown():
    state = DomainState(policy=SourcePolicy(breaker_threshold=1, breaker_cooldown=0.05))
    state.record_failure(rate_limited=True)
    assert state.circuit_open
    time.sleep(0.08)  # cooldown elapses → half-open
    rl = RateLimiter()
    rl._domains["test.no"] = state
    token = asyncio.run(rl.acquire("test.no"))  # controlled retry allowed
    token.record_success()
    assert not state.circuit_open  # circuit CLOSED again


def test_success_closes_circuit():
    state = DomainState(policy=SourcePolicy(breaker_threshold=2))
    state.record_failure(rate_limited=True)
    state.record_failure(rate_limited=True)
    assert state.circuit_open
    state.record_success()
    assert not state.circuit_open
    assert state.consecutive_failures == 0


def test_min_interval_spacing():
    async def go():
        rl = RateLimiter(default_policy=SourcePolicy(min_interval=0.1))
        t0 = time.monotonic()
        await rl.acquire("x.no")
        await rl.acquire("x.no")
        elapsed = time.monotonic() - t0
        return elapsed

    elapsed = asyncio.run(go())
    assert elapsed >= 0.1  # min interval enforced between consecutive requests


def test_concurrency_limit_per_domain():
    async def go():
        rl = RateLimiter(default_policy=SourcePolicy(max_concurrent=1, min_interval=0.0))
        inflight = {"n": 0, "max": 0}

        async def one():
            token = await rl.acquire("x.no")
            inflight["n"] += 1
            inflight["max"] = max(inflight["max"], inflight["n"])
            await asyncio.sleep(0.02)
            inflight["n"] -= 1
            token.record_success()

        await asyncio.gather(*[one() for _ in range(5)])
        return inflight["max"]

    result = asyncio.run(go())
    assert result == 1  # never more than 1 in flight


def test_domains_are_independent():
    async def go():
        rl = RateLimiter(default_policy=SourcePolicy(min_interval=0.2))
        t0 = time.monotonic()
        await rl.acquire("a.no")
        await rl.acquire("b.no")  # different domain → no min-interval wait
        return time.monotonic() - t0

    assert asyncio.run(go()) < 0.15


def test_nav_preset_conservative():
    rl = RateLimiter()
    state = rl.state_for("arbeidsplassen.nav.no")
    assert state.policy.max_concurrent == 1
    assert state.policy.min_interval >= 0.5


def test_brreg_preset():
    rl = RateLimiter()
    state = rl.state_for("data.brreg.no")
    assert state.policy.max_concurrent <= 2


def test_budget_counts_retries():
    """Retries count toward the global request budget (no bypass)."""
    from nordtrace.core.budget import RequestBudget

    b = RequestBudget(global_limit=10)
    b.try_acquire(1)
    b.record_outcome(False, retry=True)
    b.try_acquire(1)  # retry consumes another slot
    b.record_outcome(True, retry=False)
    assert b.total_used == 2
    assert b.retries == 1
    assert b.remaining() == 8


def test_snapshot_reports_health():
    rl = RateLimiter()
    state = rl.state_for("x.no")
    state.record_failure(rate_limited=True)
    snap = rl.snapshot()
    assert snap["x.no"]["rate_limited_events"] == 1


# --- adaptive degradation: pipeline survives source-level failure ---
def test_pipeline_survives_rate_limited_source(tmp_path, monkeypatch):
    """A rate-limited NAV must not fail the company — other sources complete."""
    from nordtrace.adapters import nav_jobs
    from nordtrace.core.budget import BudgetManager
    from nordtrace.core.models import ResearchRun, utcnow
    from nordtrace.core.repository import Repository
    from nordtrace.engine.pipeline import ResearchPipeline

    async def go():
        repo = Repository(tmp_path / "rl.db")
        bm = BudgetManager(max_requests=40)
        pipe = ResearchPipeline(repo, bm)
        run = ResearchRun(started_at=utcnow().isoformat(), companies=["982463718"])
        repo.create_run(run)

        # simulate NAV rate-limited: fetch_jobs raises RateLimited internally via gateway
        async def rate_limited_fetch(self, identity, run_id, limit=8):
            from nordtrace.core.models import SourceRecord, SourceType

            src = SourceRecord(
                url="https://arbeidsplassen.nav.no/stillinger/api/search?q=x",
                domain="arbeidsplassen.nav.no",
                source_type=SourceType.JOB_BOARD.value,
                authority_tier=2,
                access_status="rate_limited",
                error_detail="circuit OPEN",
                org_number=identity.organisation_number,
            )
            return [], [], src, [{"reason": "rate_limited"}]

        monkeypatch.setattr(nav_jobs.NavJobsAdapter, "fetch_jobs", rate_limited_fetch)
        outcome = await pipe.research_company("982463718", run.run_id)
        await pipe.aclose()
        repo.close()
        return outcome

    outcome = asyncio.run(go())
    # company still gets a terminal state; jobs degraded, not fatal
    assert outcome.terminal_state in ("available", "not_available")
    assert any(r.get("reason") == "rate_limited" for r in outcome.rejected)


def test_exponential_cooldown_doubles():
    """Repeated OPENs double the cooldown (capped at 4x) — protects against
    IP-level blocks without wasting budget on half-open retries, while still
    recovering within a single 100-company run."""
    state = DomainState(policy=SourcePolicy(breaker_threshold=2, breaker_cooldown=10))
    state.record_failure(rate_limited=True)
    state.record_failure(rate_limited=True)
    assert state.circuit_open and state._cooldown_mult == 1
    state.record_failure(rate_limited=True)
    assert state._cooldown_mult == 2
    state.record_failure(rate_limited=True)
    assert state._cooldown_mult == 4
    for _ in range(3):
        state.record_failure(rate_limited=True)
    assert state._cooldown_mult == 4  # capped (recovers within a run)


def test_exponential_cooldown_blocks_longer():
    state = DomainState(policy=SourcePolicy(breaker_threshold=1, breaker_cooldown=1))
    state.record_failure(rate_limited=True)
    state.record_failure(rate_limited=True)  # second OPEN → 2x cooldown
    assert state.circuit_open
    time.sleep(1.1)
    rl = RateLimiter()
    rl._domains["x.no"] = state
    # cooldown is now 2s; 1.1s elapsed → still blocked
    with pytest.raises(RateLimited):
        asyncio.run(rl.acquire("x.no"))

import asyncio

import pytest

from nordtrace.core.budget import BudgetExceededError, BudgetManager, CostBudget, RequestBudget, RuntimeBudget
from nordtrace.core.request_gateway import RequestGateway, SSRFError, validate_url


# --- request budget: hard stop ---
def test_request_budget_hard_stop():
    b = RequestBudget(global_limit=5)
    for _ in range(5):
        assert b.try_acquire(1)
    assert not b.try_acquire(1)  # would exceed
    assert b.remaining() == 0


def test_request_budget_atomic_no_races():
    b = RequestBudget(global_limit=100)
    import threading

    def worker():
        while b.try_acquire(1):
            pass

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert b.total_used == 100  # exactly the limit, no overshoot


def test_request_budget_try_acquire_n():
    b = RequestBudget(global_limit=10)
    assert b.try_acquire(3)
    assert b.remaining() == 7
    assert not b.try_acquire(8)
    assert b.try_acquire(7)
    assert b.remaining() == 0


def test_budget_manager_check_raises():
    bm = BudgetManager(max_requests=1)
    bm.requests.try_acquire(1)
    with pytest.raises(BudgetExceededError):
        bm.check()


def test_budget_manager_runtime_deadline():
    bm = BudgetManager(max_runtime_sec=0.05)
    import time as _t

    _t.sleep(0.1)
    assert bm.runtime.deadline_reached()
    with pytest.raises((BudgetExceededError, RuntimeError)):
        bm.check()


# --- runtime budget semantics ---
def test_runtime_global_deadline_wins():
    rt = RuntimeBudget(total_limit_sec=0.01, per_company_soft_sec=9999)
    import time as _t

    _t.sleep(0.02)
    assert rt.deadline_reached()
    assert rt.time_remaining() == 0.0


def test_runtime_phases():
    rt = RuntimeBudget(total_limit_sec=3600)
    assert rt.phase() == "full_research"
    rt2 = RuntimeBudget(total_limit_sec=300)
    assert rt2.phase() in ("prioritize_high_value", "finish_incomplete", "serialize_results")


def test_runtime_should_start_expensive():
    rt = RuntimeBudget(total_limit_sec=10)
    assert rt.should_start_expensive_operation(5)
    assert not rt.should_start_expensive_operation(60)


# --- cost budget ---
def test_cost_budget_accumulates():
    cb = CostBudget(limit=1.0)
    cb.record("gpt-4o-mini", 1000, 500, 0.01)
    cb.record("gpt-4o-mini", 1000, 500, 0.02)
    assert abs(cb.total_used - 0.03) < 1e-9
    assert cb.calls == 2
    assert cb.input_tokens == 2000 and cb.output_tokens == 1000


def test_cost_budget_cannot_afford():
    cb = CostBudget(limit=0.01)
    cb.record("m", 100, 100, 0.009)
    assert not cb.can_afford(0.005)
    assert cb.can_afford(0.001)


def test_cost_estimate_formula():
    cb = CostBudget()
    est = cb.estimate(1_000_000, 1_000_000, 0.15, 0.60)
    assert abs(est - 0.75) < 1e-9


# --- SSRF guard ---
@pytest.mark.parametrize(
    "bad",
    [
        "http://localhost/x",
        "http://127.0.0.1/x",
        "http://0.0.0.0/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://192.168.1.1/admin",
        "http://10.0.0.5/x",
        "http://172.16.0.1/x",
        "file:///etc/passwd",
        "ftp://example.com/file",
        "javascript:alert(1)",
        "",
    ],
)
def test_ssrf_blocked(bad):
    with pytest.raises(SSRFError):
        validate_url(bad)


def test_ssrf_resolves_private_hostname():
    with pytest.raises(SSRFError):
        validate_url("http://localhost.localdomain/x")


def test_url_normalization():
    url, host = validate_url("HTTPS://Data.Brreg.no/enhetsregisteret/api/enheter/982463718?x=1#frag")
    assert url == "https://data.brreg.no/enhetsregisteret/api/enheter/982463718?x=1"
    assert host == "data.brreg.no"


def test_url_default_port_stripped():
    url, _ = validate_url("https://example.com:443/path")
    assert url == "https://example.com/path"
    url2, _ = validate_url("http://example.com:8080/path")
    assert ":8080" in url2


def test_url_allowed_domains():
    url, host = validate_url("https://sub.telenor.no/x", allowed_domains=["telenor.no"])
    assert host == "sub.telenor.no"
    with pytest.raises(SSRFError):
        validate_url("https://evil.com/x", allowed_domains=["telenor.no"])


# --- gateway budget integration ---
def test_gateway_enforces_budget_without_network():
    """Gateway raises BudgetExceededError when budget exhausted — no request is sent."""

    async def go():
        bm = BudgetManager(max_requests=1)
        gw = RequestGateway(bm)
        bm.requests.try_acquire(1)  # exhaust
        with pytest.raises(BudgetExceededError):
            # external URL but budget check fires before any network I/O
            await gw.fetch("https://example.com/x")

    asyncio.run(go())

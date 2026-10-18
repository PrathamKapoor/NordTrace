"""Slow OS resolution must not block cancellation, finalization or process exit."""
import asyncio
import subprocess
import sys
import textwrap
import threading
import time

import httpx
import pytest

from nordtrace.core.budget import BudgetExceededError, BudgetManager, DeadlineReachedError
from nordtrace.core.request_gateway import PinnedTransport, RequestGateway
from nordtrace.smoke import TransportAudit


def test_gateway_deadline_does_not_wait_for_a_blocked_resolver(monkeypatch):
    release = threading.Event()
    finished = threading.Event()
    calls = []
    def resolve(host):
        try:
            release.wait(2)
            return ["8.8.8.8"]
        finally:
            finished.set()
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", resolve)
    timer = threading.Timer(0.6, release.set)
    timer.start()
    async def execute():
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append(r)))
        budget = BudgetManager(max_runtime_sec=0.1)
        gateway = RequestGateway(budget)
        gateway._client = client
        try:
            try:
                source = await gateway.fetch("https://fixture.example/", retries=0)
                return source.access_status, budget.requests.total_used
            except (BudgetExceededError, DeadlineReachedError):
                return "budget_exception_after_blocking", budget.requests.total_used
        finally:
            await gateway.aclose()
    started = time.monotonic()
    try:
        state, requests = asyncio.run(execute())
        elapsed = time.monotonic() - started
    finally:
        release.set()
        timer.cancel()
        assert finished.wait(1)
    assert elapsed < 0.4
    assert state == "timeout" and requests == 0 and calls == []


def test_connection_resolution_remains_cancellable_before_numeric_transport(monkeypatch):
    release = threading.Event()
    finished = threading.Event()
    connections = []
    def resolve(host):
        try:
            release.wait(2)
            return ["8.8.8.8"]
        finally:
            finished.set()
    async def connect(self, request):
        connections.append(request)
        return httpx.Response(200)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", resolve)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", connect)
    timer = threading.Timer(0.6, release.set)
    timer.start()
    async def execute():
        try:
            async with asyncio.timeout(0.1), PinnedTransport() as transport:
                await transport.handle_async_request(httpx.Request("GET", "https://fixture.example/"))
        except TimeoutError:
            return "cancelled"
        return "completed"
    started = time.monotonic()
    try:
        state = asyncio.run(execute())
        elapsed = time.monotonic() - started
    finally:
        release.set()
        timer.cancel()
        assert finished.wait(1)
    assert state == "cancelled" and elapsed < 0.4 and connections == []


def test_process_exit_does_not_join_an_uncancellable_os_dns_call():
    code = textwrap.dedent("""
        import asyncio, time, httpx
        import nordtrace.core.request_gateway as gateway_module
        from nordtrace.core.budget import BudgetManager
        def slow(host):
            time.sleep(10)
            return ["8.8.8.8"]
        gateway_module._resolve_host = slow
        async def run():
            gateway = gateway_module.RequestGateway(BudgetManager(max_runtime_sec=0.1))
            gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
            try:
                source = await gateway.fetch("https://fixture.example/", retries=0)
                assert source.access_status == "timeout"
                assert gateway.budget.requests.total_used == 0
            finally:
                await gateway.aclose()
        asyncio.run(run())
        print("deadline_and_process_exit_passed")
    """)
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=4)
    assert result.returncode == 0, result.stderr
    assert "deadline_and_process_exit_passed" in result.stdout


def test_cancelled_lookups_hold_capacity_until_os_resolution_really_finishes(monkeypatch):
    import nordtrace.core.request_gateway as module

    monkeypatch.setattr(module, "_DNS_SLOTS", threading.BoundedSemaphore(2))
    release = threading.Event()
    finished = threading.Event()
    lock = threading.Lock()
    active = maximum = started = 0
    connections = []
    def resolve(host):
        nonlocal active, maximum, started
        with lock:
            active += 1
            started += 1
            maximum = max(maximum, active)
        try:
            release.wait(2)
            return ["8.8.8.8"]
        finally:
            with lock:
                active -= 1
                if active == 0:
                    finished.set()
    monkeypatch.setattr(module, "_resolve_host", resolve)
    async def fetch():
        gateway = RequestGateway(BudgetManager(max_runtime_sec=0.1))
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: connections.append(request)))
        try:
            return await gateway.fetch("https://fixture.example/", retries=0)
        finally:
            await gateway.aclose()
    async def execute():
        results = await asyncio.gather(*(fetch() for _ in range(20)))
        assert all(source.access_status == "timeout" for source in results)
        # Cancelled callers must not permit new workers while the old OS calls live.
        later = await fetch()
        assert later.access_status == "timeout"
        with lock:
            assert active == started == maximum == 2
    try:
        asyncio.run(execute())
    finally:
        release.set()
        assert finished.wait(1)
    assert connections == []


def test_cancelled_connection_dns_is_charged_but_not_counted_as_http_or_source_failure(monkeypatch):
    release = threading.Event()
    finished = threading.Event()
    resolutions = 0
    def resolve(host):
        nonlocal resolutions
        resolutions += 1
        if resolutions <= 2:
            return ["8.8.8.8"]
        try:
            release.wait(2)
            return ["8.8.8.8"]
        finally:
            finished.set()
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", resolve)
    timer = threading.Timer(0.6, release.set)
    timer.start()
    async def execute():
        client = httpx.AsyncClient(transport=PinnedTransport(), trust_env=False)
        budget = BudgetManager(max_runtime_sec=0.2)
        gateway = RequestGateway(budget)
        gateway._client = client
        try:
            with TransportAudit() as audit:
                source = await gateway.fetch("https://fixture.example/", retries=0)
            return source, budget.requests.snapshot(), gateway.rate_limiter.snapshot(), audit.operations
        finally:
            await gateway.aclose()
    try:
        source, telemetry, health, dispatches = asyncio.run(execute())
    finally:
        release.set()
        timer.cancel()
        assert finished.wait(1)
    assert source.access_status == "timeout" and resolutions == 3
    assert telemetry["total_used"] == telemetry["unstarted_reservations"] == 1
    assert telemetry["transport_operations"] == telemetry["unresolved_reservations"] == 0
    assert dispatches == []
    assert health["fixture.example"]["consecutive_failures"] == 0
    assert health["fixture.example"]["total_requests"] == 0


@pytest.mark.parametrize("host,addresses", [
    ("different.example", ("8.8.8.8",)),
    ("fixture.example", ("127.0.0.1",)),
    ("fixture.example", ()),
])
def test_prepared_destination_cannot_bypass_host_or_public_address_checks(monkeypatch, host, addresses):
    from nordtrace.core.request_gateway import SSRFError, _ResolvedDestination

    connections = []
    async def connect(self, request):
        connections.append(request)
        return httpx.Response(200)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", connect)
    async def execute():
        async with PinnedTransport() as transport:
            with pytest.raises(SSRFError):
                await transport.handle_async_request(httpx.Request(
                    "GET", "https://fixture.example/",
                    extensions={"_nordtrace_destination": _ResolvedDestination(host, addresses)},
                ))
    asyncio.run(execute())
    assert connections == []


def test_source_domain_rejection_does_not_start_dns_or_http(monkeypatch):
    def resolve(host):
        raise AssertionError("source policy rejection must precede DNS")
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", resolve)
    budget = BudgetManager(max_requests=3)
    async def execute():
        gateway = RequestGateway(budget)
        try:
            return await gateway.fetch("https://other.example/", allowed_domains=["allowed.example"])
        finally:
            await gateway.aclose()
    assert asyncio.run(execute()).access_status == "blocked"
    assert budget.requests.total_used == 0

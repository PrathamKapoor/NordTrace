"""Instrument the actual httpx transport boundary; no external sockets."""

import asyncio
import time

import httpx
import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.config import settings
from nordtrace.core.rate_limiter import RateLimiter, SourcePolicy
from nordtrace.core.request_gateway import RequestGateway


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])


def gateway(handler, monkeypatch, **limits):
    original = httpx.AsyncClient

    def client(**kwargs):
        kwargs.pop("transport", None)
        return original(transport=httpx.MockTransport(handler), **kwargs)

    # Also intercept the legacy robots client's hidden transport when reproducing.
    monkeypatch.setattr("nordtrace.core.request_gateway.httpx.AsyncClient", client)
    budget = BudgetManager(**limits)
    limiter = RateLimiter(default_policy=SourcePolicy(min_interval=0))
    return RequestGateway(budget, rate_limiter=limiter), budget


def test_redirect_to_loopback_is_blocked_before_second_transport(monkeypatch):
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    gw, budget = gateway(respond, monkeypatch)

    async def execute():
        try:
            return await gw.fetch("https://public.example/start", retries=0)
        finally:
            await gw.aclose()

    result = asyncio.run(execute())
    assert calls == ["https://public.example/start"]
    assert result.access_status == "blocked"
    assert budget.requests.total_used == 1


def test_permitted_redirect_hops_equal_instrumented_request_count(monkeypatch):
    calls = []

    def respond(request):
        calls.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(200, text="retained source")

    gw, budget = gateway(respond, monkeypatch)

    async def execute():
        try:
            return await gw.fetch("https://public.example/start", retries=0)
        finally:
            await gw.aclose()

    result = asyncio.run(execute())
    assert result.access_status == "success"
    assert budget.requests.total_used == len(calls) == 2
    assert result.final_url == "https://public.example/final"
    assert result.redirect_chain == ["https://public.example/start", "https://public.example/final"]


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks, delay=0):
        self.chunks = chunks
        self.delay = delay
        self.reads = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            await asyncio.sleep(self.delay)
            self.reads += 1
            yield chunk

    async def aclose(self):
        self.closed = True


def test_stream_limit_stops_reading_before_full_allocation(monkeypatch):
    stream = Chunks([b"1234", b"5678", b"unread"])
    gw, budget = gateway(lambda request: httpx.Response(200, stream=stream), monkeypatch)

    async def execute():
        try:
            return await gw.fetch("https://public.example/large", max_bytes=5, retries=0)
        finally:
            await gw.aclose()

    result = asyncio.run(execute())
    assert result.access_status == "failed"
    assert stream.reads == 2
    assert stream.closed
    assert gw.get_content("https://public.example/large") is None
    assert budget.requests.total_used == 1


def test_absolute_deadline_cancels_slow_body_stream(monkeypatch):
    stream = Chunks([b"slow source"], delay=2)
    gw, budget = gateway(
        lambda request: httpx.Response(200, stream=stream), monkeypatch, max_runtime_sec=0.5
    )

    async def execute():
        try:
            return await gw.fetch("https://public.example/slow", retries=0)
        finally:
            await gw.aclose()

    started = time.monotonic()
    result = asyncio.run(execute())
    assert time.monotonic() - started < 1
    assert result.access_status == "timeout"
    assert stream.reads == 0
    assert stream.closed
    assert budget.requests.total_used == 1


def test_robots_transport_is_counted_and_deny_prevents_content_request(monkeypatch):
    calls = []

    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(200, text="User-agent: *\nDisallow: /private")

    gw, budget = gateway(respond, monkeypatch)

    async def execute():
        try:
            return await gw.fetch("https://public.example/private", respect_robots=True, retries=0)
        finally:
            await gw.aclose()

    result = asyncio.run(execute())
    assert result.access_status == "robots_denied"
    assert calls == ["/robots.txt"]
    assert budget.requests.total_used == len(calls) == 1


def test_robots_unavailable_fails_closed(monkeypatch):
    calls = []

    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(503)

    gw, budget = gateway(respond, monkeypatch)

    async def execute():
        try:
            return await gw.fetch("https://public.example/page", respect_robots=True, retries=0)
        finally:
            await gw.aclose()

    result = asyncio.run(execute())
    assert result.access_status == "robots_denied"
    assert calls == ["/robots.txt"]
    assert budget.requests.total_used == 1


@pytest.mark.parametrize("prime_permissive_cache", [False, True])
@pytest.mark.parametrize("policy", ["scheme", "origin"])
def test_robots_redirects_and_cache_obey_source_policy(monkeypatch, prime_permissive_cache, policy):
    calls = []

    def respond(request):
        calls.append(str(request.url))
        if (request.url.path == "/robots.txt" and request.url.scheme == "https"
                and request.url.port in (None, 443)):
            destination = ("http://public.example/robots.txt" if policy == "scheme"
                           else "https://public.example:8443/robots.txt")
            return httpx.Response(302, headers={"location": destination})
        return httpx.Response(
            200, text="User-agent: *\nAllow: /" if request.url.path == "/robots.txt" else "page"
        )

    gw, budget = gateway(respond, monkeypatch)

    async def execute():
        try:
            if prime_permissive_cache:
                permissive = await gw.fetch("https://public.example/page", respect_robots=True, retries=0)
                assert permissive.access_status == "success"
                calls.clear()
            before = budget.requests.total_used
            source = await gw.fetch(
                "https://public.example/page", respect_robots=True, retries=0,
                **({"allowed_schemes": ["https"]} if policy == "scheme"
                   else {"allowed_origins": ["https://public.example"]}),
            )
            assert budget.requests.total_used - before == len(calls)
            return source
        finally:
            await gw.aclose()

    source = asyncio.run(execute())
    assert source.access_status == "robots_denied"
    assert not any(url.startswith("http://") or url.endswith("/page") for url in calls)
    assert not any(":8443" in url for url in calls)
    assert budget.requests.total_used == (3 if prime_permissive_cache else 1)


def test_redirect_limit_is_enforced_at_each_hop(monkeypatch):
    monkeypatch.setattr(settings, "max_redirects", 2)
    calls = []

    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(302, headers={"location": f"/hop-{len(calls)}"})

    gw, budget = gateway(respond, monkeypatch)

    async def execute():
        try:
            return await gw.fetch("https://public.example/start", retries=0)
        finally:
            await gw.aclose()

    result = asyncio.run(execute())
    assert result.access_status == "failed"
    assert len(calls) == budget.requests.total_used == 3


def test_dns_rebinding_is_rejected_by_connection_transport(monkeypatch):
    from nordtrace.core.request_gateway import PinnedTransport, SSRFError, validate_url

    answers = iter([["8.8.8.8"], ["127.0.0.1"]])
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: next(answers))
    validate_url("https://public.example/page")
    connections = []

    async def connect(self, request):
        connections.append(request)
        return httpx.Response(200)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", connect)

    async def execute():
        async with PinnedTransport() as transport:
            with pytest.raises(SSRFError, match="public"):
                await transport.handle_async_request(httpx.Request("GET", "https://public.example/page"))

    asyncio.run(execute())
    assert connections == []


def test_connection_uses_validated_ip_with_original_host_and_tls_name(monkeypatch):
    from nordtrace.core.request_gateway import PinnedTransport

    connections = []

    async def connect(self, request):
        connections.append((request.url.host, request.headers["host"], request.extensions["sni_hostname"]))
        return httpx.Response(200)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", connect)

    async def execute():
        async with PinnedTransport() as transport:
            await transport.handle_async_request(httpx.Request("GET", "https://public.example/page"))

    asyncio.run(execute())
    assert connections == [("8.8.8.8", "public.example", "public.example")]


def test_same_ip_hosts_have_separate_tls_handshakes_and_safe_keepalive(monkeypatch):
    from httpcore._backends.auto import AutoBackend
    from httpcore._backends.mock import AsyncMockStream

    from nordtrace.core.request_gateway import PinnedTransport

    tls_names = []
    connections = []
    response = b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\n\r\nx"

    class Stream(AsyncMockStream):
        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            tls_names.append(server_hostname)
            return self

    async def connect(self, host, port, **kwargs):
        connections.append(host)
        return Stream([response, response, response])

    monkeypatch.setattr(AutoBackend, "connect_tcp", connect)

    async def execute():
        async with httpx.AsyncClient(transport=PinnedTransport(), trust_env=False) as client:
            for url in ("https://one.example/a", "https://two.example/b", "https://one.example/c"):
                assert (await client.get(url)).status_code == 200

    asyncio.run(execute())
    assert connections == ["8.8.8.8", "8.8.8.8"]
    assert tls_names == ["one.example", "two.example"]


def test_redirect_target_zero_retry_policy_is_respected(monkeypatch):
    calls = []

    def respond(request):
        calls.append(request.url.host)
        if request.url.host == "first.example":
            return httpx.Response(302, headers={"location": "https://target.example/page"})
        return httpx.Response(500)

    gw, budget = gateway(respond, monkeypatch)
    gw.rate_limiter.state_for("target.example").policy = SourcePolicy(min_interval=0, max_retries=0)

    async def execute():
        try:
            return await gw.fetch("https://first.example/page", retries=2)
        finally:
            await gw.aclose()

    result = asyncio.run(execute())
    assert result.access_status == "failed"
    assert calls == ["first.example", "target.example"]
    assert budget.requests.total_used == 2

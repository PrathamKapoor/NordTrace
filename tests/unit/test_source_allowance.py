"""A persisted run source allowlist limits acquisition before DNS or HTTP."""
import asyncio

import httpx
import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.models import ResearchRun, RunConfiguration
from nordtrace.core.repository import Repository
from nordtrace.core.request_gateway import RequestGateway


@pytest.mark.parametrize("origin", ["https://data.brreg.no/path", "https://user@data.brreg.no",
                                    "https://data.brreg.no?x=1", "https://data.brreg.no/#frag",
                                    "file:///data.brreg.no", "https://data.brreg.no:0",
                                    "https://data.brreg.no\n"])
def test_source_allowance_rejects_non_origin_policy_entries(origin):
    with pytest.raises(ValueError):
        RunConfiguration(max_requests=10, max_runtime_sec=30, max_cost_usd=0,
                         allowed_source_origins=[origin])


@pytest.mark.parametrize("url", ["https://other.example/", "http://data.brreg.no/",
                                 "https://data.brreg.no:444/", "https://data.brreg.no.evil.example/"])
def test_disallowed_source_never_reaches_dns_or_transport(monkeypatch, url):
    budget = BudgetManager(max_requests=10, allowed_source_origins=["https://data.brreg.no"])
    calls = []
    def dns(host):
        pytest.fail("excluded source must be rejected before DNS")
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", dns)
    async def execute():
        gateway = RequestGateway(budget)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: calls.append(request) or httpx.Response(200)))
        try:
            return await gateway.fetch(url, respect_robots=True, allowed_origins=[url.rstrip("/")])
        finally:
            await gateway.aclose()
    source = asyncio.run(execute())
    assert source.access_status == "blocked" and "run source" in source.error_detail
    assert source.http_status is None and not source.content_hash
    assert source.retrieved_at is None and source.discovered_at
    assert not calls and budget.requests.total_used == 0


def test_permitted_first_hop_cannot_redirect_outside_run_policy(monkeypatch):
    budget = BudgetManager(max_requests=10, allowed_source_origins=["https://DATA.BRREG.NO:443/"])
    assert budget.configuration.allowed_source_origins == ["https://data.brreg.no"]
    dns, calls = [], []
    def resolve(host):
        dns.append(host)
        return ["8.8.8.8"]
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", resolve)
    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://other.example/"})
    async def execute():
        gateway = RequestGateway(budget)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await gateway.fetch("https://data.brreg.no/entity", retries=0)
        finally:
            await gateway.aclose()
    result = asyncio.run(execute())
    assert result.access_status == "blocked"
    assert calls == ["https://data.brreg.no/entity"]
    assert all(host == "data.brreg.no" for host in dns)
    assert budget.requests.total_used == 1


def test_replacement_worker_restores_restrictive_source_policy(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "policy.db")
    run = ResearchRun(companies=["982463718"])
    repo.create_run(run)
    original = BudgetManager(max_requests=10, max_runtime_sec=60, allowed_source_origins=[])
    original.bind_run(repo, run.run_id, initialize=True)
    replacement = BudgetManager(max_requests=100)
    replacement.bind_run(repo, run.run_id)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host",
                        lambda host: pytest.fail("deny-all policy must survive resume"))
    async def execute():
        gateway = RequestGateway(replacement)
        try:
            return await gateway.fetch("https://data.brreg.no/")
        finally:
            await gateway.aclose()
    try:
        assert replacement.configuration.allowed_source_origins == []
        assert asyncio.run(execute()).access_status == "blocked"
        assert replacement.requests.total_used == 0
    finally:
        repo.close()


def test_cache_redirect_chain_is_rechecked_against_narrowed_run_policy(monkeypatch):
    budget = BudgetManager(max_requests=10)
    calls, dns = [], []
    def resolve(host):
        dns.append(host)
        return ["8.8.8.8"]
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", resolve)
    def respond(request):
        calls.append(str(request.url))
        if request.url.host == "data.brreg.no":
            return httpx.Response(302, headers={"location": "https://other.example/final"})
        return httpx.Response(200, text="captured")
    async def execute():
        gateway = RequestGateway(budget)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            assert (await gateway.fetch("https://data.brreg.no/start", retries=0)).access_status == "success"
            budget.configuration.allowed_source_origins = ["https://data.brreg.no"]
            dns.clear()
            return await gateway.fetch("https://data.brreg.no/start", retries=0)
        finally:
            await gateway.aclose()
    result = asyncio.run(execute())
    assert result.access_status == "blocked" and not result.cache_hit
    assert all(host == "data.brreg.no" for host in dns)
    assert len(calls) == budget.requests.total_used == 2


def test_robots_redirect_cannot_escape_run_source_policy(monkeypatch):
    budget = BudgetManager(max_requests=10, allowed_source_origins=["https://data.brreg.no"])
    calls, dns = [], []
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host",
                        lambda host: dns.append(host) or ["8.8.8.8"])
    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://other.example/robots.txt"})
    async def execute():
        gateway = RequestGateway(budget)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await gateway.fetch("https://data.brreg.no/page", respect_robots=True, retries=0)
        finally:
            await gateway.aclose()
    result = asyncio.run(execute())
    assert result.access_status == "robots_denied"
    assert all(host == "data.brreg.no" for host in dns)
    assert calls == ["https://data.brreg.no/robots.txt"]
    assert budget.requests.total_used == 1


def test_narrowed_run_policy_cannot_reuse_foreign_robots_redirect(monkeypatch):
    budget = BudgetManager(max_requests=10)
    calls = []
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    def respond(request):
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            if request.url.host == "data.brreg.no":
                return httpx.Response(302, headers={"location": "https://other.example/robots.txt"})
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(200, text="page")
    async def execute():
        gateway = RequestGateway(budget)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            first = await gateway.fetch("https://data.brreg.no/one", respect_robots=True)
            assert first.access_status == "success"
            budget.configuration.allowed_source_origins = ["https://data.brreg.no"]
            return await gateway.fetch("https://data.brreg.no/two", respect_robots=True)
        finally:
            await gateway.aclose()
    assert asyncio.run(execute()).access_status == "robots_denied"
    assert calls.count("https://other.example/robots.txt") == 1
    assert "https://data.brreg.no/two" not in calls

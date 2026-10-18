"""The documented public website/PDF robots policy cannot be disabled globally."""
import asyncio

import httpx
import pytest

from nordtrace.core.budget import BudgetManager
from nordtrace.core.config import Settings, settings
from nordtrace.core.request_gateway import RequestGateway


@pytest.mark.parametrize("value", [False, "false", "0"])
def test_configuration_cannot_disable_public_robots_policy(value):
    with pytest.raises(ValueError, match="robots.*cannot be disabled"):
        Settings(_env_file=None, respect_robots=value)


def test_environment_cannot_disable_public_robots_policy(monkeypatch):
    monkeypatch.setenv("RESPECT_ROBOTS", "false")
    with pytest.raises(ValueError, match="robots.*cannot be disabled"):
        Settings(_env_file=None)


def test_enabled_robots_setting_remains_compatible():
    assert Settings(_env_file=None, respect_robots=True).respect_robots is True


def test_runtime_flag_mutation_cannot_bypass_a_site_denial(monkeypatch):
    monkeypatch.setattr(settings, "respect_robots", False)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    calls = []
    budget = BudgetManager(max_requests=3)
    def respond(request):
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(403)
        return httpx.Response(200, text="private")
    async def execute():
        gateway = RequestGateway(budget)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await gateway.fetch("https://fixture.example/private", source_type="company_website",
                                       respect_robots=True, retries=0)
        finally:
            await gateway.aclose()
    source = asyncio.run(execute())
    assert source.access_status == "robots_denied"
    assert calls == ["https://fixture.example/robots.txt"]
    assert budget.requests.total_used == 1


@pytest.mark.parametrize("source_type", ["company_website", "company_document"])
def test_website_source_kind_enforces_robots_without_an_adapter_opt_in(monkeypatch, source_type):
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    calls = []
    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(403) if request.url.path == "/robots.txt" else httpx.Response(200)
    async def execute():
        gateway = RequestGateway(BudgetManager(max_requests=3))
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await gateway.fetch("https://fixture.example/content", source_type=source_type,
                                       respect_robots=False, retries=0)
        finally:
            await gateway.aclose()
    assert asyncio.run(execute()).access_status == "robots_denied"
    assert calls == ["https://fixture.example/robots.txt"]

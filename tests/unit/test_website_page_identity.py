"""Synthetic internal-page identity negatives; no third-party page material."""
import asyncio

import httpx
import pytest
from bs4 import BeautifulSoup

from nordtrace.adapters.website import WebsiteAdapter
from nordtrace.core.budget import BudgetManager
from nordtrace.core.entity import EntityResolver
from nordtrace.core.models import CompanyIdentity
from nordtrace.core.repository import Repository
from nordtrace.core.request_gateway import RequestGateway

ORG = "982463718"
OTHER = "923609016"
HOME = "https://fixture.example/"


@pytest.mark.parametrize("footer,accepted", [
    (f"<p>Customer service</p><footer>Org.nr {OTHER}</footer>", False),
    (f"<footer>Customer Org.nr {OTHER}</footer>", True),
    ("<footer>Org.<span>nr</span> <span>982</span><span>463</span><span>718</span></footer>", True),
])
def test_homepage_identity_keeps_block_context_and_inline_identifiers(footer, accepted):
    soup = BeautifulSoup(f"<main>FIXTURE AS Org.nr {ORG}</main>{footer}", "lxml")
    adapter = WebsiteAdapter(None, BudgetManager(), EntityResolver())
    identity = CompanyIdentity(organisation_number=ORG, legal_name="FIXTURE AS", website=HOME)
    ok, _ = adapter.verify_site_homepage(identity, adapter._identity_text(soup), HOME)
    assert ok is accepted


@pytest.mark.parametrize("path", ["contact", "products", "news", "careers"])
@pytest.mark.parametrize("placement", [
    "footer", "late_body", "separate_customer_heading", "customer_break", "customer_rule",
    "customer_footer", "target_footer",
])
def test_internal_page_identity_checks_full_uncleaned_text(
    tmp_path, monkeypatch, path, placement,
):
    # Removing the pre-cleaning check, or checking only a text prefix, must fail.
    foreign = f"Org.nr {OTHER}"
    suffix = {
        "footer": f"<footer>{foreign}</footer>",
        "late_body": "x " * 11000 + foreign,
        "separate_customer_heading": f"<p>Customer service</p><footer>{foreign}</footer>",
        "customer_break": f"<footer>Customer service<br>{foreign}</footer>",
        "customer_rule": f"<footer>Customer service<hr>{foreign}</footer>",
        "customer_footer": f"<footer>Customer {foreign}</footer>",
        "target_footer": "<footer>Org.nr <span>982</span><span>463</span><span>718</span></footer>",
    }[placement]
    body = (f"<main>FIXTURE AS Org.nr {ORG} contact@fixture.example "
            f'<a href="/jobs/engineer">Engineer position</a></main>{suffix}')
    repo = Repository(tmp_path / "identity.db")
    budget = BudgetManager(max_requests=50)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    def respond(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        text = (f'<p>FIXTURE AS Org.nr {ORG}</p><a href="/{path}">Details</a>'
                if request.url.path == "/" else body)
        return httpx.Response(200, text=text)

    async def execute():
        gateway = RequestGateway(budget, repository=repo)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await WebsiteAdapter(gateway, budget, EntityResolver()).crawl(
                CompanyIdentity(organisation_number=ORG, legal_name="FIXTURE AS", website=HOME),
                "fixture",
            )
        finally:
            await gateway.aclose()

    try:
        evidence, facts, sources, rejected, coverage = asyncio.run(execute())
        page = next(source for source in sources if source.url == HOME + path)
        captured, raw = repo.read_capture(page.source_id)
        assert body.encode() == raw and captured.content_hash == page.content_hash
        if placement not in ("customer_footer", "target_footer"):
            assert any(item["url"] == HOME + path and OTHER in item["reason"] for item in rejected)
            assert not any(item.source_id == page.source_id for item in evidence + facts)
            assert coverage.get({"contact": "locations", "products": "products_services",
                                 "news": "recent_activity", "careers": "jobs"}[path]) != "found"
        else:
            assert not rejected
            assert any(item.source_id == page.source_id for item in evidence)
            assert any(item.source_id == page.source_id for item in facts)
        assert budget.requests.total_used == 4
    finally:
        repo.close()

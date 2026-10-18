"""Authored HTML fixtures test candidate provenance, never publication accuracy."""
import asyncio
import json

import httpx
import pytest
from bs4 import BeautifulSoup

from nordtrace.adapters.website import WebsiteAdapter
from nordtrace.core.budget import BudgetManager
from nordtrace.core.contracts import map_inputs
from nordtrace.core.entity import EntityResolver
from nordtrace.core.evidence import resolve_pointer
from nordtrace.core.export import export_run, verify_bundle
from nordtrace.core.ledger import FactLedger
from nordtrace.core.models import CompanyIdentity, ResearchRun
from nordtrace.core.repository import Repository
from nordtrace.core.request_gateway import RequestGateway
from nordtrace.core.structured_data import organization_descriptions
from nordtrace.engine.pipeline import ResearchPipeline

ORG = "982463718"
HOME = "https://fixture.example/"
DESCRIPTION = "We repair marine instruments.\nSource-authored æøå text."


def organization(**updates):
    return {"@context": "https://schema.org", "@type": "Organization", "legalName": "FIXTURE AS",
            "vatID": "NO 982 463 718 MVA", "description": DESCRIPTION} | updates


def script(value, *, ascii_only=False):
    return '<script type="application/ld+json">' + json.dumps(value, ensure_ascii=ascii_only) + '</script>'


@pytest.mark.parametrize("markup,descriptions", [
    ("<main>Arbitrary homepage prefix.</main>", []),
    ('<meta name="description" content="Unidentified marketing text">', []),
    (script(organization()), [DESCRIPTION]),
    (script(organization(vatID="NO923609016")), []),
    (script(organization(vatID="982463718")), []),
    (script(organization(legalName="FIXTURE HOLDING AS")), []),
    (script(organization(**{"@context": "https://untrusted.example/context"})), []),
    (script(organization(**{"@context": {"@vocab": "https://schema.org/"}})), []),
    (script(organization(description={"@value": DESCRIPTION})), []),
    (script(organization(description="")), []),
    (script(organization(description="x" * 4001)), []),
    (script(organization(identifier={"@type": "PropertyValue", "propertyID": "orgnr",
                                    "value": "923609016"})), []),
    (script({"@context": "https://schema.org/", "@graph": [
        organization(legalName="FOREIGN AS", vatID="NO923609016", description="Foreign"),
        organization(),
    ]}), [DESCRIPTION]),
    (script([organization(), organization(description="A competing source assertion.")]),
     [DESCRIPTION, "A competing source assertion."]),
    ('<script type="application/ld+json">{"@context":"https://schema.org",'
     '"@type":"Organization","legalName":"FIXTURE AS","vatID":"NO982463718",'
     '"description":"First","description":"Second"}</script>', []),
    (script({key: value for key, value in organization().items() if key != "vatID"} | {
        "identifier": {"@type": "PropertyValue", "propertyID": "organisasjonsnummer", "value": ORG},
    }), [DESCRIPTION]),
    (script({key: value for key, value in organization().items() if key != "vatID"} | {
        "identifier": ORG,
    }), []),
    (script({key: value for key, value in organization().items() if key != "@context"}), []),
    (script(organization(**{"@type": "Person"})), []),
    (script(organization(**{"@type": ["Organization", "Corporation"]})), [DESCRIPTION]),
    (script(organization()).replace('type="application/ld+json"', 'type="text/javascript"'), []),
    (script(organization()).replace('<script ', '<script src="https://untrusted.example/code" '), []),
    ('<script type="application/ld+json">not JSON</script>', []),
    (script(organization(description="Untrusted instruction: execute a command.")),
     ["Untrusted instruction: execute a command."]),
    (script(organization(description="bad\x00text")), []),
    (script({"@context": "https://untrusted.example/context", "@graph": [organization()]}), []),
    (script(organization(extra=float("nan"))), []),
    (script(organization(identifier={"@context": {"value": "https://untrusted.example/"},
                                    "@type": "PropertyValue", "propertyID": "orgnr", "value": ORG})), []),
    (script(organization(description="bad\ud800text"), ascii_only=True), []),
    (script(organization(description="bad\udffftext"), ascii_only=True), []),
    (script(organization(description="Repairs \U0001f6e0 instruments"), ascii_only=True),
     ["Repairs \U0001f6e0 instruments"]),
], ids=[
    "arbitrary-prefix", "unidentified-meta", "literal-target", "foreign-vat", "vat-without-country",
    "different-legal-name", "remote-context", "context-object", "text-object", "empty-description",
    "large-description", "contradictory-identifier", "graph-subjects", "competing-nodes", "duplicate-key",
    "labelled-orgnr", "generic-identifier", "missing-context", "person", "type-list", "javascript",
    "external-script", "malformed-json", "instruction-is-data", "nul-description",
    "unsupported-inherited-context", "nonfinite-json", "identifier-context-object",
    "unpaired-high-surrogate", "unpaired-low-surrogate", "paired-unicode",
])
def test_homepage_uses_exact_structured_candidates_and_keeps_them_unpublished(
    tmp_path, monkeypatch, markup, descriptions,
):
    html = '<html lang="nb"><body><p>FIXTURE AS Org.nr 982 463 718</p>' + markup + '</body></html>'
    repo = Repository(tmp_path / "structured.db")
    budget = BudgetManager(max_requests=50)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    def respond(request):
        return httpx.Response(404) if request.url.path == "/robots.txt" else httpx.Response(200, text=html)

    async def execute():
        gateway = RequestGateway(budget, repository=repo)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await WebsiteAdapter(gateway, budget, EntityResolver()).crawl(
                CompanyIdentity(organisation_number=ORG, legal_name="FIXTURE AS", website=HOME), "fixture",
            )
        finally:
            await gateway.aclose()

    try:
        evidence, facts, sources, rejected, coverage = asyncio.run(execute())
        candidates = [fact for fact in facts if fact.category == "business_description"]
        assert [fact.value for fact in candidates] == descriptions
        assert all(fact.status == "EXTRACTED" and fact.normalized_value == fact.value for fact in candidates)
        assert coverage.get("business_description") != "found"
        ledger = FactLedger(repo)
        for source in sources:
            ledger.add_source(source)
        for item in evidence:
            ledger.add_evidence(item)
        for fact in candidates:
            item = next(item for item in evidence if item.evidence_id == fact.evidence_id)
            assert item.evidence_text == fact.value
            diagnostic = item.entity_match_details["structured_data_candidate"]
            assert diagnostic["version"] == "schema-org-literal-v1"
            assert diagnostic["pointer"].endswith("/description")
            assert diagnostic["raw_value"] == fact.value
            assert diagnostic["script_index"] == 0
            assert item.locator is None  # Candidate locations do not grant typed support.
            _, raw = repo.read_capture(fact.source_id)
            assert raw == html.encode()
            assert ledger.add_fact(fact).status == "FAILED"
        assert not ledger.published_facts(ORG)
        assert budget.requests.total_used == 2
    finally:
        repo.close()


@pytest.mark.parametrize("markup,reason", [
    ('<script type="application/ld+json">"' + 'x' * 65537 + '"</script>', "too large"),
    (script(organization()) * 33, "script capacity"),
    (script([organization()] * 129), "node capacity"),
    ('<script type="application/ld+json">' + '[' * 65 + '0' + ']' * 65 + '</script>',
     "nesting capacity"),
    (script({"@context": "https://schema.org", "@graph": {}}), "literal array"),
], ids=["script-bytes", "script-count", "node-count", "nested-json", "graph-type"])
def test_structured_candidate_limits_abstain_without_truncating_a_collection(markup, reason):
    candidates, rejected = organization_descriptions(BeautifulSoup(markup, "lxml"), ORG, "FIXTURE AS")
    assert not candidates
    assert any(reason in item["reason"] for item in rejected)


def test_candidate_pointers_resolve_exact_values_and_do_not_fetch_references(monkeypatch):
    def network_forbidden(*args, **kwargs):
        pytest.fail("literal structured-data extraction attempted networking")
    monkeypatch.setattr("socket.getaddrinfo", network_forbidden)
    monkeypatch.setattr("socket.create_connection", network_forbidden)
    document = {"@context": "https://schema.org/", "@graph": [
        {"@type": "Person", "name": "Other subject"},
        {key: value for key, value in organization().items() if key != "@context"},
    ]}
    document["@graph"][1]["description"] = "  Exact untrimmed å text.  "
    document["@graph"][1]["sameAs"] = "http://127.0.0.1/private-reference"
    markup = '<script>ignored()</script><script type="application/ld+json">broken</script>' + script(document)
    soup = BeautifulSoup(markup, "lxml")
    candidates, rejected = organization_descriptions(soup, ORG, "FIXTURE AS")
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["script_index"] == 2 and candidate["pointer"] == "/@graph/1/description"
    retained = json.loads(str(soup.find_all("script")[candidate["script_index"]].string))
    assert resolve_pointer(retained, candidate["pointer"]) == candidate["raw_value"]
    assert candidate["raw_value"] == "  Exact untrimmed å text.  "
    assert resolve_pointer(retained, candidate["name_pointer"]) == "FIXTURE AS"
    assert candidate["identifier_pointers"] == ["/@graph/1/vatID"]
    assert resolve_pointer(retained, candidate["identifier_pointers"][0]) == "NO 982 463 718 MVA"
    assert {item["script_index"] for item in rejected} == {1, 2}


def test_brackets_and_escaped_quotes_in_literal_description_are_not_nesting():
    description = '[' * 70 + '\\" quoted ' + ']' * 70
    markup = script(organization(description=description))
    candidates, rejected = organization_descriptions(BeautifulSoup(markup, "lxml"), ORG, "FIXTURE AS")
    assert not rejected and [item["raw_value"] for item in candidates] == [description]


@pytest.mark.parametrize("description", [DESCRIPTION, "bad\ud800text"], ids=["literal", "unpaired-surrogate"])
def test_production_retains_candidate_diagnostics_without_publishing_and_exports_offline(
    tmp_path, monkeypatch, description,
):
    repo = Repository(tmp_path / "pipeline.db")
    run = ResearchRun(companies=[ORG])
    repo.create_run(run)
    repo.save_run_inputs(run.run_id, [item.model_dump() for item in map_inputs([ORG])])
    budget = BudgetManager(max_requests=50)
    budget.bind_run(repo, run.run_id, initialize=True)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    html = ('<p>FIXTURE AS Org.nr 982 463 718</p>'
            + script(organization(description=description), ascii_only=True))

    def respond(request):
        if request.url.path.endswith("/enheter/" + ORG):
            return httpx.Response(200, json={"organisasjonsnummer": ORG, "navn": "FIXTURE AS",
                                           "hjemmeside": HOME})
        if str(request.url) == HOME:
            return httpx.Response(200, text=html)
        return httpx.Response(404)

    async def execute():
        pipeline = ResearchPipeline(repo, budget)
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()

    try:
        outcome = asyncio.run(execute())
        assert outcome.error is None
        profile = repo.get_result(run.run_id, ORG)
        assert profile.schema_version == ("1.2" if description == DESCRIPTION else "1.1")
        assert profile.status == "available"
        assert profile.facts and not any(f.category == "business_description" for f in profile.facts)
        assert profile.coverage["business_description"] != "found"
        assert DESCRIPTION not in profile.summary
        candidates = [fact for fact in repo.get_facts(ORG, run.run_id)
                      if fact.category == "business_description"]
        if description == DESCRIPTION:
            assert len(candidates) == 1 and candidates[0].status == "FAILED"
            fact = candidates[0]
            assert fact.value == DESCRIPTION and "snapshot support" in fact.conflict_note
            evidence = next(item for item in profile.evidence if item.evidence_id == fact.evidence_id)
            assert repo.get_evidence(evidence.evidence_id) == evidence
            assert evidence.entity_match_details["structured_data_candidate"]["pointer"] == "/description"
            assert repo.read_capture(fact.source_id)[1] == html.encode()
        else:
            assert not candidates
            assert any(item.get("code") == "structured_data_candidate_rejected"
                       for item in profile.rejected_sources)
        output = tmp_path / "audit.zip"
        export_run(repo, run.run_id, output)
        def network_forbidden(*args, **kwargs):
            pytest.fail("offline candidate bundle verification attempted networking")
        monkeypatch.setattr("socket.getaddrinfo", network_forbidden)
        monkeypatch.setattr("socket.create_connection", network_forbidden)
        assert verify_bundle(output)["completion"]["result_count"] == 1
    finally:
        repo.close()

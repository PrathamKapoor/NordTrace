"""Synthetic schema-v2 registry fixtures, authored for these tests (MIT).

Schema: official Enhetsregisteret docs retrieved 2026-10-17. Org numbers are
checksum-valid fixture identifiers, not assertions of real-world relationships.
No copied company/person data or live acquisition is required by this module.
"""

import asyncio
import json

import httpx
import pytest

from nordtrace.adapters.brreg import BrregAdapter
from nordtrace.core.budget import BudgetManager
from nordtrace.core.ledger import FactLedger
from nordtrace.core.models import ResearchRun, utcnow
from nordtrace.core.repository import Repository
from nordtrace.core.request_gateway import RequestGateway
from nordtrace.engine.pipeline import ResearchPipeline

ORG = "982463718"
FIRST = "958973306"
SECOND = "984851006"


def unit(org, parent=ORG, name="Fixture workplace"):
    return {
        "organisasjonsnummer": org, "overordnetEnhet": parent, "navn": name,
        "organisasjonsform": {"kode": "BEDR"},
        "beliggenhetsadresse": {
            "adresse": ["Fixture street 1"], "postnummer": "0001", "poststed": "OSLO", "kommune": "OSLO",
        },
        "postadresse": {"kommune": "BERGEN"},
        "naeringskode1": {"beskrivelse": "Fixture operations"},
    }


def page(number, units, total=2, pages=2):
    return {
        "_embedded": {"underenheter": units},
        "page": {"number": number, "size": 1, "totalElements": total, "totalPages": pages},
        # Deliberately unsafe discovery links must never control acquisition.
        "_links": {"next": {"href": "http://127.0.0.1/private"}},
    }


@pytest.mark.parametrize("second_status", [200, 403])
def test_pipeline_publishes_parent_verified_paginated_subunits_with_exact_snapshots(
    tmp_path, monkeypatch, second_status,
):
    monkeypatch.setattr("nordtrace.core.config.settings.brreg_branch_page_size", 1)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    repo = Repository(tmp_path / "subunits.db")
    run = ResearchRun(companies=[ORG], started_at=utcnow().isoformat())
    repo.create_run(run)
    requests = []

    def respond(request):
        requests.append(str(request.url))
        if request.url.path.endswith("/enheter/" + ORG):
            return httpx.Response(200, json={"organisasjonsnummer": ORG, "navn": "TARGET AS"})
        if request.url.path.endswith("/underenheter"):
            assert request.url.params["overordnetEnhet"] == ORG
            number = int(request.url.params["page"])
            if number == 1 and second_status != 200:
                return httpx.Response(second_status)
            return httpx.Response(200, json=page(number, [unit(FIRST if number == 0 else SECOND)]))
        return httpx.Response(404)

    budget = BudgetManager(max_requests=35)

    async def execute():
        pipeline = ResearchPipeline(repo, budget)
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()

    outcome = asyncio.run(execute())
    branches = [fact for fact in outcome.facts if fact.field == "branch"]
    assert {fact.item_key for fact in branches} == ({FIRST, SECOND} if second_status == 200 else {FIRST})
    assert all(fact.value["parent_orgnr"] == ORG for fact in branches)
    assert all(fact.value["municipality"] == "OSLO" for fact in branches)  # Physical, not postal.
    assert outcome.coverage["locations"] == "found"
    assert budget.requests.total_used == len(requests)
    assert all("127.0.0.1" not in request for request in requests)
    profile = repo.get_result(run.run_id, ORG)
    evidence = {item.evidence_id: item for item in profile.evidence}
    for branch in branches:
        source, body = repo.read_capture(branch.source_id)
        assert branch.retrieved_at == source.retrieved_at
        locator = evidence[branch.evidence_id].locator
        assert locator.pointer == "/_embedded/underenheter/0"
        assert json.loads(body)["_embedded"]["underenheter"][0] == locator.raw_value
    attempts = [item for item in profile.refresh_outcomes if item.family == "locations"]
    assert len(attempts) == 2
    assert all(item.completeness == ("complete" if second_status == 200 else "partial") for item in attempts)
    assert [item.state for item in attempts] == [
        "available", "available" if second_status == 200 else "blocked",
    ]
    repo.close()


@pytest.mark.parametrize("problem", ["foreign_parent", "missing_parent", "invalid_id"])
def test_subunit_subject_must_come_from_record_not_target_or_query(tmp_path, monkeypatch, problem):
    bad = unit(FIRST)
    if problem == "foreign_parent":
        bad["overordnetEnhet"] = SECOND
    elif problem == "missing_parent":
        del bad["overordnetEnhet"]
    else:
        bad["organisasjonsnummer"] = "123456789"
    result, repo, _ = collect(tmp_path, monkeypatch, [page(0, [bad], total=1, pages=1)])
    assert result.facts == []
    assert result.rejected and result.completeness != "complete"
    assert repo.read_capture(result.sources[0].source_id)[1]
    repo.close()


def collect(tmp_path, monkeypatch, responses, max_requests=10):
    monkeypatch.setattr("nordtrace.core.config.settings.brreg_branch_page_size", 1)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    repo = Repository(tmp_path / "adapter.db")
    budget = BudgetManager(max_requests=max_requests)
    requests = []

    def respond(request):
        requests.append(str(request.url))
        number = int(request.url.params.get("page", "0"))
        response = responses[number]
        return httpx.Response(response) if isinstance(response, int) else httpx.Response(200, json=response)

    async def execute():
        gateway = RequestGateway(budget, repository=repo)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await BrregAdapter(gateway, budget).fetch_underenheter(ORG, "fixture")
        finally:
            await gateway.aclose()

    return asyncio.run(execute()), repo, requests


@pytest.mark.parametrize("limit", [1, 10])
def test_partial_collection_keeps_supported_first_page_without_claiming_completeness(
    tmp_path, monkeypatch, limit,
):
    result, repo, requests = collect(tmp_path, monkeypatch, [page(0, [unit(FIRST)]), 403], limit)
    assert len(result.facts) == 1
    assert result.completeness == "partial"
    assert result.state == "blocked"
    assert len(requests) == (1 if limit == 1 else 2)
    ledger = FactLedger(repository=repo)
    for source in result.sources:
        ledger.add_source(source)
    for evidence in result.evidence:
        ledger.add_evidence(evidence)
    for fact in result.facts:
        ledger.add_fact(fact)
    assert len(ledger.published_facts()) == 1
    repo.close()


@pytest.mark.parametrize("tamper", ["value", "item", "scope", "locator", "endpoint", "port"])
def test_publication_rechecks_subunit_record_subject_and_attributes(tmp_path, monkeypatch, tamper):
    result, repo, _ = collect(tmp_path, monkeypatch, [page(0, [unit(FIRST)], total=1, pages=1)])
    source = result.sources[0]
    evidence = result.evidence[0].model_copy(deep=True)
    fact = result.facts[0].model_copy(deep=True)
    if tamper == "value":
        fact.value["municipality"] = "BERGEN"
    elif tamper == "item":
        fact.item_key = SECOND
    elif tamper == "scope":
        fact.subject_scope = "group"
    elif tamper == "locator":
        evidence.locator.normalization = "identity"
    else:
        # Even internally consistent captures cannot give an unrelated endpoint registry semantics.
        body = repo.read_capture(source.source_id)[1]
        url = (source.url.replace("data.brreg.no", "data.brreg.no:8443")
               if tamper == "port" else "https://data.brreg.no/unrelated")
        source = source.model_copy(update={
            "source_id": "wrong-endpoint", "url": url, "requested_url": url, "final_url": url,
        })
        repo.save_capture(source, body)
        fact.source_id = evidence.source_id = source.source_id
    ledger = FactLedger(repository=repo)
    ledger.add_fact(fact, evidence, source)
    assert ledger.published_facts() == []
    repo.close()


@pytest.mark.parametrize("problem", [
    "missing_page", "boolean_pages", "impossible_count", "empty_address_list",
])
def test_schema_or_pagination_ambiguity_cannot_claim_complete_collection(tmp_path, monkeypatch, problem):
    document = page(0, [unit(FIRST)], total=1, pages=1)
    if problem == "missing_page":
        del document["page"]
    elif problem == "boolean_pages":
        document["page"]["totalPages"] = True
    elif problem == "impossible_count":
        document["page"]["totalPages"] = 0
    else:
        document["_embedded"]["underenheter"][0]["beliggenhetsadresse"] = []
    result, repo, _ = collect(tmp_path, monkeypatch, [document])
    assert result.completeness != "complete"
    repo.close()


def test_explicit_empty_collection_has_complete_unavailable_state(tmp_path, monkeypatch):
    result, repo, _ = collect(tmp_path, monkeypatch, [page(0, [], total=0, pages=0)])
    assert result.facts == [] and result.completeness == "complete" and result.state == "not_available"
    repo.close()


def test_response_cannot_expand_the_configured_record_bound(tmp_path, monkeypatch):
    document = page(0, [unit(FIRST), unit(SECOND)], total=2, pages=1)
    document["page"]["size"] = 2
    result, repo, _ = collect(tmp_path, monkeypatch, [document])  # Requested size remains 1.
    assert result.completeness != "complete"
    assert result.facts == []
    repo.close()

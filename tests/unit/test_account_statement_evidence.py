"""Authored statement-metadata fixtures; no monetary accuracy or live profile claim."""
import asyncio
import json
from copy import deepcopy

import httpx
import pytest

from nordtrace.adapters.brreg import BrregAdapter
from nordtrace.core.budget import BudgetManager
from nordtrace.core.ledger import FactLedger
from nordtrace.core.repository import Repository
from nordtrace.core.request_gateway import RequestGateway

ORG = "982463718"
RECORD = {
    "id": 120, "journalnr": "2026123456", "virksomhet": {"organisasjonsnummer": ORG},
    "regnskapstype": "SELSKAP", "valuta": "EUR",
    "regnskapsperiode": {"fraDato": "2025-01-01", "tilDato": "2025-12-31"},
    "resultatregnskapResultat": {"aarsresultat": 123},
}


def acquire(repo, monkeypatch, payload):
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    async def execute():
        gateway = RequestGateway(BudgetManager(max_requests=1), repository=repo)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload, headers={"content-type": "application/json"})))
        try:
            return await BrregAdapter(gateway, gateway.budget).fetch_accounts(ORG, "metadata-fixture")
        finally:
            await gateway.aclose()

    return asyncio.run(execute())


def publish(repo, evidence, facts, source):
    ledger = FactLedger(repo)
    ledger.add_source(source)
    for item in evidence:
        ledger.add_evidence(item)
    for fact in facts:
        ledger.add_fact(fact)
    return ledger


def test_exact_statement_metadata_publishes_but_amount_does_not(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "capture.db")
    try:
        evidence, facts, source, _ = acquire(repo, monkeypatch, [RECORD])
        ledger = publish(repo, evidence, facts, source)
        statements = ledger.published_facts()
        assert len(statements) == 1 and statements[0].category == "accounting_filings"
        fact = statements[0]
        assert fact.field == "statement" and fact.item_key == "120"
        assert fact.subject_scope == "legal_entity"
        assert fact.value == {
            "record_id": "120", "journal_number": "2026123456", "currency": "EUR",
            "period_start": "2025-01-01", "period_end": "2025-12-31", "accounting_scope": "legal_entity",
        }
        ev = ledger.evidence[fact.evidence_id]
        assert ev.locator.pointer == "/0/id" and ev.locator.raw_value == 120
        assert ev.entity_match_details["extraction_rule"] == "brreg-statement-metadata-v1"
        assert "amount" not in fact.value and repo.read_capture(source.source_id)[1]
        assert all(entry.fact.status == "FAILED" for entry in ledger.all_entries()
                   if entry.fact.category == "financials")
    finally:
        repo.close()


@pytest.mark.parametrize("change", [
    {"id": True}, {"id": 0}, {"id": 2147483648}, {"id": "120"},
    {"valuta": None}, {"regnskapstype": "KONSERN"},
    {"virksomhet": {"organisasjonsnummer": "958973306"}},
    {"regnskapsperiode": {"fraDato": "2025-12-31", "tilDato": "2025-01-01"}},
])
def test_unresolved_or_foreign_statement_does_not_publish_metadata(tmp_path, monkeypatch, change):
    repo = Repository(tmp_path / "bad.db")
    try:
        evidence, facts, source, _ = acquire(repo, monkeypatch, [{**RECORD, **change}])
        assert not publish(repo, evidence, facts, source).published_facts()
    finally:
        repo.close()


def test_competing_filings_are_distinct_records_without_choosing_an_amendment(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "versions.db")
    try:
        later_id = {**RECORD, "id": 999, "journalnr": "different"}
        evidence, facts, source, status = acquire(repo, monkeypatch, [RECORD, later_id])
        published = publish(repo, evidence, facts, source).published_facts()
        assert {f.item_key for f in published} == {"120", "999"}
        assert all(f.category == "accounting_filings" for f in published)
        assert status == "ambiguous"  # No inferred latest/amended monetary statement.
    finally:
        repo.close()


@pytest.mark.parametrize("mutation", [
    "value", "scope", "pointer", "source", "no-repository", "supporting-pointers", "item-key",
    "amount-in-metadata", "rule", "raw-id-bool", "mirror-capture", "query-capture", "wrong-id-endpoint",
    "content-type", "missing-snapshot",
])
def test_statement_support_is_rechecked_from_capture(tmp_path, monkeypatch, mutation):
    repo = Repository(tmp_path / "tamper.db")
    try:
        evidence, facts, source, _ = acquire(repo, monkeypatch, [RECORD])
        fact = next(f for f in facts if f.category == "accounting_filings")
        ev = next(e for e in evidence if e.evidence_id == fact.evidence_id)
        fact, ev, source = deepcopy(fact), deepcopy(ev), deepcopy(source)
        if mutation == "value":
            fact.value["currency"] = "NOK"
        elif mutation == "scope":
            fact.subject_scope = "group"
        elif mutation == "pointer":
            ev.locator.pointer = "/0/resultatregnskapResultat/aarsresultat"
        elif mutation == "source":
            source.url = source.requested_url = source.final_url = "https://mirror.example/accounts"
            # Acquisition metadata disagreement is itself sufficient rejection.
        elif mutation == "supporting-pointers":
            ev.entity_match_details["supporting_pointers"]["currency"] = "/0/id"
        elif mutation == "item-key":
            fact.item_key = "999"
        elif mutation == "amount-in-metadata":
            fact.value["revenue"] = 999999999
        elif mutation == "rule":
            ev.entity_match_details["extraction_rule"] = "unknown"
        elif mutation == "raw-id-bool":
            ev.locator.raw_value = True
        elif mutation == "missing-snapshot":
            repo.conn.execute("DELETE FROM source_captures WHERE source_id=?", (source.source_id,))
        elif mutation in ("mirror-capture", "query-capture", "wrong-id-endpoint", "content-type"):
            _, body = repo.read_capture(source.source_id)
            if mutation == "mirror-capture":
                source.url = "https://mirror.example/accounts"
            elif mutation == "query-capture":
                source.url += "?orgnr=958973306"
            elif mutation == "wrong-id-endpoint":
                source.url += "/999"
            else:
                source.content_type = "text/plain"
            source.requested_url = source.final_url = source.url
            source.source_id = "fixture-" + mutation
            fact.source_id = ev.source_id = source.source_id
            repo.save_capture(source, body)
        ledger = FactLedger(None if mutation == "no-repository" else repo)
        assert ledger.add_fact(fact, ev, source).status == "FAILED"
    finally:
        repo.close()


@pytest.mark.parametrize("other", [
    {**RECORD, "valuta": "NOK"},
    {**RECORD, "virksomhet": {"organisasjonsnummer": "958973306"}},
    {**RECORD, "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"}},
])
def test_same_id_cannot_bind_competing_subject_or_accounting_metadata(tmp_path, monkeypatch, other):
    repo = Repository(tmp_path / "conflicting-id.db")
    try:
        evidence, facts, source, _ = acquire(repo, monkeypatch, [RECORD, other])
        assert not publish(repo, evidence, facts, source).published_facts()
    finally:
        repo.close()


def test_repeated_identical_record_has_one_logical_metadata_claim(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "duplicate.db")
    try:
        evidence, facts, source, _ = acquire(repo, monkeypatch, [RECORD, deepcopy(RECORD)])
        assert len(publish(repo, evidence, facts, source).published_facts()) == 1
    finally:
        repo.close()


def test_pipeline_metadata_history_api_and_export_do_not_inflate_monetary_coverage(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from fastapi.testclient import TestClient

    from nordtrace.api.app import app
    from nordtrace.cli import cli
    from nordtrace.core.contracts import batch_payload, write_json_atomic
    from nordtrace.core.models import ResearchRun
    from nordtrace.engine.pipeline import ResearchPipeline

    repo = Repository(tmp_path / "pipeline.db")
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    monkeypatch.setattr("nordtrace.api.app.get_repo", lambda: repo)
    monkeypatch.setattr("nordtrace.cli._repo", lambda: Repository(tmp_path / "pipeline.db"))
    previous = None
    cases = [[RECORD], [RECORD], [RECORD, {**RECORD, "id": 121, "journalnr": "second"}], None]
    try:
        for records in cases:
            run = ResearchRun(companies=[ORG])
            repo.create_run(run)
            inputs = [{"index": 0, "supplied": ORG, "result_key": ORG}]
            repo.save_run_inputs(run.run_id, inputs)

            def respond(request, records=records):
                if request.url.path.endswith("/enheter/" + ORG):
                    return httpx.Response(200, json={
                        "organisasjonsnummer": ORG, "navn": "METADATA FIXTURE AS",
                    })
                if "/regnskap/" in request.url.path:
                    return httpx.Response(503) if records is None else httpx.Response(
                        200, json=records, headers={"content-type": "application/json"})
                return httpx.Response(404)

            async def execute(run_id=run.run_id, handler=respond):
                pipeline = ResearchPipeline(repo, BudgetManager(max_requests=30))
                pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
                try:
                    return await pipeline.research_company(ORG, run_id)
                finally:
                    await pipeline.aclose()

            outcome = asyncio.run(execute())
            assert outcome.error is None
            profile = repo.get_result(run.run_id, ORG)
            assert profile.coverage["financials"] == ("failed" if records is None else "ambiguous")
            assert not any(f.category == "financials" for f in profile.facts + profile.last_known)
            statements = [f for f in profile.facts if f.category == "accounting_filings"]
            if records is not None:
                assert len(statements) == len(records)
                assert "Accounts record" in profile.summary
                assert f"[{statements[0].claim_id}]" in profile.summary
                assert "annual result EUR 123" not in profile.summary
            else:
                assert len([f for f in profile.last_known if f.category == "accounting_filings"]) == 2
                assert not any(c.change_type == "RETRACTED" for c in profile.changes)
            with TestClient(app) as client:
                response = client.get(f"/companies/{ORG}?run_id={run.run_id}")
                assert response.json() == profile.model_dump(mode="json")
                if statements:
                    response = client.get(
                        f"/companies/{ORG}/evidence/{statements[0].evidence_id}?run_id={run.run_id}")
                    assert response.status_code == 200 and response.json()["snapshot"]["verified"]
                    assert response.json()["evidence"]["entity_match_details"]["supporting_pointers"][
                        "currency"] in ("/0/valuta", "/1/valuta")
            output = tmp_path / (run.run_id + ".json")
            write_json_atomic(output, batch_payload(run, [profile], inputs))
            assert json.loads(output.read_text())["results"][0] == profile.model_dump(mode="json")
            bundle = tmp_path / (run.run_id + ".zip")
            exported = CliRunner().invoke(cli, ["export-run", run.run_id, "--output", str(bundle)])
            assert exported.exit_code == 0, exported.output
            verified = CliRunner().invoke(cli, ["verify-bundle", str(bundle)])
            assert verified.exit_code == 0, verified.output
            assert json.loads(verified.output)["completion"]["result_count"] == 1
            if previous is not None:
                assert repo.get_result(previous.run_id, ORG) == previous
                if records == [RECORD]:
                    assert {f.claim_id for f in statements} == {
                        f.claim_id for f in previous.facts if f.category == "accounting_filings"}
                    assert not any(c.category == "accounting_filings" and c.change_type != "UNCHANGED"
                                   for c in profile.changes)
            previous = profile
    finally:
        repo.close()

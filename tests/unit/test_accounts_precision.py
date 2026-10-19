"""Original exact-number oracles; no live or independently adjudicated accounts."""
import asyncio
import json

import httpx
import pytest

from nordtrace.adapters.brreg import BrregAdapter
from nordtrace.core.budget import BudgetManager
from nordtrace.core.evidence import parse_json_body
from nordtrace.core.repository import Repository
from nordtrace.core.request_gateway import RequestGateway

ORG = "982463718"


def response_bytes(token):
    return (
        '[{"virksomhet":{"organisasjonsnummer":"' + ORG + '"},'
        '"regnskapstype":"SELSKAP","valuta":"EUR",'
        '"regnskapsperiode":{"fraDato":"2025-01-01","tilDato":"2025-12-31"},'
        '"resultatregnskapResultat":{"driftsresultat":{"driftsinntekter":'
        '{"sumDriftsinntekter":' + token + '}}}}]'
    ).encode()


def collect(tmp_path, monkeypatch, body):
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    repo = Repository(tmp_path / "accounts.db")

    async def execute():
        gateway = RequestGateway(BudgetManager(max_requests=1), repository=repo)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=body, headers={"content-type": "application/json"})))
        try:
            return await BrregAdapter(gateway, gateway.budget).fetch_accounts(ORG, "precision")
        finally:
            await gateway.aclose()
    try:
        result = asyncio.run(execute())
        assert repo.read_capture(result[2].source_id)[1] == body
        return result
    finally:
        repo.close()


@pytest.mark.parametrize("token,expected", [
    ("9007199254740993.01", "9007199254740993.01"),
    ("-12345678901234567890.12", "-12345678901234567890.12"),
    ("0", "0"), ("-0.00", "-0.00"), ("1.2300e3", "1230.0"),
])
def test_accounts_preserve_exact_source_number_and_lexeme(tmp_path, monkeypatch, token, expected):
    evidence, facts, source, status = collect(tmp_path, monkeypatch, response_bytes(token))
    assert status == "found"
    claim = next(f for f in facts if f.field == "revenue")
    assert type(claim.value) is str and claim.value == expected
    assert claim.status == "EXTRACTED" and claim.unit is None
    assert claim.currency == "EUR" and claim.reporting_period == "2025-01-01/2025-12-31"
    item = next(ev for ev in evidence if ev.evidence_id == claim.evidence_id)
    assert item.locator is None  # No supported financial locator until units are established.
    assert item.entity_match_details["raw_number_lexeme"] == token
    assert item.entity_match_details["field_pointer"].endswith("/sumDriftsinntekter")
    assert item.entity_match_details["number_representation"] == "json-number-decimal-v1"
    assert item.entity_match_details["unit_scale_basis"] == "unresolved"
    assert item.content_hash == source.content_hash
    assert token in item.evidence_text
    json.dumps(claim.model_dump(mode="json"), allow_nan=False)


@pytest.mark.parametrize("token", [
    "true", "false", '"12.34"', "{}", "[]", "1e1000", "1e-1000", "1e" + "9" * 60,
])
def test_unsupported_monetary_values_do_not_become_candidates(tmp_path, monkeypatch, token):
    evidence, facts, source, status = collect(tmp_path, monkeypatch, response_bytes(token))
    assert not facts and status == "ambiguous"
    assert source.error_detail


def test_generic_json_float_contract_is_unchanged():
    assert type(parse_json_body(b'{"amount":1.25}')["amount"]) is float
    assert type(parse_json_body(b'{"amount":1}')["amount"]) is int


def test_nearby_large_restated_values_cannot_collapse_to_one_latest_record(tmp_path, monkeypatch):
    first = response_bytes("9007199254740993.01")
    second = response_bytes("9007199254740993.02")
    evidence, facts, source, status = collect(tmp_path, monkeypatch, first[:-1] + b"," + second[1:])
    assert status == "ambiguous" and not evidence and not facts
    assert "competing" in source.error_detail


@pytest.mark.parametrize("body", [
    response_bytes("NaN"), response_bytes("Infinity"), response_bytes("1" * 257),
    response_bytes("1").replace(b'"valuta":"EUR"', b'"valuta":"EUR","valuta":"NOK"'),
    response_bytes("1").replace(b'"EUR"', b'"\xff"'),
    b'{"nested":' + b"[" * 65 + b"0" + b"]" * 65 + b"}",
])
def test_exact_decoder_keeps_strict_source_guards(tmp_path, monkeypatch, body):
    evidence, facts, source, status = collect(tmp_path, monkeypatch, body)
    assert status == "failed" and not evidence and not facts
    assert "accounts JSON rejected" in source.error_detail


def test_unqualified_accounts_cannot_publish_in_an_in_memory_ledger(tmp_path, monkeypatch):
    from nordtrace.core.ledger import FactLedger

    evidence, facts, source, _ = collect(tmp_path, monkeypatch, response_bytes("12.34"))
    ledger = FactLedger()
    result = ledger.add_fact(facts[0], evidence[0], source)
    assert result.status == "FAILED"


def test_exact_diagnostics_survive_pipeline_history_and_offline_export(tmp_path, monkeypatch):
    import zipfile

    from fastapi.testclient import TestClient

    from nordtrace.api.app import app
    from nordtrace.core.contracts import batch_payload, write_json_atomic
    from nordtrace.core.export import export_run, verify_bundle
    from nordtrace.core.models import ResearchRun
    from nordtrace.engine.pipeline import ResearchPipeline

    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    repo = Repository(tmp_path / "history.db")
    monkeypatch.setattr("nordtrace.api.app.get_repo", lambda: repo)
    previous = None
    try:
        for token in ("9007199254740993.01", "9007199254740993.02", None):
            run = ResearchRun(companies=[ORG])
            repo.create_run(run)
            inputs = [{"index": 0, "supplied": ORG, "result_key": ORG}]
            repo.save_run_inputs(run.run_id, inputs)

            def respond(request, token=token):
                if request.url.path.endswith("/enheter/" + ORG):
                    return httpx.Response(200, json={
                        "organisasjonsnummer": ORG, "navn": "ORIGINAL FIXTURE AS",
                    })
                if "/regnskap/" in request.url.path:
                    return httpx.Response(503) if token is None else httpx.Response(
                        200, content=response_bytes(token), headers={"content-type": "application/json"})
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
            assert not any(f.category == "financials" for f in profile.facts + profile.last_known)
            assert not any(change.category == "financials" for change in profile.changes)
            assert profile.coverage["financials"] == ("failed" if token is None else "ambiguous")
            if token is not None:
                diagnostic = next(e for e in profile.evidence
                                  if "raw_number_lexeme" in e.entity_match_details)
                assert diagnostic.entity_match_details["raw_number_lexeme"] == token
                assert repo.get_evidence(diagnostic.evidence_id) == diagnostic
                assert token not in (profile.summary or "")
            if previous is not None:
                assert repo.get_result(previous.run_id, ORG) == previous
            previous = profile
            with TestClient(app) as client:
                response = client.get(f"/companies/{ORG}?run_id={run.run_id}")
                assert response.status_code == 200
                assert response.json() == profile.model_dump(mode="json")
            path = tmp_path / (run.run_id + ".json")
            write_json_atomic(path, batch_payload(run, [profile], inputs))
            assert json.loads(path.read_text())["results"][0] == profile.model_dump(mode="json")
            bundle = tmp_path / (run.run_id + ".zip")
            export_run(repo, run.run_id, bundle)
            assert verify_bundle(bundle)["completion"]["result_count"] == 1
            with zipfile.ZipFile(bundle) as archive:
                exported = json.loads(archive.read("results.jsonl"))
                assert exported == profile.model_dump(mode="json")
    finally:
        repo.close()

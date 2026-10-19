"""Authored registry-shaped amounts (D-086); no live accuracy or held-out claim."""
import asyncio
import json
import zipfile
from copy import deepcopy

import httpx
import pytest

from nordtrace.adapters.brreg import BrregAdapter
from nordtrace.core.budget import BudgetManager
from nordtrace.core.ledger import FactLedger
from nordtrace.core.models import JsonNumberLocator
from nordtrace.core.repository import Repository
from nordtrace.core.request_gateway import RequestGateway

ORG = "982463718"
REVENUE = "/0/resultatregnskapResultat/driftsresultat/driftsinntekter/sumDriftsinntekter"


def record(record_id=120, year=2025, **changes):
    value = {
        "id": record_id, "journalnr": f"{year}000{record_id}", "virksomhet": {"organisasjonsnummer": ORG},
        "regnskapstype": "SELSKAP", "valuta": "NOK", "avviklingsregnskap": False,
        "regnskapsperiode": {"fraDato": f"{year}-01-01", "tilDato": f"{year}-12-31"},
        "resultatregnskapResultat": {
            "aarsresultat": -12.5,
            "driftsresultat": {"driftsresultat": 0.0, "driftsinntekter": {"sumDriftsinntekter": 882017.0}},
        },
        "eiendeler": {"sumEiendeler": 9007199254740993},
        "egenkapitalGjeld": {"egenkapital": {"sumEgenkapital": -0.0}, "gjeldOversikt": {"sumGjeld": 1.5E3}},
    }
    value.update(changes)
    return value


def acquire(repo, monkeypatch, body, content_type="application/json"):
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    if not isinstance(body, bytes):
        body = json.dumps(body).encode()

    async def execute():
        gateway = RequestGateway(BudgetManager(max_requests=1), repository=repo)
        gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=body, headers={"content-type": content_type})))
        try:
            return await BrregAdapter(gateway, gateway.budget).fetch_accounts(ORG, "amount-fixture")
        finally:
            await gateway.aclose()

    return asyncio.run(execute())


def published_amounts(repo, monkeypatch, body):
    evidence, facts, source, status = acquire(repo, monkeypatch, body)
    ledger = FactLedger(repo)
    ledger.add_source(source)
    for item in evidence:
        ledger.add_evidence(item)
    for fact in facts:
        ledger.add_fact(fact)
    return [f for f in ledger.published_facts() if f.category == "financials"], ledger, status


def test_supported_amounts_publish_exact_values_with_every_qualifier(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "amounts.db")
    try:
        # Raw bytes keep lexemes exact: the large integer exceeds binary float precision.
        body = json.dumps([record()]).replace("1500.0", "1.5E3").encode()
        assert b"9007199254740993" in body and b"1.5E3" in body
        amounts, ledger, status = published_amounts(repo, monkeypatch, body)
        values = {f.field: f.value for f in amounts}
        assert status == "found"
        assert values == {
            "total_operating_revenue": "882017", "operating_result": "0", "annual_result": "-12.5",
            "total_assets": "9007199254740993", "equity": "0", "total_liabilities": "1500",
        }
        revenue = next(f for f in amounts if f.field == "total_operating_revenue")
        assert (revenue.currency, revenue.unit, revenue.subject_scope, revenue.item_key) == (
            "NOK", "currency_unit_x1", "legal_entity", None)
        assert (revenue.reporting_period, revenue.valid_from, revenue.valid_to) == (
            "2025-01-01/2025-12-31", "2025-01-01", "2025-12-31")
        locator = ledger.evidence[revenue.evidence_id].locator
        assert isinstance(locator, JsonNumberLocator)
        assert (locator.pointer, locator.raw_value, locator.record_pointer, locator.record_id) == (
            REVENUE, "882017.0", "/0", "120")
        assert (locator.multiplier, locator.unit_basis) == ("1", "rr0002-denomination-normalized-at-receipt")
        lexemes = {ledger.evidence[f.evidence_id].locator.raw_value for f in amounts}
        assert {"-12.5", "-0.0", "1.5E3", "9007199254740993"} <= lexemes
        display = json.loads(ledger.evidence[revenue.evidence_id].evidence_text)
        assert display["journal_number"] == "2025000120" and display["accounting_scope"] == "legal_entity"
        assert all(not isinstance(f.value, float) for f in amounts)
    finally:
        repo.close()


def test_non_nok_currency_is_carried_from_the_statement_not_assumed(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "eur.db")
    try:
        amounts, _, _ = published_amounts(repo, monkeypatch, [record(valuta="EUR")])
        assert amounts and {f.currency for f in amounts} == {"EUR"}
    finally:
        repo.close()


@pytest.mark.parametrize("change", [
    {"avviklingsregnskap": True}, {"avviklingsregnskap": None}, "drop-avviklingsregnskap",
    {"valuta": None}, {"valuta": "nok"}, {"regnskapstype": "KONSERN"}, {"regnskapstype": None},
    {"virksomhet": {"organisasjonsnummer": "958973306"}}, {"id": True}, {"id": "120"},
    {"regnskapsperiode": {"fraDato": "2025-01-01"}},
    {"regnskapsperiode": {"fraDato": "2025-12-31", "tilDato": "2025-01-01"}},
    {"regnskapsperiode": {"fraDato": "20250101", "tilDato": "2025-12-31"}},
])
def test_unresolved_basis_scope_subject_or_period_withholds_all_amounts(tmp_path, monkeypatch, change):
    repo = Repository(tmp_path / "unresolved.db")
    try:
        value = record()
        if change == "drop-avviklingsregnskap":
            value.pop("avviklingsregnskap")
        else:
            value.update(change)
        amounts, ledger, _ = published_amounts(repo, monkeypatch, [value])
        assert amounts == []
        assert not any(isinstance(e.locator, JsonNumberLocator) for e in ledger.evidence.values())
    finally:
        repo.close()


@pytest.mark.parametrize("token", ["true", "\"882017\"", "null", "{}", "[1]"])
def test_non_number_field_values_never_become_amounts(tmp_path, monkeypatch, token):
    repo = Repository(tmp_path / "types.db")
    try:
        body = json.dumps([record()]).replace("882017.0", token).encode()
        amounts, _, _ = published_amounts(repo, monkeypatch, body)
        assert "total_operating_revenue" not in {f.field for f in amounts}
        assert "annual_result" in {f.field for f in amounts}
    finally:
        repo.close()


def test_competing_records_for_one_period_abstain_without_blocking_other_periods(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "competing.db")
    try:
        restated = record(record_id=999)
        restated["resultatregnskapResultat"]["aarsresultat"] = 40
        body = [record(record_id=120), restated, record(record_id=77, year=2024)]
        amounts, _, status = published_amounts(repo, monkeypatch, body)
        assert status == "found" and amounts
        assert {f.reporting_period for f in amounts} == {"2024-01-01/2024-12-31"}
        _, _, source, _ = acquire(Repository(tmp_path / "detail.db"), monkeypatch, body)
        assert "2 legal-entity statement record(s) withheld" in source.error_detail
    finally:
        repo.close()


def test_unplaceable_subject_record_withholds_every_period(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "unplaceable.db")
    try:
        amounts, _, _ = published_amounts(repo, monkeypatch, [
            record(), record(record_id=5, year=2024, regnskapsperiode={"fraDato": "2024-01-01"})])
        assert amounts == []
    finally:
        repo.close()


def test_group_records_and_foreign_records_do_not_compete_with_legal_entity(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "scopes.db")
    try:
        body = [record(record_id=1, regnskapstype="KONSERN"),
                record(record_id=2, virksomhet={"organisasjonsnummer": "958973306"}), record(record_id=3)]
        amounts, ledger, _ = published_amounts(repo, monkeypatch, body)
        assert amounts and all(ledger.evidence[f.evidence_id].locator.record_id == "3" for f in amounts)
    finally:
        repo.close()


def test_identical_duplicate_representation_is_one_claim_per_predicate(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "duplicate.db")
    try:
        amounts, _, _ = published_amounts(repo, monkeypatch, [record(), record()])
        assert len(amounts) == 6 and len({f.claim_id for f in amounts}) == 6
    finally:
        repo.close()


@pytest.mark.parametrize("mutation", [
    "value", "currency", "unit", "period", "scope", "item-key", "field", "pointer", "raw-lexeme",
    "record-id", "record-pointer", "display", "rule", "no-repository", "missing-snapshot",
    "mirror-capture", "wrong-id-endpoint", "content-type", "float-value", "statement-category",
])
def test_amount_support_is_rechecked_against_the_retained_capture(tmp_path, monkeypatch, mutation):
    repo = Repository(tmp_path / "tamper.db")
    try:
        evidence, facts, source, _ = acquire(repo, monkeypatch, [record()])
        fact = deepcopy(next(f for f in facts if f.field == "total_operating_revenue"))
        ev = deepcopy(next(e for e in evidence if e.evidence_id == fact.evidence_id))
        source = deepcopy(source)
        assert FactLedger(repo).add_fact(deepcopy(fact), deepcopy(ev), deepcopy(source)).status == "PUBLISHED"
        if mutation == "value":
            fact.value = fact.normalized_value = "882018"
        elif mutation == "currency":
            fact.currency = "EUR"
        elif mutation == "unit":
            fact.unit = "thousands"
        elif mutation == "period":
            fact.reporting_period = "2024-01-01/2024-12-31"
        elif mutation == "scope":
            fact.subject_scope = "group"
        elif mutation == "item-key":
            fact.item_key = "120"
        elif mutation == "field":
            fact.field = "operating_result"
        elif mutation == "pointer":
            ev.locator.pointer = "/0/resultatregnskapResultat/aarsresultat"
        elif mutation == "raw-lexeme":
            ev.locator.raw_value = "882017"
        elif mutation == "record-id":
            ev.locator.record_id = "121"
        elif mutation == "record-pointer":
            ev.locator.record_pointer = ""
        elif mutation == "display":
            ev.evidence_text = ev.evidence_text.replace("NOK", "EUR")
        elif mutation == "rule":
            ev.entity_match_details["extraction_rule"] = "brreg-statement-metadata-v1"
        elif mutation == "missing-snapshot":
            repo.conn.execute("DELETE FROM source_captures WHERE source_id=?", (source.source_id,))
        elif mutation == "float-value":
            fact.value = fact.normalized_value = 882017.0
        elif mutation == "statement-category":
            fact.category = "accounting_filings"
        elif mutation in ("mirror-capture", "wrong-id-endpoint", "content-type"):
            _, body = repo.read_capture(source.source_id)
            if mutation == "mirror-capture":
                source.url = "https://mirror.example/regnskapsregisteret/regnskap/" + ORG
            elif mutation == "wrong-id-endpoint":
                source.url += "/121"
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


def test_number_locator_requires_schema_1_3_and_rejects_float_raw_values():
    from pydantic import ValidationError

    from nordtrace.core.models import CompanyProfile, EvidenceRecord

    locator = JsonNumberLocator(pointer=REVENUE, raw_value="882017.0", record_pointer="/0", record_id="120")
    evidence = EvidenceRecord(source_id="s", locator=locator)
    for version in ("1.1", "1.2"):
        with pytest.raises(ValidationError, match="requires result schema_version 1.3"):
            CompanyProfile(schema_version=version, run_id="r", organisation_number=ORG, evidence=[evidence])
    assert CompanyProfile(schema_version="1.3", run_id="r", organisation_number=ORG, evidence=[evidence])
    for bad in ({"raw_value": 882017.0}, {"raw_value": "NaN"}, {"raw_value": "1e"}, {"multiplier": "1000"},
                {"record_id": "0"}, {"pointer": "/0/../x"}):
        with pytest.raises(ValidationError):
            JsonNumberLocator(**({"pointer": REVENUE, "raw_value": "1", "record_pointer": "/0",
                                  "record_id": "120"} | bad))


def test_pipeline_refresh_history_interfaces_and_bundle_preserve_exact_amounts(tmp_path, monkeypatch):
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
    restated = record()
    restated["resultatregnskapResultat"]["aarsresultat"] = -12.25
    cases = [
        ("first", [record()]), ("same-snapshot", [record()]), ("restated", [restated]),
        ("new-period", [restated, record(record_id=300, year=2026)]), ("outage", None),
    ]
    history = []
    try:
        for label, records in cases:
            run = ResearchRun(companies=[ORG])
            repo.create_run(run)
            inputs = [{"index": 0, "supplied": ORG, "result_key": ORG}]
            repo.save_run_inputs(run.run_id, inputs)

            def respond(request, records=records):
                if request.url.path.endswith("/enheter/" + ORG):
                    return httpx.Response(200, json={"organisasjonsnummer": ORG, "navn": "AMOUNT FIXTURE AS"})
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

            assert asyncio.run(execute()).error is None
            profile = repo.get_result(run.run_id, ORG)
            amounts = {(f.field, f.reporting_period): f for f in profile.facts if f.category == "financials"}
            changes = {(c.field, c.reporting_period): c.change_type for c in profile.changes
                       if c.category == "financials"}
            p2025 = ("annual_result", "2025-01-01/2025-12-31")
            if label == "outage":
                assert profile.coverage["financials"] == "failed" and not amounts
                kept = [f for f in profile.last_known if f.category == "financials"]
                assert len(kept) == 12 and not any(v == "RETRACTED" for v in changes.values())
                assert profile.schema_version == "1.3"
            else:
                assert profile.coverage["financials"] == "found" and profile.schema_version == "1.3"
                assert "total operating revenue NOK 882 017 (unit: whole currency units; " in profile.summary
                shown = max(key[1] for key in amounts if key[0] == "total_operating_revenue")
                assert f"[{amounts[('total_operating_revenue', shown)].claim_id}]" in profile.summary
                assert not any(isinstance(f.value, float) for f in amounts.values())
            if label == "first":
                assert amounts[p2025].value == "-12.5" and changes[p2025] == "NEW"
            elif label == "same-snapshot":
                assert set(changes.values()) == {"UNCHANGED"}
                assert {f.claim_id for f in amounts.values()} == {
                    f.claim_id for f in history[0].facts if f.category == "financials"}
            elif label == "restated":
                assert amounts[p2025].value == "-12.25" and changes[p2025] == "CHANGED"
                assert {v for k, v in changes.items() if k != p2025} == {"UNCHANGED"}
            elif label == "new-period":
                assert changes[("annual_result", "2026-01-01/2026-12-31")] == "NEW"
                assert changes[p2025] == "UNCHANGED" and len(amounts) == 12
                assert "period: 2026-01-01/2026-12-31" in profile.summary
            with TestClient(app) as client:
                response = client.get(f"/companies/{ORG}?run_id={run.run_id}")
                assert response.json() == profile.model_dump(mode="json")
                if amounts:
                    fact = amounts[p2025]
                    view = client.get(f"/companies/{ORG}/evidence/{fact.evidence_id}?run_id={run.run_id}")
                    assert view.status_code == 200 and view.json()["snapshot"]["verified"]
                    assert view.json()["evidence"]["locator"]["kind"] == "json_number"
            output = tmp_path / (run.run_id + ".json")
            write_json_atomic(output, batch_payload(run, [profile], inputs))
            batch = json.loads(output.read_text(encoding="utf-8"))
            assert batch["schema_version"] == "1.3" and batch["results"][0] == profile.model_dump(mode="json")
            bundle = tmp_path / (run.run_id + ".zip")
            exported = CliRunner().invoke(cli, ["export-run", run.run_id, "--output", str(bundle)])
            assert exported.exit_code == 0, exported.output
            verified = CliRunner().invoke(cli, ["verify-bundle", str(bundle)])
            assert verified.exit_code == 0, verified.output
            with zipfile.ZipFile(bundle) as archive:
                assert json.loads(archive.read("manifest.json"))["result_schema"] == "nordtrace-1.3"
                line = archive.read("results.jsonl").decode()
                assert '"value":"-12.5"' in line or '"value":"-12.25"' in line
                claims = json.loads(archive.read("starter-example.jsonl"))["claims"]
                assert any(c["field"] == "annual_result" and isinstance(c["value"], str) for c in claims) or (
                    label == "outage")
            for earlier in history:
                assert repo.get_result(earlier.run_id, ORG) == earlier
            history.append(profile)
    finally:
        repo.close()


def test_declared_older_bundle_schema_cannot_carry_amount_results(tmp_path, monkeypatch):
    from nordtrace.core.export import export_run, result_schema, verify_bundle
    from nordtrace.core.models import ResearchRun
    from nordtrace.engine.pipeline import ResearchPipeline

    repo = Repository(tmp_path / "bundle.db")
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])
    run = ResearchRun(companies=[ORG])
    repo.create_run(run)
    repo.save_run_inputs(run.run_id, [{"index": 0, "supplied": ORG, "result_key": ORG}])

    def respond(request):
        if request.url.path.endswith("/enheter/" + ORG):
            return httpx.Response(200, json={"organisasjonsnummer": ORG, "navn": "AMOUNT FIXTURE AS"})
        if "/regnskap/" in request.url.path:
            return httpx.Response(200, json=[record()], headers={"content-type": "application/json"})
        return httpx.Response(404)

    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=30))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            await pipeline.research_company(ORG, run.run_id)
        finally:
            await pipeline.aclose()

    try:
        asyncio.run(execute())
        bundle = tmp_path / "amounts.zip"
        export_run(repo, run.run_id, bundle)
        forged = tmp_path / "forged.zip"
        with zipfile.ZipFile(bundle) as source, zipfile.ZipFile(forged, "w") as target:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == "result-schema.json":
                    data = (json.dumps(result_schema("1.2"), ensure_ascii=False, separators=(",", ":"))
                            + "\n").encode()
                    schema_bytes = data
                target.writestr(item.filename, data)
            manifest = json.loads(source.read("manifest.json"))
        import hashlib
        manifest["result_schema"] = "nordtrace-1.2"
        manifest["schema_sha256"] = hashlib.sha256(schema_bytes).hexdigest()
        rewritten = tmp_path / "forged-manifest.zip"
        with zipfile.ZipFile(forged) as source, zipfile.ZipFile(rewritten, "w") as target:
            for item in source.infolist():
                data = json.dumps(manifest).encode() if item.filename == "manifest.json" else source.read(
                    item.filename)
                target.writestr(item.filename, data)
        verify_bundle(bundle)
        with pytest.raises(ValueError, match="exceeds declared bundle schema"):
            verify_bundle(rewritten)
    finally:
        repo.close()

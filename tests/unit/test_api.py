import json
import tempfile
import pathlib
import pytest
from fastapi.testclient import TestClient

from nordtrace.api.app import app, get_repo
from nordtrace.core.config import settings
from nordtrace.core.repository import Repository
from nordtrace.core.models import (
    CompanyIdentity, EvidenceRecord, Fact, SourceRecord, utcnow,
)


@pytest.fixture()
def client(tmp_path):
    settings.database_path = str(tmp_path / "api.db")
    repo = Repository(settings.database_path)
    # seed run row first (FK target)
    from nordtrace.core.models import ResearchRun
    run = ResearchRun(run_id="run_seed", started_at=utcnow().isoformat(), companies=["982463718"])
    repo.create_run(run)
    # seed a company + facts
    ident = CompanyIdentity(organisation_number="982463718", legal_name="TELENOR ASA",
                            organisation_form="ASA", status="active",
                            registered_address="Snarøyveien 30 1360 FORNEBU", municipality="BÆRUM",
                            industry_code="61.100", industry_description="Telekommunikasjon",
                            website="https://www.telenor.no/", registration_date="2000-10-06")
    repo.upsert_company(ident, "run_seed")
    src = SourceRecord(source_id="src_seed", url="https://data.brreg.no/enheter/982463718",
                       domain="data.brreg.no", source_type="registry", authority_tier=0,
                       access_status="success", http_status=200, content_hash="h",
                       org_number="982463718", retrieved_at=utcnow().isoformat())
    repo.insert_sources_bulk([src], "run_seed", "982463718")
    ev = EvidenceRecord(source_id="src_seed", url=src.url, source_title="Brreg",
                        source_type="registry", authority_tier=0, evidence_text="TELENOR ASA navn",
                        entity_verdict="VERIFIED", org_number="982463718", retrieved_at=utcnow().isoformat())
    repo.insert_evidence(ev)
    for i, (fld, val) in enumerate([("legal_name", "TELENOR ASA"), ("status", "active"),
                                    ("industry_code", "61.100"), ("revenue", 678000000.0)]):
        cat = "identity" if i < 3 else "financials"
        f = Fact(org_number="982463718", category=cat, field=fld, value=val,
                 normalized_value=str(val), source_id="src_seed", evidence_id=ev.evidence_id,
                 entity_verdict="VERIFIED", status="PUBLISHED", fact_confidence=0.99,
                 retrieved_at=utcnow().isoformat(), run_id="run_seed",
                 currency="NOK" if cat == "financials" else None)
        repo.insert_fact(f)
    with TestClient(app) as c:
        yield c


def test_root(client):
    assert client.get("/").status_code == 200
    assert client.get("/").json()["service"] == "NordTrace"


def test_health(client):
    assert client.get("/health").json() == {"ok": True}


def test_company_payload(client):
    r = client.get("/companies/982463718")
    assert r.status_code == 200
    d = r.json()
    assert d["company"]["legal_name"] == "TELENOR ASA"
    assert len(d["facts"]) == 4
    assert d["coverage"]["identity"] == "found"
    assert d["coverage"]["financials"] == "found"


def test_company_facts_endpoint(client):
    r = client.get("/companies/982463718/facts")
    assert r.status_code == 200
    assert len(r.json()["facts"]) >= 4


def test_company_sources_endpoint(client):
    r = client.get("/companies/982463718/sources")
    assert r.status_code == 200
    assert len(r.json()["sources"]) >= 1


def test_company_changes_endpoint_empty(client):
    r = client.get("/companies/982463718/changes")
    assert r.status_code == 200
    assert r.json()["changes"] == []


def test_unknown_company_404(client):
    assert client.get("/companies/999999999").status_code == 404


def test_malformed_orgnr_422(client):
    assert client.get("/companies/123").status_code == 422
    assert client.get("/companies/abcdefghi").status_code == 422


def test_research_invalid_orgnr_422(client):
    r = client.post("/research", json={"organisation_number": "12345"})
    assert r.status_code == 422
    assert "invalid" in r.json()["detail"]


def test_research_unknown_orgnr_404(client):
    """Valid checksum, unregistered → run completes with terminal state, company 404."""
    r = client.post("/research", json={"organisation_number": "999999999"})
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    import time
    for _ in range(120):
        rr = client.get(f"/research/{run_id}")
        if rr.json().get("state") in ("completed", "failed"):
            break
        time.sleep(0.5)
    assert rr.json().get("state") == "completed"
    # unregistered company → not_found terminal state
    states = rr.json()["company_states"]
    assert states.get("999999999") in ("not_available", "failed")


def test_unknown_run_404(client):
    assert client.get("/research/run_doesnotexist").status_code == 404
    assert client.get("/runs/run_doesnotexist/trace").status_code == 404


def test_run_status_endpoint(client):
    r = client.get("/run-status")
    assert r.status_code == 200
    assert "budgets" in r.json()


def test_dashboard_served(client):
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "NordTrace" in r.text


def test_fact_dedupe_no_duplicate_slots(client):
    """Duplicate facts across runs collapse to latest per slot."""
    # insert a duplicate fact with a newer timestamp
    repo = get_repo()
    from nordtrace.core.models import ResearchRun
    repo.create_run(ResearchRun(run_id="run_seed2", started_at=utcnow().isoformat(), companies=["982463718"]))
    src = repo.get_sources("982463718")[0]
    ev = repo.evidence_for_company("982463718")[0]
    f = Fact(org_number="982463718", category="identity", field="legal_name", value="TELENOR ASA",
             normalized_value="TELENOR ASA", source_id=src.source_id, evidence_id=ev.evidence_id,
             entity_verdict="VERIFIED", status="PUBLISHED", retrieved_at=utcnow().isoformat(),
             run_id="run_seed2")
    repo.insert_fact(f)
    r = client.get("/companies/982463718")
    facts = r.json()["facts"]
    slots = [f"{f['category']}|{f['field']}|{f['reporting_period']}" for f in facts]
    assert len(slots) == len(set(slots))

import hashlib
import json

import pytest

from nordtrace.core.changes import detect_changes
from nordtrace.core.ledger import FactLedger
from nordtrace.core.models import EvidenceRecord, Fact, FactStatus, JsonPointerLocator, SourceRecord, utcnow
from nordtrace.core.repository import Repository


@pytest.fixture
def retained_registry(tmp_path):
    """Exercise ledger mechanics with real retained/located registry support."""
    repo = Repository(tmp_path / "ledger.db")
    ledger = FactLedger(repo)

    def observe(value, field="employee_count"):
        key = "antallAnsatte" if field == "employee_count" else "navn"
        document = {"organisasjonsnummer": "982463718", key: value}
        body = json.dumps(document).encode()
        source = SourceRecord(
            url="https://data.brreg.no/enhetsregisteret/api/enheter/982463718",
            source_type="registry", authority_tier=0, org_number="982463718",
            access_status="success", http_status=200, retrieved_at=utcnow().isoformat(),
            content_hash=hashlib.sha256(body).hexdigest(), snapshot_representation="http-response-body-v1",
        )
        repo.save_capture(source, body)
        evidence = EvidenceRecord(
            source_id=source.source_id, source_type="registry", authority_tier=0,
            org_number="982463718", entity_verdict="VERIFIED", content_hash=source.content_hash,
            retrieved_at=source.retrieved_at, evidence_text=json.dumps(value),
            locator=JsonPointerLocator(pointer="/" + key, raw_value=value),
        )
        fact = Fact(
            org_number="982463718", category="identity", field=field, value=value, normalized_value=value,
            subject_scope="legal_entity", source_id=source.source_id, evidence_id=evidence.evidence_id,
            entity_verdict="VERIFIED", retrieved_at=source.retrieved_at,
        )
        return ledger.add_fact(fact, evidence, source)

    try:
        yield ledger, observe
    finally:
        repo.close()


def make_src(src_id="s1", org="982463718", status="success"):
    return SourceRecord(
        source_id=src_id,
        url=f"https://brreg.no/{src_id}",
        access_status=status,
        source_type="registry",
        org_number=org,
        content_hash=f"h-{src_id}",
    )


def make_ev(ev_id="e1", src_id="s1", org="982463718", text="Revenue 100 and equity 999 NOK FY2024"):
    return EvidenceRecord(
        source_id=src_id, evidence_id=ev_id, org_number=org, evidence_text=text, entity_verdict="VERIFIED"
    )


def make_fact(
    org="982463718",
    cat="financials",
    fld="revenue",
    val=100,
    src="s1",
    ev="e1",
    status=None,
    retrieved=None,
    period="FY2024",
    entity="VERIFIED",
):
    return Fact(
        org_number=org,
        category=cat,
        field=fld,
        value=val,
        normalized_value=val if not isinstance(val, str) else val,
        currency="NOK" if cat == "financials" else None,
        reporting_period=period,
        source_id=src,
        evidence_id=ev,
        entity_verdict=entity,
        status=status or FactStatus.PUBLISHED.value,
        retrieved_at=retrieved or utcnow().isoformat(),
    )


# --- citation validation ---
def test_valid_citation_publishes(retained_registry):
    _, observe = retained_registry
    f = observe(100)
    assert f.status == FactStatus.PUBLISHED.value


def test_missing_evidence_fails():
    led = FactLedger()
    led.add_source(make_src())
    f = led.add_fact(make_fact(ev="missing"))
    assert f.status == FactStatus.FAILED.value
    assert "evidence" in f.conflict_note


def test_unretrieved_source_fails():
    led = FactLedger()
    led.add_source(make_src(status="failed"))
    led.add_evidence(make_ev())
    f = led.add_fact(make_fact())
    assert f.status == FactStatus.FAILED.value


def test_rejected_entity_fails():
    led = FactLedger()
    led.add_source(make_src())
    led.add_evidence(make_ev())
    f = led.add_fact(make_fact(entity="REJECTED"))
    assert f.status == FactStatus.FAILED.value


def test_null_value_fails():
    led = FactLedger()
    led.add_source(make_src())
    led.add_evidence(make_ev())
    f = led.add_fact(make_fact(val=None))
    assert f.status in (FactStatus.FAILED.value, FactStatus.NOT_AVAILABLE.value)


def test_financial_missing_currency_fails():
    led = FactLedger()
    led.add_source(make_src())
    led.add_evidence(make_ev())
    f = make_fact()
    f.currency = None
    f2 = led.add_fact(f)
    assert f2.status == FactStatus.FAILED.value


def test_evidence_from_other_source_fails():
    led = FactLedger()
    led.add_source(make_src("s1"))
    led.add_source(make_src("s2"))
    led.add_evidence(make_ev("e1", "s2"))
    f = led.add_fact(make_fact(src="s1", ev="e1"))
    assert f.status == FactStatus.FAILED.value


# --- conflict detection ---
def test_conflict_detected_same_slot_different_value(retained_registry):
    _, observe = retained_registry
    observe(100)
    f2 = observe(999)
    assert f2.status == FactStatus.CONFLICT.value
    assert "conflict" in f2.conflict_note.lower()


def test_no_conflict_same_value(retained_registry):
    _, observe = retained_registry
    observe(100)
    f2 = observe(100)
    assert f2.status == FactStatus.PUBLISHED.value


def test_no_conflict_different_slots(retained_registry):
    _, observe = retained_registry
    observe(100)
    f2 = observe("FIXTURE AS", field="legal_name")
    assert f2.status == FactStatus.PUBLISHED.value


# --- temporal ---
def test_temporal_view_orders_by_period():
    led = FactLedger()
    led.add_source(make_src())
    led.add_evidence(make_ev())
    led.add_fact(make_fact(cat="leadership", fld="role:CEO", val="New", period="FY2025"))
    led.add_fact(make_fact(cat="leadership", fld="role:CEO", val="Old", period="FY2024"))
    view = led.temporal_view("982463718", "role:CEO")
    assert [f.normalized_value for f in view] == ["Old", "New"]  # sorted by period


def test_temporal_facts_not_merged():
    led = FactLedger()
    led.add_source(make_src())
    led.add_evidence(make_ev())
    f24 = led.add_fact(make_fact(cat="leadership", fld="role:CEO", val="Old", period="FY2024"))
    f25 = led.add_fact(make_fact(cat="leadership", fld="role:CEO", val="New", period="FY2025"))
    # different periods are different slots: no conflict
    assert f24.status == FactStatus.PUBLISHED.value
    assert f25.status == FactStatus.PUBLISHED.value


# --- source unavailable on refresh ---
def test_mark_source_unavailable(retained_registry):
    led, observe = retained_registry
    fact = observe(100)
    n = led.mark_source_unavailable("982463718", fact.source_id)
    assert n == 1
    facts = led.all_entries()
    assert facts[0].fact.status == FactStatus.SOURCE_UNAVAILABLE.value


# --- change detection ---
def test_change_detection_changed():
    prev = [make_fact(val=100, retrieved="2026-01-01")]
    curr = [make_fact(val=120, retrieved="2026-02-01")]
    changes = detect_changes("982463718", "run2", prev, curr)
    ch = [c for c in changes if c.change_type == "CHANGED"]
    assert len(ch) == 1
    assert ch[0].previous_value == 100 and ch[0].current_value == 120


def test_change_detection_unchanged():
    prev = [make_fact(val=100, retrieved="2026-01-01")]
    curr = [make_fact(val=100, retrieved="2026-02-01")]
    changes = detect_changes("982463718", "run2", prev, curr)
    assert any(c.change_type == "UNCHANGED" for c in changes)


def test_change_detection_new():
    prev = []
    curr = [make_fact(val=100, retrieved="2026-02-01")]
    changes = detect_changes("982463718", "run2", prev, curr)
    assert any(c.change_type == "NEW" for c in changes)


def test_change_detection_missing_observation_is_unconfirmed():
    prev = [make_fact(val=100, retrieved="2026-01-01")]
    curr = []
    changes = detect_changes("982463718", "run2", prev, curr)
    assert [c.change_type for c in changes] == ["SOURCE_UNAVAILABLE"]


def test_change_detection_ceo_change():
    prev = [make_fact(cat="leadership", fld="role:CEO", val="A", retrieved="2026-01-01")]
    curr = [make_fact(cat="leadership", fld="role:CEO", val="B", retrieved="2026-02-01")]
    changes = detect_changes("982463718", "run2", prev, curr)
    ch = [c for c in changes if c.change_type == "CHANGED"]
    assert len(ch) == 1 and ch[0].previous_value == "A" and ch[0].current_value == "B"


def test_change_detection_temporal_periods_separate():
    prev = [make_fact(cat="leadership", fld="role:CEO", val="Old", period="FY2024", retrieved="2026-01-01")]
    curr = [make_fact(cat="leadership", fld="role:CEO", val="New", period="FY2025", retrieved="2026-02-01")]
    changes = detect_changes("982463718", "run2", prev, curr)
    types = {c.reporting_period: c.change_type for c in changes}
    assert types.get("FY2024") == "SOURCE_UNAVAILABLE"
    assert types.get("FY2025") == "NEW"


def test_change_detection_carries_sources():
    prev = [make_fact(val=100, src="s_old", retrieved="2026-01-01")]
    curr = [make_fact(val=120, src="s_new", retrieved="2026-02-01")]
    changes = detect_changes("982463718", "run2", prev, curr)
    ch = [c for c in changes if c.change_type == "CHANGED"][0]
    assert ch.previous_source_id == "s_old" and ch.current_source_id == "s_new"

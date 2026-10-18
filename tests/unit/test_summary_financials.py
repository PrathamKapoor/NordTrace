"""Legacy template safeguards only: financial production support stays withheld."""
from decimal import Decimal

import pytest

from nordtrace.core.ledger import FactLedger
from nordtrace.core.models import ChangeRecord, CompanyIdentity, Coverage, EvidenceRecord, Fact, SourceRecord
from nordtrace.core.synthesis import build_summary

ORG = "982463718"


def add_candidate(ledger, field="revenue", value=Decimal("1234.56"), **qualifiers):
    # Real production rejects these unlocated financial candidates. This legacy
    # in-memory ledger exercises the downstream template without mocking it.
    source = SourceRecord(access_status="success", org_number=ORG)
    evidence = EvidenceRecord(source_id=source.source_id, org_number=ORG,
                              entity_verdict="VERIFIED",
                              evidence_text=f"EUR NOK {value}; reporting years 2024 and 2025")
    fields = {"currency": "EUR", "unit": "units", "reporting_period": "2025",
              "subject_scope": "legal_entity"}
    fields.update(qualifiers)
    fact = Fact(org_number=ORG, category="financials", field=field, value=value,
                source_id=source.source_id, evidence_id=evidence.evidence_id,
                entity_verdict="VERIFIED", **fields)
    ledger.add_fact(fact, evidence, source)
    assert fact in ledger.published_facts(ORG)
    assert fact.status == "PUBLISHED"
    return fact


def render(ledger):
    return build_summary(CompanyIdentity(organisation_number=ORG, legal_name="FIXTURE AS"), ledger,
                         Coverage(states={"financials": "found"}), [])


@pytest.mark.parametrize("value,expected", [
    (1234.56, "1 234.56"),
    (0, "0"),
    (-1234.56, "-1 234.56"),
    (Decimal("9007199254740993.01"), "9 007 199 254 740 993.01"),
    ("1234.567890123456789", "1 234.567890123456789"),
    (Decimal("0.00"), "0.00"),
])
def test_monetary_text_preserves_exact_normalized_value_and_qualifiers(value, expected):
    ledger = FactLedger()
    fact = add_candidate(ledger, value=value)
    text = render(ledger)
    assert f"revenue EUR {expected} (unit: units; period: 2025; legal entity) [{fact.claim_id}]" in text


def test_each_financial_observation_keeps_its_own_period_unit_currency_and_scope():
    ledger = FactLedger()
    revenue = add_candidate(ledger, value=1000, unit="thousands")
    result = add_candidate(ledger, field="annual_result", value=-20.25, currency="NOK",
                           unit="millions", reporting_period="2024", subject_scope="group")
    text = render(ledger)
    assert f"revenue EUR 1 000 (unit: thousands; period: 2025; legal entity) [{revenue.claim_id}]" in text
    assert f"annual result NOK -20.25 (unit: millions; period: 2024; group) [{result.claim_id}]" in text
    assert "Financials (2025)" not in text


@pytest.mark.parametrize("qualifiers", [{"unit": None}, {"unit": ""}, {"subject_scope": "unknown"}])
def test_template_does_not_display_monetary_candidates_with_unresolved_qualifiers(qualifiers):
    ledger = FactLedger()
    fact = add_candidate(ledger, **qualifiers)
    text = render(ledger)
    assert f"[{fact.claim_id}]" not in text
    assert "revenue EUR" not in text
    assert "Financials: monetary values could not be safely rendered." in text


def test_unresolved_financial_candidate_does_not_hide_the_qualified_observation():
    ledger = FactLedger()
    add_candidate(ledger, field="revenue", unit=None)
    result = add_candidate(ledger, field="annual_result", value=0)
    text = render(ledger)
    assert f"annual result EUR 0 (unit: units; period: 2025; legal entity) [{result.claim_id}]" in text
    assert "Some monetary observations could not be safely rendered and are withheld." in text


@pytest.mark.parametrize("kind", ["NEW", "CHANGED", "RETRACTED"])
def test_financial_change_text_does_not_publish_unqualified_or_truncated_amounts(kind):
    ledger = FactLedger()
    current = "11112222333344445555666677778888999900001111222233.45"
    fact = add_candidate(ledger, value=current)
    changes = [ChangeRecord(org_number=ORG, run_id="new", category="financials", field="revenue",
                            change_type=kind, claim_id=fact.claim_id,
                            previous_value="98765432109876543210987654321098765432109876543210.12",
                            current_value="11112222333344445555666677778888999900001111222233.45")]
    text = build_summary(CompanyIdentity(organisation_number=ORG, legal_name="FIXTURE AS"),
                         ledger, Coverage(), changes, previous_run_id="old")
    assert "9876543210" not in text and "1111222233" not in text
    expected = f"revenue: {kind.lower()} monetary observation; inspect qualified evidence [{fact.claim_id}]"
    assert expected in text


def test_oversized_fixed_point_amount_is_withheld_without_allocating_a_huge_brief():
    ledger = FactLedger()
    fact = add_candidate(ledger, value=10 ** 300)
    text = render(ledger)
    assert f"[{fact.claim_id}]" not in text
    assert "Financials: monetary values could not be safely rendered." in text
    assert len(text) < 2000

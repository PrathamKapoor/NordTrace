"""Regression gates; full snapshot/table support is a separate release requirement."""

import pytest

from nordtrace.core.ledger import FactLedger, _quoted_number
from nordtrace.core.models import EvidenceRecord, Fact, SourceRecord


def ledger_with_quote(quote, verdict="VERIFIED"):
    ledger = FactLedger()
    ledger.add_source(SourceRecord(source_id="s", access_status="success", org_number="982463718"))
    ledger.add_evidence(EvidenceRecord(
        evidence_id="e", source_id="s", org_number="982463718",
        evidence_text=quote, entity_verdict=verdict,
    ))
    return ledger


def revenue(value=999999999, period="FY2025"):
    return Fact(
        org_number="982463718", category="financials", field="revenue", value=value,
        currency="NOK", reporting_period=period, source_id="s", evidence_id="e", entity_verdict="VERIFIED",
    )


@pytest.mark.parametrize("verdict", ["VERIFIED", "REJECTED"])
def test_filing_notice_does_not_support_invented_revenue(verdict):
    result = ledger_with_quote("Annual accounts filed", verdict).add_fact(revenue())
    assert result.status == "FAILED"


def test_claim_cannot_upgrade_likely_evidence_to_verified():
    result = ledger_with_quote("Revenue 100 NOK FY2025", "LIKELY").add_fact(revenue(100))
    assert result.status == "FAILED"


def test_financial_claim_without_reporting_period_is_withheld():
    result = ledger_with_quote("Revenue 100 NOK").add_fact(revenue(100, period=None))
    assert result.status == "FAILED"


def test_value_substring_does_not_support_a_different_numeric_value():
    assert not _quoted_number(999999999, "Revenue 1999999999 NOK FY2025")
    result = ledger_with_quote("Revenue 1999999999 NOK FY2025").add_fact(revenue())
    assert result.status == "FAILED"


@pytest.mark.parametrize("value,quote", [
    (0, "Revenue 0 NOK FY2025"),
    (-100, "Revenue -100 NOK FY2025"),
])
def test_explicit_zero_and_negative_values_are_preserved(value, quote):
    assert _quoted_number(value, quote)
    result = ledger_with_quote(quote).add_fact(revenue(value))
    assert result.status == "FAILED"  # A quote alone establishes no retained financial support.
    assert result.value == value


@pytest.mark.parametrize("value,quote", [
    (0, "Revenue 100 000 NOK FY2025"),
    (100, "Revenue (100) NOK FY2025"),
])
def test_numeric_group_or_negative_parentheses_cannot_support_wrong_value(value, quote):
    assert not _quoted_number(value, quote)
    assert ledger_with_quote(quote).add_fact(revenue(value)).status == "FAILED"


def test_negative_parentheses_preserve_the_sign():
    assert _quoted_number(-100, "Revenue (100) NOK FY2025")
    assert ledger_with_quote("Revenue (100) NOK FY2025").add_fact(revenue(-100)).status == "FAILED"

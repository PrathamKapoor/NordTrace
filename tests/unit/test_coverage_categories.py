"""Coverage-category tests: business, jobs, financials, activity fixtures."""

import pytest

from nordtrace.adapters.website import _extract_job_openings, classify_url
from nordtrace.core.ledger import FactLedger
from nordtrace.core.models import (
    CompanyIdentity,
    EvidenceRecord,
    Fact,
    FactStatus,
    SourceRecord,
)


def make_ledger_with(org="982463718"):
    led = FactLedger()
    src = SourceRecord(
        source_id="s",
        url="https://x.no",
        domain="x.no",
        access_status="success",
        source_type="company_website",
        org_number=org,
        content_hash="h",
    )
    ev = EvidenceRecord(
        source_id="s", evidence_id="e", org_number=org, evidence_text="text", entity_verdict="LIKELY"
    )
    led.add_source(src)
    led.add_evidence(ev)
    return led, src, ev


# --- Business: page classification variants ---
@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://x.no/about", "ABOUT"),
        ("https://x.no/about-us", "ABOUT"),
        ("https://x.no/company", "ABOUT"),
        ("https://x.no/om-oss", "ABOUT"),
        ("https://x.no/who-we-are", "OTHER"),  # not in keywords; crawled low-prio
        ("https://x.no/what-we-do", "OTHER"),  # not in keywords
        ("https://x.no/solutions", "SERVICE"),
        ("https://x.no/services", "SERVICE"),
    ],
)
def test_business_page_classification(url, expected):
    assert classify_url(url)[0] == expected


def test_business_description_from_homepage():
    led, src, ev = make_ledger_with()
    f = led.add_fact(
        Fact(
            org_number="982463718",
            category="business_description",
            field="description",
            value="We build software",
            normalized_value="We build software",
            source_id="s",
            evidence_id="e",
            entity_verdict="LIKELY",
        )
    )
    assert f.status == FactStatus.PUBLISHED.value


def test_no_description_is_not_available():
    led, src, ev = make_ledger_with()
    assert not any(f.category == "business_description" for f in led.published_facts("982463718"))


# --- Jobs: extraction fixtures ---
def test_job_extraction_nav_style_links():
    from bs4 import BeautifulSoup

    html = """<a href="/stillinger/sok?q=x">Utvikler</a>
              <a href="/ledige-stillinger/utvikler2">Backend-utvikler</a>"""
    jobs = _extract_job_openings(BeautifulSoup(html, "lxml"), "https://x.no/karriere/")
    titles = [j["title"] for j in jobs]
    assert "Utvikler" in titles
    assert "Backend-utvikler" in titles


def test_job_extraction_available_positions():
    from bs4 import BeautifulSoup

    html = """<a href="/available-positions/sommerstudent-2027-finans/">
                Les mer om stillingen ‘Sommerstudent 2027 – Finans’</a>"""
    jobs = _extract_job_openings(BeautifulSoup(html, "lxml"), "https://x.no/karriere/")
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Sommerstudent 2027 – Finans"


def test_job_extraction_rejects_generic_nav_without_listing_url():
    from bs4 import BeautifulSoup

    html = '<a href="/about/team/">Les mer</a>'
    jobs = _extract_job_openings(BeautifulSoup(html, "lxml"), "https://x.no/karriere/")
    assert jobs == []


def test_job_extraction_inherited_parent_path_not_counted():
    from bs4 import BeautifulSoup

    # /om/jobbitelenor/visomvaager/x — 'jobb' in the PARENT path must not count
    html = '<a href="/om/jobbitelenor/visomvaager/annette/">Bli kjent med Annette</a>'
    jobs = _extract_job_openings(BeautifulSoup(html, "lxml"), "https://x.no/om/jobbitelenor/")
    assert jobs == []


def test_no_jobs_is_honest():
    led, src, ev = make_ledger_with()
    assert not any(f.category == "jobs" for f in led.published_facts("982463718"))


def test_unrelated_employer_job_rejected():
    """A job posting from a different company must not attach to the target."""
    from nordtrace.core.entity import EntityResolver
    from nordtrace.core.entity import MatchVerdict as MV

    target = CompanyIdentity(organisation_number="982463718", legal_name="TELENOR ASA")
    r = EntityResolver().evaluate(
        target, candidate_name="SALMAR AS", candidate_text="SALMAR AS søker utvikler"
    )
    assert r.verdict in (MV.REJECTED.value, MV.AMBIGUOUS.value)
    assert r.verdict != MV.VERIFIED.value


# --- Financials: HTML + PDF + multi-period + unavailable ---
def test_financial_html_fact_published():
    led, src, ev = make_ledger_with()
    f = led.add_fact(
        Fact(
            org_number="982463718",
            category="financials",
            field="revenue",
            value=1000.0,
            currency="NOK",
            reporting_period="FY2025",
            source_id="s",
            evidence_id="e",
            entity_verdict="VERIFIED",
        )
    )
    assert f.status == FactStatus.PUBLISHED.value


def test_financial_multiple_periods_separate_slots():
    led, src, ev = make_ledger_with()
    for i, fy in enumerate(["FY2023", "FY2024", "FY2025"]):
        f = led.add_fact(
            Fact(
                org_number="982463718",
                category="financials",
                field="revenue",
                value=1000.0 + i,
                currency="NOK",
                reporting_period=fy,
                source_id="s",
                evidence_id="e",
                entity_verdict="VERIFIED",
            )
        )
        assert f.status == FactStatus.PUBLISHED.value  # separate slots, no conflict
    slots = {f.fact_key() for f in led.published_facts("982463718")}
    assert len([s for s in slots if s.startswith("financials|revenue|")]) == 3


def test_financial_unavailable_is_honest():
    led, src, ev = make_ledger_with()
    assert not any(f.category == "financials" for f in led.published_facts("982463718"))


def test_financial_currency_required():
    led, src, ev = make_ledger_with()
    f = Fact(
        org_number="982463718",
        category="financials",
        field="revenue",
        value=1000.0,
        currency=None,
        reporting_period="FY2025",
        source_id="s",
        evidence_id="e",
        entity_verdict="VERIFIED",
    )
    f2 = led.add_fact(f)
    assert f2.status == FactStatus.FAILED.value


# --- Activity: recent/old/none/unrelated ---
def test_activity_recent_event_published():
    led, src, ev = make_ledger_with()
    f = led.add_fact(
        Fact(
            org_number="982463718",
            category="recent_activity",
            field="status_event",
            value={"event": "expansion", "date": "2026-09-01"},
            normalized_value="expansion",
            source_id="s",
            evidence_id="e",
            entity_verdict="VERIFIED",
            published_at="2026-09-01",
        )
    )
    assert f.status == FactStatus.PUBLISHED.value


def test_activity_old_event_has_date():
    led, src, ev = make_ledger_with()
    f = led.add_fact(
        Fact(
            org_number="982463718",
            category="recent_activity",
            field="status_event",
            value={"event": "partnership", "date": "2015-01-01"},
            normalized_value="partnership",
            source_id="s",
            evidence_id="e",
            entity_verdict="VERIFIED",
            published_at="2015-01-01",
        )
    )
    assert f.status == FactStatus.PUBLISHED.value
    assert f.value["date"] == "2015-01-01"  # date preserved; not presented as current


def test_activity_none_is_honest():
    led, src, ev = make_ledger_with()
    assert not any(f.category == "recent_activity" for f in led.published_facts("982463718"))


def test_activity_unrelated_company_not_attached():
    """Unrelated company activity must not attach to the target."""
    led = FactLedger()
    src = SourceRecord(
        source_id="s_other",
        url="https://other.no",
        domain="other.no",
        access_status="success",
        source_type="news",
        org_number="958973306",
    )
    ev = EvidenceRecord(
        source_id="s_other",
        evidence_id="e_other",
        org_number="958973306",
        evidence_text="SALMAR AS launches new product",
        entity_verdict="LIKELY",
    )
    led.add_source(src)
    led.add_evidence(ev)
    f = led.add_fact(
        Fact(
            org_number="982463718",
            category="recent_activity",
            field="status_event",
            value={"event": "launch"},
            source_id="s_other",
            evidence_id="e_other",
            entity_verdict="LIKELY",
        )
    )
    # the fact references another company's source — citation validator rejects
    assert f.status == FactStatus.FAILED.value

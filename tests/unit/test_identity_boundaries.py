"""Synthetic hard negatives; no claim of independently adjudicated live accuracy."""

import pytest

from nordtrace.adapters.website import WebsiteAdapter
from nordtrace.core.budget import BudgetManager
from nordtrace.core.entity import EntityResolver, extract_orgnrs, name_similarity, registrable_domain
from nordtrace.core.models import CompanyIdentity
from nordtrace.core.orgnr import validate_orgnr

TARGET = CompanyIdentity(
    organisation_number="982463718", legal_name="TELENOR ASA",
    website="https://www.telenor.no", municipality="BÆRUM",
    registered_address="Snarøyveien 30 1360 FORNEBU",
)


@pytest.mark.parametrize("text", [
    "TELENOR ASA. Operated by Other AS, orgnr 958973306.",
    "TELENOR ASA orgnr 982463718. Operator orgnr 958 973 306.",
])
def test_homepage_name_or_target_id_cannot_override_contradictory_operator(text):
    adapter = WebsiteAdapter(None, BudgetManager(), EntityResolver())
    accepted, reason = adapter.verify_site_homepage(TARGET, text, "https://www.telenor.no")
    assert not accepted, reason


def test_name_and_registered_domain_without_legal_attachment_remains_ambiguous():
    adapter = WebsiteAdapter(None, BudgetManager(), EntityResolver())
    accepted, reason = adapter.verify_site_homepage(TARGET, "Welcome to TELENOR ASA", TARGET.website)
    assert not accepted, reason


@pytest.mark.parametrize("raw", ["NO 982 463 718 MVA", "982.463.718 MVA", "NO982463718MVA"])
def test_vat_labels_preserve_valid_identity(raw):
    parsed = validate_orgnr(raw)
    assert parsed.valid
    assert parsed.value == "982463718"


def test_grouped_source_identifiers_are_checksum_checked():
    assert extract_orgnrs("Org.nr. 982 463 718 MVA; ref 123456789") == ["982463718"]


def test_incidental_financial_number_is_not_an_identity_contradiction():
    result = EntityResolver().evaluate(
        TARGET, candidate_orgnr="982463718", candidate_name="TELENOR ASA",
        candidate_text="Revenue in NOK: 958973306.",
    )
    assert result.verdict == "VERIFIED"
    assert not result.signals.orgnr_contradiction


def test_explicit_customer_mention_is_not_document_operator():
    result = EntityResolver().evaluate(
        TARGET, candidate_orgnr="982463718", candidate_name="TELENOR ASA",
        candidate_text="TELENOR ASA orgnr 982463718. Our customer SALMAR AS orgnr 958973306.",
    )
    assert result.verdict == "VERIFIED"


def test_target_digits_inside_longer_number_do_not_verify_identity():
    result = EntityResolver().evaluate(TARGET, candidate_text="Reference 19824637180")
    assert result.verdict != "VERIFIED"


def test_name_substring_does_not_create_token_match():
    assert name_similarity("SOLAR AS", "SOLARIS AS") == 0


@pytest.mark.parametrize("hostname,expected", [
    ("news.example.co.uk", "example.co.uk"),
    ("www.example.no", "example.no"),
    ("first.github.io", "first.github.io"),
])
def test_registrable_domain_uses_offline_public_suffix_data(hostname, expected):
    assert registrable_domain(hostname) == expected


def test_shared_domain_can_have_two_independently_identified_entities():
    resolver = EntityResolver()
    resolver.register_verified_domain("shared.no", "958973306")
    result = resolver.evaluate(TARGET, candidate_orgnr="982463718", candidate_url="https://shared.no")
    assert result.verdict == "VERIFIED"
    resolver.register_verified_domain("shared.no", "982463718")
    assert resolver.known_domains["shared.no"] == {"958973306", "982463718"}


def test_crawl_preserves_footer_identifiers_for_attachment_check():
    import asyncio
    from types import SimpleNamespace

    from nordtrace.core.models import SourceRecord

    html = "<main>TELENOR ASA orgnr 982463718</main><footer>Operator orgnr 958 973 306</footer>"

    class CapturedGateway:
        async def fetch(self, url, **kwargs):
            return SourceRecord(url=url, access_status="success", source_type="company_website")

        def get_content(self, url):
            return SimpleNamespace(text=html)

    adapter = WebsiteAdapter(CapturedGateway(), BudgetManager(), EntityResolver())
    evidence, facts, sources, rejected, coverage = asyncio.run(adapter.crawl(TARGET, "fixture"))
    assert facts == []
    assert all("foreign organisation number" in item["reason"] for item in rejected)


def test_registrable_domain_rejects_whole_url_at_its_boundary():
    with pytest.raises(ValueError, match="hostname"):
        registrable_domain("https://news.example.co.uk/path")

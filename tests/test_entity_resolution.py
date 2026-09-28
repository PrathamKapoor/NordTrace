import pytest
from nordtrace.core.entity import EntityResolver, PublicationFirewall
from nordtrace.core.models import CompanyIdentity, Source


def test_exact_org_number_match():
    identity = CompanyIdentity(
        organisation_number="912345678",
        legal_name="Test AS",
        organisation_form="AS",
    )
    resolver = EntityResolver()
    assert resolver.match("Organization 912345678", identity) == "VERIFIED"


def test_wrong_company_rejected():
    identity_target = CompanyIdentity(
        organisation_number="912345678",
        legal_name="Test AS",
        organisation_form="AS",
    )
    identity_wrong = CompanyIdentity(
        organisation_number="987654321",
        legal_name="Wrong AB",
        organisation_form="AB",
    )
    firewall = PublicationFirewall()
    source = Source(source_id="test", url="http://example.com", domain="example.com", source_type="search")
    allowed = firewall.allow(source, identity_target, "This page belongs to Wrong AB (987654321)")
    assert allowed is False
    assert len(firewall.rejected_candidates) == 1

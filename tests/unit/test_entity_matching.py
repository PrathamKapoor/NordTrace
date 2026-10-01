import pytest
from nordtrace.core.entity import (
    EntityResolver, PublicationFirewall, normalize_name, name_similarity,
    extract_orgnrs, domain_of, registrable_domain,
)
from nordtrace.core.models import CompanyIdentity, MatchVerdict as MV

T = CompanyIdentity(
    organisation_number="982463718",
    legal_name="TELENOR ASA",
    municipality="BÆRUM",
    website="https://www.telenor.no/",
)


def test_exact_orgnr_verifies():
    assert T.resolver_verdict if False else EntityResolver().evaluate(T, candidate_text="Orgnr 982463718").verdict == MV.VERIFIED.value


def test_foreign_orgnr_in_name_field_rejects():
    r = EntityResolver().evaluate(T, candidate_name="Telenor ASA", candidate_orgnr="987654321")
    assert r.verdict == MV.REJECTED.value
    assert r.signals.foreign_orgnr == "987654321"


def test_foreign_orgnr_in_text_rejects_even_with_name_match():
    r = EntityResolver().evaluate(T, candidate_text="Telenor ASA OrgNr 987654321")
    assert r.verdict == MV.REJECTED.value


def test_two_similar_names_ambiguous_without_corroboration():
    r = EntityResolver().evaluate(T, candidate_name="TELENOR AB", candidate_municipality="STOCKHOLM")
    assert r.verdict in (MV.REJECTED.value, MV.AMBIGUOUS.value)


def test_name_plus_domain_verifies():
    r = EntityResolver().evaluate(T, candidate_name="Telenor Norge AS", candidate_url="https://www.telenor.no/om/")
    assert r.verdict in (MV.VERIFIED.value, MV.LIKELY.value)


def test_name_plus_municipality_likely():
    r = EntityResolver().evaluate(T, candidate_name="Telenor ASA", candidate_municipality="BÆRUM")
    assert r.verdict in (MV.VERIFIED.value, MV.LIKELY.value)


def test_dissimilar_name_rejected():
    r = EntityResolver().evaluate(T, candidate_name="Fjell Fotterapi Laila Fjell")
    assert r.verdict == MV.REJECTED.value


def test_dates_not_mistaken_for_orgnr():
    r = EntityResolver().evaluate(T, candidate_text="Publisert 2024-01-15, tlf 40001234, AS")
    assert not r.signals.orgnr_contradiction


def test_domain_conflict_rejects():
    r = EntityResolver()
    r.register_verified_domain("dnb.no", "984857859")
    res = r.evaluate(T, candidate_name="TELENOR ASA", candidate_url="https://www.dnb.no/x")
    assert res.verdict == MV.REJECTED.value
    assert res.signals.domain_conflict


def test_subsidiary_same_domain_not_auto_verified():
    # TELENOR NORGE AS (different orgnr) on telenor.no subdomain — related but not verified
    r = EntityResolver().evaluate(T, candidate_name="TELENOR NORGE AS", candidate_url="https://sub.telenor.no/")
    assert r.verdict != MV.VERIFIED.value


def test_brand_only_text_not_verified():
    r = EntityResolver().evaluate(T, candidate_text="Telenor is a telecom brand")
    assert r.verdict != MV.VERIFIED.value


def test_parent_vs_subsidiary_not_merged():
    parent = CompanyIdentity(organisation_number="960514718", legal_name="SALMAR ASA")
    sub = CompanyIdentity(organisation_number="958973306", legal_name="SALMAR AS")
    r = EntityResolver()
    # sub evaluated against parent must not auto-verify (no orgnr match)
    res = r.evaluate(parent, candidate_name=sub.legal_name)
    assert res.verdict != MV.VERIFIED.value


def test_normalize_name_strips_legal_suffixes():
    assert normalize_name("ACME ASA") == "acme"
    assert normalize_name("ACME ASA Holding") == "acme holding"
    assert normalize_name("Test NUF") == "test"


def test_normalize_name_keeps_geographic_words():
    assert normalize_name("Telenor Norge AS") == "telenor norge"
    assert normalize_name("Nordic Solutions AS") == "nordic solutions"


def test_extract_orgnrs_dedupes_and_excludes():
    found = extract_orgnrs("Orgnr 982463718 og 982463718", exclude="982463718")
    assert found == []
    found2 = extract_orgnrs("982463718 and 987654321", exclude="982463718")
    assert found2 == ["987654321"]


def test_name_similarity_bounds():
    assert name_similarity("TELENOR ASA", "TELENOR ASA") == 1.0
    assert name_similarity("", "x") == 0.0
    s = name_similarity("Telenor Norge AS", "TELENOR ASA")
    assert 0.0 < s <= 1.0


def test_firewall_rejects_and_records():
    fw = PublicationFirewall()
    res = fw.evaluate_candidate(T, candidate_name="Wrong AB", candidate_orgnr="987654321")
    assert res.verdict == MV.REJECTED.value
    assert not fw.may_publish(res)
    assert len(fw.rejected) == 1
    assert fw.rejected[0]["signals"]["foreign_orgnr"] == "987654321"


def test_firewall_publishes_verified():
    fw = PublicationFirewall()
    res = fw.evaluate_candidate(T, candidate_text="Orgnr 982463718")
    assert fw.may_publish(res)


def test_translated_name_prefer_unknown():
    # An English-style name without corroboration → AMBIGUOUS (unknown), not wrong-company
    r = EntityResolver().evaluate(T, candidate_name="Telenor Norway")
    assert r.verdict in (MV.AMBIGUOUS.value, MV.LIKELY.value)

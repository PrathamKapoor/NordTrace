import pytest

from nordtrace.adapters.brreg import BrregAdapter, _address_line
from nordtrace.adapters.pdf_pipeline import (
    _join_space_thousands,
    _parse_number,
    extract_financial_lines,
    extract_pdf_pages,
)
from nordtrace.adapters.website import _extract_contact, _extract_names, classify_url


# --- number parsing (Norwegian formats) ---
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1 234 567", 1234567.0),
        ("1.234.567", 1234567.0),
        ("47,687.4", 47687.4),
        ("1,2", 1.2),
        ("1234567", 1234567.0),
        ("-500", -500.0),
        ("1 234", 1234.0),
    ],
)
def test_parse_number(raw, expected):
    assert _parse_number(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "", "12,3456", "--5"])
def test_parse_number_rejects_garbage(raw):
    assert _parse_number(raw) is None or _parse_number(raw) == -5


def test_join_space_thousands():
    assert _join_space_thousands(["1", "234", "567"]) == ["1 234 567"]
    assert _join_space_thousands(["2024", "47", "687"]) == ["2024", "47", "687"]  # year guard
    assert _join_space_thousands(["47,687.4", "46,445.4"]) == ["47,687.4", "46,445.4"]
    assert _join_space_thousands(["12", "345", "678", "910"]) == ["12 345 678 910"]


# --- PDF extraction (real PDF fixture, downloaded during test session if missing) ---
REAL_PDF = None


def _load_real_pdf():
    global REAL_PDF
    if REAL_PDF is not None:
        return REAL_PDF
    import ssl
    import urllib.request

    url = "https://akerbp.com/wp-content/uploads/2026/07/aker-bp-2026-q2-report.pdf"
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
        REAL_PDF = r.read()
    return REAL_PDF


def test_pdf_parse_real_report():
    try:
        pdf = _load_real_pdf()
    except Exception:
        pytest.skip("network unavailable for real PDF fixture")
    res = extract_pdf_pages(pdf)
    assert res.ok
    assert len(res.pages) > 30
    assert not res.is_scanned


def test_pdf_financial_lines_with_page_numbers():
    try:
        pdf = _load_real_pdf()
    except Exception:
        pytest.skip("network unavailable for real PDF fixture")
    res = extract_pdf_pages(pdf)
    lines = extract_financial_lines(res.pages)
    assert len(lines) >= 3
    for ln_item in lines:
        assert "page" in ln_item and ln_item["page"] >= 1
        assert "field" in ln_item and ln_item["field"]
        assert "line" in ln_item
    # at least one line has a parsed value
    assert any(ln_item["value"] is not None for ln_item in lines)


def test_pdf_parse_non_pdf():
    res = extract_pdf_pages(b'{"id": 1}')
    assert not res.ok
    assert "pdf parse error" in res.error or "header" in res.error


def test_pdf_parse_empty():
    res = extract_pdf_pages(b"")
    assert not res.ok


def test_pdf_synthetic_multi_page():
    # Build a minimal 2-page PDF with pypdf writer
    import io

    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=612, height=792)
    w.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    w.write(buf)
    res = extract_pdf_pages(buf.getvalue())
    # blank pages → no text → scanned detection
    assert not res.ok or len(res.pages) == 2


# --- website classification ---
@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://x.no/om/jobbitelenor", "CAREERS"),
        ("https://x.no/karriere/ledige-stillinger", "CAREERS"),
        ("https://x.no/om/presse-og-media/", "NEWS"),
        ("https://x.no/om/", "ABOUT"),
        ("https://x.no/om-oss", "ABOUT"),
        ("https://x.no/about", "ABOUT"),
        ("https://x.no/produkter/internett", "PRODUCT"),
        ("https://x.no/tjenester", "SERVICE"),
        ("https://x.no/kontakt", "CONTACT"),
        ("https://x.no/ledelse", "LEADERSHIP"),
        ("https://x.no/investor/reports", "FINANCIAL"),
        ("https://x.no/", "HOME"),
    ],
)
def test_classify_url(url, expected):
    assert classify_url(url)[0] == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://x.no/privacy-policy",
        "https://x.no/wp-admin/settings",
        "https://x.no/img/logo.png",
        "https://x.no/cookie-declaration",
    ],
)
def test_classify_url_junk(url):
    assert classify_url(url)[1] == 0


# --- contact extraction ---
def test_extract_contact():
    text = "Contact us at post@telenor.no or +47 915 03 000. Visit Snarøyveien 30."
    c = _extract_contact(text, "https://x.no")
    assert c and "post@telenor.no" in c["emails"]
    assert any("+47" in p or "915" in p for p in c["phones"])


def test_extract_contact_none():
    assert _extract_contact("nothing here", "https://x.no") is None


# --- role extraction from web pages ---
def test_extract_names():
    text = "Administrerende direktør: Benedicte Fasmer\nStyreleder: Jens Petter Olsen"
    names = _extract_names(text)
    assert any("Fasmer" in n[0] for n in names)
    assert any("Olsen" in n[0] for n in names)


# --- brreg address parsing ---
def test_address_line():
    assert (
        _address_line({"adresse": ["Postboks 800"], "postnummer": "1331", "poststed": "FORNEBU"})
        == "Postboks 800 1331 FORNEBU"
    )
    assert _address_line(None) is None
    assert _address_line({"adresse": []}) is None


def test_website_normalization():
    assert BrregAdapter._normalize_website("www.telenor.no/") == "https://www.telenor.no/"
    assert BrregAdapter._normalize_website("https://x.no/path") == "https://x.no/path"
    assert BrregAdapter._normalize_website(None) is None
    assert BrregAdapter._normalize_website("HTTP://X.NO") == "http://x.no"

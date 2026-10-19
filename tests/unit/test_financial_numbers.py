"""Authored numeric/candidate fixtures, not adjudicated financial release evidence."""

from decimal import Decimal

import pytest

from nordtrace.adapters.pdf_pipeline import PdfPage, _parse_number, extract_financial_lines


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0", "0"),
        ("0,00", "0.00"),
        ("(0,00)", "-0.00"),
        ("(1 234,50)", "-1234.50"),
        ("−1 234,50", "-1234.50"),
        ("1\u202f234\u202f567,89", "1234567.89"),
        ("1.234.567,89", "1234567.89"),
        ("1,234,567.89", "1234567.89"),
        ("12,3456", "12.3456"),
        ("9007199254740993,01", "9007199254740993.01"),
        ("(" + "9" * 80 + ")", "-" + "9" * 80),
    ],
)
def test_money_candidates_preserve_exact_decimal_value_and_sign(raw, expected):
    value = _parse_number(raw)
    assert isinstance(value, Decimal)
    assert str(value) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "1.234",
        "1,234",
        "12 34",
        "1 23 456",
        "12,34,567",
        "1.234.56",
        "1,2.3",
        "(-12)",
        "(12)-",
        "--12",
        "12..",
        "12,",
        "NOK 12",
        "NaN",
        "Infinity",
        "—",
        "-",
        "",
        "1" * 257,
    ],
)
def test_ambiguous_malformed_and_unavailable_numbers_do_not_turn_into_money(raw):
    assert _parse_number(raw) is None


@pytest.mark.parametrize(
    "raw,mark,expected",
    [
        ("1,234", ",", "1.234"),
        ("1,234", ".", "1234"),
        ("1.234", ",", "1234"),
        ("1.234", ".", "1.234"),
    ],
)
def test_explicit_decimal_convention_resolves_single_separator_ambiguity(raw, mark, expected):
    assert _parse_number(raw, decimal_mark=mark) == Decimal(expected)


def test_comparative_row_cannot_select_another_year_when_current_value_is_zero():
    rows = extract_financial_lines([PdfPage(1, "Driftsinntekter 1200 0\nDriftsresultat 0 450")])
    assert len(rows) == 2
    assert all(row["value"] is None for row in rows)


def test_single_zero_and_parenthesized_negative_are_preserved_as_candidates():
    rows = extract_financial_lines([PdfPage(1, "Driftsinntekter 0\nDriftsresultat (1 234,50)")])
    assert [row["value"] for row in rows] == [Decimal("0"), Decimal("-1234.50")]


def _unqualified_report():
    # Original synthetic PDF text stream; no third-party document or font bytes.
    import io

    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 12 Tf 50 750 Td (TARGET AS Org.nr 982463718) Tj "
        b"0 -24 Td (Annual accounts without currency or accounting scope) Tj "
        b"0 -24 Td (Driftsinntekter 1200 0) Tj "
        b"0 -24 Td (Driftsresultat 42) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_real_pdf_without_accounting_qualifiers_cannot_manufacture_nok_or_publish(tmp_path, monkeypatch):
    import asyncio

    import httpx

    from nordtrace.adapters.pdf_pipeline import PdfFinancialPipeline, extract_pdf_pages
    from nordtrace.core.budget import BudgetManager
    from nordtrace.core.entity import EntityResolver
    from nordtrace.core.models import CompanyIdentity
    from nordtrace.core.repository import Repository
    from nordtrace.core.request_gateway import RequestGateway

    body = _unqualified_report()
    parsed = extract_pdf_pages(body)
    assert parsed.ok and "Driftsinntekter 1200 0" in parsed.pages[0].text
    repo = Repository(tmp_path / "pdf.db")
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    async def execute():
        budget = BudgetManager(max_requests=5)
        gateway = RequestGateway(budget, repository=repo)
        gateway._client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: (
                    httpx.Response(404)
                    if request.url.path == "/robots.txt"
                    else httpx.Response(200, content=body, headers={"content-type": "application/pdf"})
                )
            )
        )
        try:
            return await PdfFinancialPipeline(gateway, budget, EntityResolver()).process_pdf(
                CompanyIdentity(organisation_number="982463718", legal_name="TARGET AS"),
                "https://target.example/annual.pdf",
                "synthetic",
            )
        finally:
            await gateway.aclose()

    try:
        evidence, facts, source, status = asyncio.run(execute())
        assert status == "ambiguous" and not facts
        assert source.access_status == "success" and source.http_status == 200
        assert repo.read_capture(source.source_id)[1] == body
        assert source.error_detail and "scope" in source.error_detail
        assert evidence and all(item.entity_verdict == "AMBIGUOUS" for item in evidence)
        assert all(item.content_hash == source.content_hash for item in evidence)
    finally:
        repo.close()


@pytest.mark.parametrize(
    "pdf_status,expected",
    [
        (200, "ambiguous"),
        (403, "blocked"),
        (429, "blocked"),
        (404, "not_available"),
        (410, "not_available"),
        (500, "failed"),
    ],
)
def test_pdf_ambiguity_survives_complete_pipeline_without_invented_financial_facts(
    tmp_path,
    monkeypatch,
    pdf_status,
    expected,
):
    import asyncio

    import httpx

    from nordtrace.core.budget import BudgetManager
    from nordtrace.core.models import ResearchRun
    from nordtrace.core.repository import Repository
    from nordtrace.engine.pipeline import ResearchPipeline

    body = _unqualified_report()
    org = "982463718"
    repo = Repository(tmp_path / "pipeline.db")
    run = ResearchRun(companies=[org])
    repo.create_run(run)
    monkeypatch.setattr("nordtrace.core.request_gateway._resolve_host", lambda host: ["8.8.8.8"])

    def respond(request):
        if request.url.path.endswith("/enheter/" + org):
            return httpx.Response(
                200,
                json={
                    "organisasjonsnummer": org,
                    "navn": "TARGET AS",
                    "hjemmeside": "https://target.example/",
                },
            )
        if str(request.url) == "https://target.example/":
            return httpx.Response(
                200, text='<p>TARGET AS Org.nr 982463718</p><a href="/annual.pdf">Annual report</a>'
            )
        if request.url.path == "/annual.pdf":
            return httpx.Response(pdf_status, content=body, headers={"content-type": "application/pdf"})
        return httpx.Response(404)

    async def execute():
        pipeline = ResearchPipeline(repo, BudgetManager(max_requests=30))
        pipeline.gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            return await pipeline.research_company(org, run.run_id)
        finally:
            await pipeline.aclose()

    try:
        outcome = asyncio.run(execute())
        assert outcome.error is None
        profile = repo.get_result(run.run_id, org)
        assert not any(fact.category == "financials" for fact in profile.facts)
        assert profile.coverage["financials"] == expected
        source = next(
            item
            for item in profile.sources
            if item.url.endswith("annual.pdf") and item.access_status != "discovered"
        )
        refresh = next(item for item in profile.refresh_outcomes if item.source_id == source.source_id)
        assert refresh.state == expected and refresh.completeness == "unknown"
        assert source.http_status == pdf_status
        if pdf_status == 200:
            assert repo.read_capture(source.source_id)[1] == body
    finally:
        repo.close()

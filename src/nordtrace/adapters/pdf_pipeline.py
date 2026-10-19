"""PDF pipeline: download → verify → extract text with page numbers →
find Norwegian financial key lines → entity verification → evidence.

Deterministic extraction only — the LLM is never allowed to invent financial
values. If a PDF is scanned/image-based (no extractable text) we report
extraction as failed, honestly.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

from nordtrace.core.budget import BudgetManager
from nordtrace.core.config import settings
from nordtrace.core.entity import EntityResolver, normalize_name
from nordtrace.core.models import (
    CompanyIdentity,
    EvidenceRecord,
    Fact,
    MatchVerdict,
    SourceRecord,
    SourceType,
)
from nordtrace.core.request_gateway import RequestGateway

# Norwegian financial key terms → canonical field
_KEY_TERMS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"driftsinntekter|omsetning|operat?:?\s*inntekter", re.I), "revenue"),
    (re.compile(r"driftsresultat", re.I), "operating_result"),
    (re.compile(r"(?:årsresultat|ar:?\s*resultat| result of the year)", re.I), "annual_result"),
    (re.compile(r"sum\s+eiendeler|total\s+assets", re.I), "total_assets"),
    (re.compile(r"egenkapital", re.I), "equity"),
    (re.compile(r"sum\s+gjeld|total\s+liabilities", re.I), "total_liabilities"),
    (re.compile(r"gjennomsnittlig\s+antall\s+ansatte|antall\s+ansatte", re.I), "employees"),
    (re.compile(r"regnskapsåret|regnskap[åa]r", re.I), "fiscal_year"),
]

@dataclass
class PdfPage:
    page_number: int
    text: str


@dataclass
class PdfResult:
    ok: bool
    pages: List[PdfPage] = None  # type: ignore
    error: Optional[str] = None
    is_scanned: bool = False


def extract_pdf_pages(pdf_bytes: bytes) -> PdfResult:
    """Extract text per page using pypdf. Detects scanned (image-only) PDFs."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf_bytes))
        if len(reader.pages) == 0:
            return PdfResult(ok=False, error="empty PDF")
        pages: List[PdfPage] = []
        total_chars = 0
        for i, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            total_chars += len(text.strip())
            pages.append(PdfPage(page_number=i, text=text))
        if total_chars < 50:
            return PdfResult(
                ok=False, pages=pages, is_scanned=True, error="no extractable text (likely scanned/image PDF)"
            )
        return PdfResult(ok=True, pages=pages)
    except Exception as e:
        return PdfResult(ok=False, error=f"pdf parse error: {type(e).__name__}")


def _parse_number(raw: str, *, decimal_mark: Optional[str] = None) -> Optional[Decimal]:
    """Parse one bounded, already identified numeric cell without float rounding.

    A single three-digit separator is ambiguous without an explicit convention.
    This function establishes no currency, multiplier, period or table scope.
    """
    if decimal_mark not in (None, ".", ","):
        raise ValueError("unsupported decimal convention")
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 256:
        return None
    text = raw.strip().replace("\u00a0", " ").replace("\u202f", " ").replace("\u2212", "-")
    sign = ""
    if text.startswith("(") and text.endswith(")"):
        sign, text = "-", text[1:-1]
    elif text.startswith(("-", "+")):
        sign, text = text[0], text[1:]
    if not re.fullmatch(r"[0-9][0-9 .,]*", text) or text.endswith((".", ",", " ")):
        return None

    def integer_digits(value: str, group: Optional[str]) -> Optional[str]:
        separator = group if group and group in value else " " if " " in value else None
        if separator:
            pattern = r"[0-9]{1,3}(?:" + re.escape(separator) + r"[0-9]{3})+"
            return value.replace(separator, "") if re.fullmatch(pattern, value) else None
        return value if re.fullmatch(r"[0-9]+", value) else None

    chosen = decimal_mark
    if chosen is None:
        if "." in text and "," in text:
            chosen = "." if text.rfind(".") > text.rfind(",") else ","
        elif "." in text or "," in text:
            mark = "." if "." in text else ","
            if text.count(mark) == 1:
                left, right = text.split(mark)
                if len(right) == 3 and re.fullmatch(r"[0-9]{1,3}", left):
                    return None
                chosen = mark
            else:
                digits = integer_digits(text, mark)
                return Decimal(sign + digits) if digits is not None else None
    fraction = None
    if chosen and chosen in text:
        if text.count(chosen) != 1:
            return None
        integer, fraction = text.split(chosen)
        if not re.fullmatch(r"[0-9]+", fraction):
            return None
    else:
        integer = text
    grouping = ("," if chosen == "." else ".") if chosen else None
    digits = integer_digits(integer, grouping)
    if digits is None:
        return None
    try:
        return Decimal(sign + digits + ("." + fraction if fraction is not None else ""))
    except InvalidOperation:
        return None


def extract_financial_lines(pages: List[PdfPage]) -> List[Dict]:
    """Unpublished row diagnostics; multiple numbers never select a reporting column."""
    out: List[Dict] = []
    for page in pages:
        for line in page.text.split("\n"):
            line_s = line.strip()
            if not line_s or len(line_s) > 300:
                continue
            for pat, field in _KEY_TERMS:
                if pat.search(line_s):
                    # Plain text does not identify comparative-year columns.
                    # Parentheses delimit one negative cell; spaces can separate
                    # columns, so do not merge numeric tokens into a chosen value.
                    cells = re.findall(
                        r"\([0-9][0-9 \u00a0\u202f.,]*\)|[+\-\u2212]?[0-9][0-9\u00a0\u202f.,]*",
                        line_s,
                    )
                    value = _parse_number(cells[0]) if len(cells) == 1 else None
                    out.append({"field": field, "line": line_s, "page": page.page_number,
                                "value": value, "candidate_cells": cells})
                    break
    return out


class PdfFinancialPipeline:
    """Download + extract + verify + evidence for financial PDFs."""

    def __init__(self, gateway: RequestGateway, budget: BudgetManager, resolver: EntityResolver):
        self.gateway = gateway
        self.budget = budget
        self.resolver = resolver

    async def process_pdf(
        self, identity: CompanyIdentity, pdf_url: str, run_id: str, max_pages: int = 60
    ) -> Tuple[List[EvidenceRecord], List[Fact], SourceRecord, str]:
        """Returns (evidences, facts, source, status). Status:
        found / not_found / failed / blocked."""
        src = await self.gateway.fetch(
            pdf_url,
            respect_robots=True,
            stage="pdf",
            company=identity.organisation_number,
            source_type=SourceType.COMPANY_DOCUMENT.value,
            authority_tier=1,
            max_bytes=settings.max_pdf_bytes,
        )
        if src.access_status != "success":
            if src.access_status in ("blocked", "robots_denied", "rate_limited"):
                status = "blocked"
            elif src.http_status in (404, 410):
                status = "not_found"
            else:
                status = "failed"
            return [], [], src, status

        # content-type verification
        cached = self.gateway.get_content(src.url or "")
        ctype = (cached.headers.get("content-type") or "").lower() if cached else ""
        pdf_bytes = cached.content if cached else b""
        if "pdf" not in ctype and not pdf_bytes.startswith(b"%PDF"):
            return [], [], src, "not_found"

        result = extract_pdf_pages(pdf_bytes)
        if not result.ok:
            # honest failure: scanned or malformed PDF
            ev = EvidenceRecord(
                source_id=src.source_id,
                url=src.url,
                source_title="Annual report (PDF, unreadable)",
                source_type=SourceType.COMPANY_DOCUMENT.value,
                authority_tier=1,
                retrieved_at=src.retrieved_at,
                evidence_text=result.error,
                content_hash=src.content_hash,
                entity_verdict=MatchVerdict.AMBIGUOUS.value,
                org_number=identity.organisation_number,
            )
            return [ev], [], src, "failed"

        # entity verification inside the document
        full_text = "\n".join(p.text for p in result.pages[:max_pages])
        orgnr_in_doc = identity.organisation_number in full_text
        name_in_doc = normalize_name(identity.legal_name) in normalize_name(full_text)
        if not (orgnr_in_doc or name_in_doc):
            ev = EvidenceRecord(
                source_id=src.source_id,
                url=src.url,
                source_title="Annual report (PDF, entity mismatch)",
                source_type=SourceType.COMPANY_DOCUMENT.value,
                authority_tier=1,
                retrieved_at=src.retrieved_at,
                evidence_text="Document does not mention the target company name or orgnr.",
                content_hash=src.content_hash,
                entity_verdict=MatchVerdict.REJECTED.value,
                org_number=identity.organisation_number,
            )
            return [ev], [], src, "not_found"

        lines = [item for item in extract_financial_lines(result.pages[:max_pages])
                 if item["field"] not in ("fiscal_year", "employees")]
        if not lines:
            return [], [], src, "not_found"
        # A regex line and document mention do not identify accounting columns,
        # period, currency, multiplier or entity/group statement scope.
        src.error_detail = (
            "PDF financial candidates require verified table columns, currency, scale, "
            "period and entity/group scope"
        )
        evidences = []
        for item in lines:
            evidences.append(EvidenceRecord(
                source_id=src.source_id, url=src.url,
                source_title=f"Unverified financial row candidate, p.{item['page']}",
                source_type=SourceType.COMPANY_DOCUMENT.value, authority_tier=1,
                retrieved_at=src.retrieved_at, evidence_text=item["line"],
                page_or_section=f"page {item['page']}", content_hash=src.content_hash,
                entity_verdict=MatchVerdict.AMBIGUOUS.value, org_number=identity.organisation_number,
                entity_match_details={
                    "orgnr_mentioned": orgnr_in_doc, "name_mentioned": name_in_doc,
                    "publication_support": "unimplemented", "field_candidate": item["field"],
                    "raw_numeric_cells": item["candidate_cells"],
                    "accounting_qualifiers": "unresolved",
                },
            ))
        return evidences, [], src, "ambiguous"

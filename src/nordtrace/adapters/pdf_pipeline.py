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
from typing import Dict, List, Optional, Tuple

from nordtrace.core.budget import BudgetManager
from nordtrace.core.config import settings
from nordtrace.core.entity import EntityResolver, normalize_name
from nordtrace.core.models import (
    CompanyIdentity,
    EvidenceRecord,
    Fact,
    FactStatus,
    MatchVerdict,
    SourceRecord,
    SourceType,
    content_hash,
    utcnow,
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

_NUMBER_RE = re.compile(r"(-?\d[\d\s\u00a0.,]*)")


@dataclass
class PdfPage:
    page_number: int
    text: str


_NUMBER_RE = re.compile(r"(-?\d[\d\u00a0.,]*\d|\d)")
_SPACE_GROUP_RE = re.compile(r"^(\d{1,3}( \d{3})+)$")


def _join_space_thousands(tokens: list) -> list:
    """Rejoin tokens like ['1','234','567'] when consecutive tokens form
    space-separated thousands groups (Norwegian convention)."""
    out: list = []
    i = 0
    while i < len(tokens):
        # Guard: don't start a group right after a 4+ digit token (year or prior number)
        prev_is_number = i > 0 and tokens[i - 1].isdigit() and len(tokens[i - 1]) >= 4
        if prev_is_number:
            out.append(tokens[i])
            i += 1
            continue
        # try to build a space-grouped number starting at i:
        # first token 1-3 digits, every subsequent token exactly 3 digits
        j = i + 1
        first_ok = len(tokens[i]) <= 3 and tokens[i].isdigit()
        if first_ok:
            while j < len(tokens) and len(tokens[j]) == 3 and tokens[j].isdigit():
                j += 1
        candidate = " ".join(tokens[i:j])
        groups = candidate.split(" ")
        if j - i > 1 and all(len(g) == 3 for g in groups[1:]):
            out.append(candidate)
            i = j
        else:
            out.append(tokens[i])
            i += 1
    return out


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


def _parse_number(raw: str) -> Optional[float]:
    """Parse Norwegian-formatted numbers. Structure-based disambiguation:
    groups of 3 after separator → thousands; 1-2 digits after separator → decimal."""
    if not raw:
        return None
    s = raw.replace("\u00a0", " ").strip().rstrip(".,;")
    if not s:
        return None
    if re.match(r"^-?\d{1,3}(\s\d{3})+$", s):  # 1 234 567
        s = s.replace(" ", "")
    elif re.match(r"^-?\d{1,3}(\.\d{3})+$", s):  # 1.234.567
        s = s.replace(".", "")
    elif re.match(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$", s):  # 47,687.4 -> 47687.4
        s = s.replace(",", "")
    elif re.match(r"^-?\d+,\d{1,2}$", s):  # 1,2 (decimal comma)
        s = s.replace(",", ".")
    s = s.replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return None


def extract_financial_lines(pages: List[PdfPage]) -> List[Dict]:
    """Deterministic key-line extraction with page numbers. Values must appear
    in the document text; nothing is inferred beyond the matched line."""
    out: List[Dict] = []
    for page in pages:
        for line in page.text.split("\n"):
            line_s = line.strip()
            if not line_s or len(line_s) > 300:
                continue
            for pat, field in _KEY_TERMS:
                if pat.search(line_s):
                    # find the last number on the line (statement convention)
                    numbers = _join_space_thousands(_NUMBER_RE.findall(line_s))
                    value = None
                    for cand in reversed(numbers):
                        value = _parse_number(cand)
                        if value is not None and value != 0:
                            break
                    out.append(
                        {
                            "field": field,
                            "line": line_s[:200],
                            "page": page.page_number,
                            "value": value,
                        }
                    )
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
            stage="pdf",
            company=identity.organisation_number,
            source_type=SourceType.COMPANY_DOCUMENT.value,
            authority_tier=1,
            max_bytes=settings.max_pdf_bytes,
        )
        if src.access_status != "success":
            status = "blocked" if src.access_status in ("blocked", "robots_denied") else "failed"
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
                content_hash=content_hash(pdf_bytes[:100000].hex() or src.content_hash or ""),
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

        lines = extract_financial_lines(result.pages[:max_pages])
        now = utcnow().isoformat()
        evidences: List[EvidenceRecord] = []
        facts: List[Fact] = []

        # fiscal year from document (prefer explicit)
        fy = None
        for ln_item in lines:
            if ln_item["field"] == "fiscal_year":
                m = re.search(r"(19|20)\d{2}", ln_item["line"])
                if m:
                    fy = f"FY{m.group(0)}"
                    break

        seen_fields: Dict[str, Dict] = {}
        for ln_item in lines:
            if ln_item["field"] == "fiscal_year" or ln_item["value"] is None:
                continue
            k = ln_item["field"]
            if k not in seen_fields:  # first occurrence wins (statement order)
                seen_fields[k] = ln_item
        for field, ln_item in seen_fields.items():
            ev = EvidenceRecord(
                source_id=src.source_id,
                url=src.url,
                source_title=f"Annual report (PDF), p.{ln_item['page']}",
                source_type=SourceType.COMPANY_DOCUMENT.value,
                authority_tier=1,
                retrieved_at=src.retrieved_at,
                evidence_text=ln_item["line"],
                page_or_section=f"page {ln_item['page']}",
                content_hash=src.content_hash,
                entity_verdict=MatchVerdict.LIKELY.value,
                org_number=identity.organisation_number,
                entity_match_details={"orgnr_in_doc": orgnr_in_doc, "name_in_doc": name_in_doc},
            )
            evidences.append(ev)
            facts.append(
                Fact(
                    org_number=identity.organisation_number,
                    run_id=run_id,
                    category="financials",
                    field=field,
                    value=ln_item["value"],
                    normalized_value=ln_item["value"],
                    currency="NOK",
                    reporting_period=fy,
                    source_id=src.source_id,
                    evidence_id=ev.evidence_id,
                    retrieved_at=now,
                    entity_verdict=MatchVerdict.LIKELY.value,
                    fact_confidence=0.75,
                    status=FactStatus.PUBLISHED.value,
                )
            )
        status = "found" if facts else "not_found"
        return evidences, facts, src, status

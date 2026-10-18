"""Strict retained HTML support; downloaded content never executes."""
from __future__ import annotations

import re
from datetime import datetime
from email.message import Message
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, CData, NavigableString, Tag

from nordtrace.core.entity import subject_orgnrs
from nordtrace.core.models import EvidenceRecord, Fact, HtmlJsonLdLocator, SourceRecord
from nordtrace.core.orgnr import validate_orgnr

# Preserve role/identifier context across block boundaries, including footers.
_IDENTITY_BLOCKS = frozenset({
    "address", "article", "aside", "blockquote", "body", "dd", "div", "dl", "dt", "fieldset",
    "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header",
    "li", "main", "nav", "ol", "p", "pre", "section", "table", "td", "th", "tr", "ul",
})


def visible_identity_text(soup: BeautifulSoup) -> str:
    """Keep inline labels together without merging unrelated block subjects."""
    parts: list[str] = []
    previous_block = None
    for node in soup.descendants:
        if isinstance(node, Tag) and node.name in ("br", "hr"):
            previous_block = None
            continue
        if type(node) not in (NavigableString, CData):
            continue
        text = str(node).strip()
        if not text:
            continue
        block = next((parent for parent in node.parents if parent.name in _IDENTITY_BLOCKS), soup)
        if parts:
            parts.append(" " if id(block) == previous_block else "\n")
        parts.append(text)
        previous_block = id(block)
    return "".join(parts)


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or any(ord(c) <= 32 or ord(c) >= 127 for c in url)):
        raise ValueError("HTML attachment requires a safe HTTPS URL")
    if parsed.fragment or parsed.port == 0:
        raise ValueError("HTML URL fragment or port unsupported")
    return parsed.scheme, parsed.hostname.lower(), parsed.port if parsed.port is not None else 443


def _require_utf8_content_type(value: str) -> None:
    header = Message()
    header["content-type"] = value
    charsets = [item for key, item in (header.get_params() or [])[1:] if key.lower() == "charset"]
    if (header.get_content_type() != "text/html" or len(charsets) > 1
            or any(not isinstance(item, str) or item.lower() not in ("utf-8", "utf8")
                   for item in charsets)):
        raise ValueError("HTML requires unambiguous text/html UTF8 representation")


def verify_html_support(
    repo, fact: Fact, source: SourceRecord, evidence: EvidenceRecord, body: bytes,
) -> None:
    # Imports are local to keep evidence parsing and bounded candidate extraction acyclic.
    from nordtrace.core.evidence import parse_json_body, require_registry_identity_acquisition
    from nordtrace.core.structured_data import organization_descriptions

    locator = evidence.locator
    if not isinstance(locator, HtmlJsonLdLocator):
        raise ValueError("typed HTML locator required")
    if (source.source_type != "company_website" or source.authority_tier != 1
            or source.access_status != "success" or source.http_status != 200
            or source.snapshot_representation != "http-response-body-v1"):
        raise ValueError("HTML source acquisition unsupported")
    _require_utf8_content_type(source.content_type or "")
    if (fact.category, fact.field) != ("business_description", "description"):
        raise ValueError("HTML predicate has no supported extraction rule")
    if (fact.subject_scope != "legal_entity" or fact.item_key is not None
            or fact.entity_verdict != "VERIFIED"):
        raise ValueError("HTML description requires exact scalar legal-entity subject")
    anchor, anchor_body = repo.read_capture(locator.identity_source_id)
    if (anchor.source_type != "registry" or anchor.authority_tier != 0
            or anchor.access_status != "success" or anchor.http_status != 200):
        raise ValueError("HTML official identity anchor unavailable")
    if (anchor.org_number != fact.org_number or not anchor.retrieved_at
            or datetime.fromisoformat(anchor.retrieved_at).tzinfo is None):
        raise ValueError("HTML anchor subject/time provenance missing or different")
    require_registry_identity_acquisition(anchor, fact.org_number)
    document = parse_json_body(anchor_body)
    if (not isinstance(document, dict) or document.get("organisasjonsnummer") != fact.org_number
            or not validate_orgnr(fact.org_number).valid
            or not isinstance(document.get("navn"), str) or not document["navn"].strip()):
        raise ValueError("HTML anchor subject missing or different")
    registered = document.get("hjemmeside")
    if not isinstance(registered, str) or not registered.strip():
        raise ValueError("HTML requires a retained registered website")
    registered = registered.strip()
    expected = _origin(registered if "://" in registered else "https://" + registered)
    for url in (source.url, source.requested_url or source.url, source.final_url or source.url,
                *source.redirect_chain):
        if not url or _origin(url) != expected:
            raise ValueError("HTML acquisition origin differs from retained registered website")
    # Strict UTF8 is a declared local representation, never replacement decoding.
    text = body.decode("utf-8-sig")
    closed = re.search(r"</html\s*>", text, flags=re.I)
    if closed and text[closed.end():].strip():
        raise ValueError("HTML has unsupported trailing content after closed document")
    soup = BeautifulSoup(text, "lxml")
    for meta in soup.find_all("meta"):
        if meta.has_attr("charset") and str(meta["charset"]).lower() not in ("utf-8", "utf8"):
            raise ValueError("HTML embedded charset differs from declared UTF8 representation")
        if str(meta.get("http-equiv", "")).lower() == "content-type":
            _require_utf8_content_type(str(meta.get("content", "")))
    if any(org != fact.org_number for org in subject_orgnrs(visible_identity_text(soup))):
        raise ValueError("HTML page carries a contradictory subject identifier")
    candidates, _rejected = organization_descriptions(soup, fact.org_number, document["navn"])
    matching = [candidate for candidate in candidates if candidate["script_index"] == locator.script_index
                and candidate["pointer"] == locator.pointer]
    if len(matching) != 1 or matching[0]["raw_value"] != locator.raw_value:
        raise ValueError("HTML locator does not resolve to supported exact-subject literal")
    if (fact.value != locator.raw_value or fact.normalized_value != locator.raw_value
            or evidence.evidence_text != locator.raw_value):
        raise ValueError("HTML value/display differs from retained literal")

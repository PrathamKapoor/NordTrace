"""Snapshot-backed support checks; unsupported extraction formats fail closed."""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit, urlunsplit

from nordtrace.core.models import EvidenceRecord, Fact, SourceRecord
from nordtrace.core.orgnr import validate_orgnr


class SnapshotReader(Protocol):
    def read_capture(self, source_id: str) -> tuple[SourceRecord, bytes]: ...


def require_json_nesting(raw: str) -> None:
    """Bound JSON container depth before decoding, ignoring string contents."""
    depth = 0
    quoted = False
    escaped = False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 64:
                raise ValueError("JSON nesting capacity exceeded")
        elif char in "]}":
            depth -= 1


def require_json_unicode(document: Any) -> None:
    """Reject non-scalar strings in a decoded JSON tree without rewriting data.

    Escaped unpaired surrogates survive json.loads but cannot be retained as
    UTF8 evidence/SQLite text. Inspect object keys and unused nested values too:
    whole-record locators may preserve them even when one selected field is safe.
    """
    pending = [document]
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
                raise ValueError("JSON contains invalid Unicode scalar")
        elif isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object member")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError("nonfinite JSON constant unsupported")


def _finite_json_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise ValueError("JSON number outside supported finite range")
    coefficient = token.lower().split("e", 1)[0]
    if value == 0 and any(char in "123456789" for char in coefficient):
        raise ValueError("JSON number underflow unsupported")
    return value


def parse_json_body(body: bytes) -> Any:
    """Decode network JSON as UTF8 strictly; tolerate an optional UTF8 BOM.

    Do not use HTTPX's replacement-decoded text as an identity/evidence value.
    """
    text = body.decode("utf-8-sig")
    require_json_nesting(text)
    document = json.loads(
        text, object_pairs_hook=_unique_json_object,
        parse_constant=_reject_json_constant, parse_float=_finite_json_float,
    )
    require_json_unicode(document)
    return document

# These paths express the public Enhetsregisteret schema, not evaluator rules.
IDENTITY_PATHS: dict[str, tuple[tuple[str, ...], str]] = {
    "legal_name": (("/navn",), "identity"),
    "organisation_form": (("/organisasjonsform/kode",), "identity"),
    "status": (("",), "brreg-status-v1"),
    "registered_address": (("/forretningsadresse",), "brreg-address-v1"),
    "municipality": (("/forretningsadresse/kommune", "/postadresse/kommune"), "identity"),
    "industry_code": (("/naeringskode1/kode",), "identity"),
    "industry_description": (("/naeringskode1/beskrivelse",), "identity"),
    "website": (("/hjemmeside",), "brreg-website-v1"),
    "registration_date": (("/registreringsdatoEnhetsregisteret",), "identity"),
    "employee_count": (("/antallAnsatte",), "identity"),
}


def resolve_pointer(document: Any, pointer: str) -> Any:
    """RFC 6901 JSON pointer, with strict escapes and array indices."""
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError("JSON pointer must start with /")
    value = document
    for encoded in pointer[1:].split("/"):
        if re.search(r"~(?![01])", encoded):
            raise ValueError("invalid JSON pointer escape")
        token = encoded.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(value, list):
                if not re.fullmatch(r"0|[1-9][0-9]*", token):
                    raise ValueError("invalid JSON array index")
                value = value[int(token)]
            elif isinstance(value, dict):
                value = value[token]
            else:
                raise ValueError("JSON pointer traverses a scalar")
        except (KeyError, IndexError, OverflowError) as error:
            raise ValueError("JSON pointer not found") from error
    return value


def normalize_registry_value(raw: Any, normalization: str) -> Any:
    if normalization == "identity":
        return raw
    if normalization == "brreg-subunit-v1":
        return normalize_subunit(raw)
    if normalization == "brreg-address-v1" and isinstance(raw, dict):
        return " ".join(str(part) for part in [
            " ".join(raw.get("adresse") or []), raw.get("postnummer"), raw.get("poststed"),
        ] if part) or None
    if normalization == "brreg-website-v1" and isinstance(raw, str):
        raw = raw.strip()
        parts = urlsplit(raw if "://" in raw else "https://" + raw)
        if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
            raise ValueError("unsupported website URL")
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))
    if normalization == "brreg-status-v1" and isinstance(raw, dict):
        if raw.get("slettedato"):
            return "deleted"
        if raw.get("konkurs") is True:
            return "bankrupt"
        if raw.get("underAvvikling") is True:
            return "under_liquidation"
        if raw.get("underTvangsavviklingEllerTvangsopplosning") is True:
            return "under_compulsory_liquidation"
        if all(raw.get(key) is False for key in (
            "konkurs", "underAvvikling", "underTvangsavviklingEllerTvangsopplosning",
        )):
            return "active"
        return "unknown"
    raise ValueError("normalization incompatible with source value")


def normalize_subunit(raw: Any) -> dict:
    """Schema-v2 subunit relationship, preserving physical-address scope."""
    if not isinstance(raw, dict):
        raise ValueError("subunit must be an object")
    org = validate_orgnr(raw.get("organisasjonsnummer", ""))
    parent = validate_orgnr(raw.get("overordnetEnhet", ""))
    if not org.valid or not parent.valid or org.value == parent.value:
        raise ValueError("subunit and explicit parent identifiers must be distinct valid orgnrs")
    name = raw.get("navn")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("subunit name missing or invalid")
    address = raw.get("beliggenhetsadresse")
    industry = raw.get("naeringskode1")
    address = {} if address is None else address
    industry = {} if industry is None else industry
    if not isinstance(address, dict) or not isinstance(industry, dict):
        raise ValueError("subunit address/industry schema mismatch")
    lines = address.get("adresse", [])
    if not isinstance(lines, list) or any(not isinstance(line, str) for line in lines):
        raise ValueError("subunit address lines invalid")
    value = {"orgnr": org.value, "parent_orgnr": parent.value, "name": name,
             "physical_address": " ".join(lines) or None, "municipality": address.get("kommune"),
             "postal_code": address.get("postnummer"), "postal_area": address.get("poststed"),
             "industry": industry.get("beskrivelse"), "closure_date": raw.get("nedleggelsesdato"),
             "deleted_date": raw.get("slettedato")}
    if any(item is not None and not isinstance(item, str) for item in value.values()):
        raise ValueError("subunit attributes must be strings or unknown")
    for field in ("closure_date", "deleted_date"):
        date_value = value[field]
        if isinstance(date_value, str):
            date.fromisoformat(date_value)
    return value


def _same(a: Any, b: Any) -> bool:
    # JSON types distinguish false from 0; numeric coercion must be declared.
    return json.dumps(a, sort_keys=True, ensure_ascii=False, allow_nan=False) == json.dumps(
        b, sort_keys=True, ensure_ascii=False, allow_nan=False
    )


def require_registry_identity_acquisition(source: SourceRecord, org_number: str) -> None:
    """Only the exact official HTTPS entity lookup establishes live registry authority.

    Supplied official snapshots need a separate versioned anchor contract; a
    configured mirror or self-declared authority tier cannot substitute for it.
    """
    expected_path = "/enhetsregisteret/api/enheter/" + org_number
    urls = [source.url, source.requested_url or source.url, source.final_url or source.url,
            *source.redirect_chain]
    for url in urls:
        try:
            if not url or any(ord(char) < 32 or ord(char) == 127 for char in url):
                raise ValueError("invalid URL")
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or parsed.hostname != "data.brreg.no"
                    or parsed.port not in (None, 443) or parsed.username is not None
                    or parsed.password is not None or parsed.path.rstrip("/") != expected_path
                    or parsed.query or parsed.fragment):
                raise ValueError("unsupported endpoint")
        except ValueError as error:
            raise ValueError(
                "registry identity acquisition requires the exact official entity endpoint"
            ) from error


def verify_capture_metadata(captured: SourceRecord, source: SourceRecord) -> None:
    for field in (
        "url", "requested_url", "final_url", "redirect_chain", "source_type", "org_number",
        "content_hash", "content_type", "http_status", "snapshot_representation", "retrieved_at",
        "authority_tier", "access_status",
    ):
        if getattr(captured, field) != getattr(source, field):
            raise ValueError("acquisition metadata disagrees with captured source")


def verify_snapshot_support(
    repo: SnapshotReader, fact: Fact, source: SourceRecord, evidence: EvidenceRecord,
) -> None:
    captured, body = repo.read_capture(source.source_id)
    verify_capture_metadata(captured, source)
    if evidence.content_hash != captured.content_hash:
        raise ValueError("evidence does not identify the retained snapshot")
    if not captured.retrieved_at or datetime.fromisoformat(captured.retrieved_at).tzinfo is None:
        raise ValueError("capture retrieval time must include a timezone")
    if (
        evidence.retrieved_at != captured.retrieved_at or fact.retrieved_at != captured.retrieved_at
        or evidence.authority_tier != captured.authority_tier
        or evidence.source_type != captured.source_type
    ):
        raise ValueError("evidence/claim provenance differs from capture")
    locator = evidence.locator
    if locator is None:
        raise ValueError("snapshot-backed evidence locator required")
    document = parse_json_body(body)
    raw = resolve_pointer(document, locator.pointer)
    if not _same(raw, locator.raw_value):
        raise ValueError("locator raw value differs from snapshot")
    if fact.category == "locations" and fact.field == "branch":
        if source.source_type != "registry" or source.authority_tier != 0:
            raise ValueError("subunit claim requires official registry acquisition")
        for url in (source.url, source.requested_url or source.url, source.final_url or source.url,
                    *source.redirect_chain):
            if not url or any(ord(char) < 32 or ord(char) == 127 for char in url):
                raise ValueError("subunit acquisition URL invalid")
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or parsed.hostname != "data.brreg.no"
                    or parsed.port not in (None, 443)
                    or parsed.username is not None or parsed.password is not None or parsed.fragment
                    or parsed.path.rstrip("/") != "/enhetsregisteret/api/underenheter"
                    or parse_qs(parsed.query, keep_blank_values=True).get("overordnetEnhet")
                    != [fact.org_number]):
                raise ValueError("subunit acquisition endpoint or parent filter differs")
        if (locator.normalization != "brreg-subunit-v1"
                or not re.fullmatch(r"/_embedded/underenheter/(0|[1-9][0-9]*)", locator.pointer)):
            raise ValueError("subunit locator must select the exact collection record")
        value = normalize_subunit(raw)
        if (value["parent_orgnr"] != fact.org_number or fact.item_key != value["orgnr"]
                or fact.subject_scope != "legal_entity"):
            raise ValueError("subunit parent, item or relationship scope differs")
        if not _same(fact.value, value) or not _same(fact.normalized_value, value):
            raise ValueError("subunit attributes differ from captured record")
        if evidence.evidence_text != json.dumps(raw, ensure_ascii=False, sort_keys=True):
            raise ValueError("subunit evidence display differs from located record")
        return
    if fact.category != "identity" or source.source_type != "registry" or source.authority_tier != 0:
        raise ValueError("claim predicate has no supported extraction rule")
    require_registry_identity_acquisition(source, fact.org_number)
    subject = validate_orgnr(document.get("organisasjonsnummer", "")) if isinstance(document, dict) else None
    if subject is None or not subject.valid or subject.value != fact.org_number:
        raise ValueError("snapshot subject differs from claim subject")
    if fact.subject_scope != "legal_entity" or fact.item_key is not None:
        raise ValueError("registry identity requires scalar legal-entity scope")
    rule = IDENTITY_PATHS.get(fact.field)
    if rule is None or locator.pointer not in rule[0] or locator.normalization != rule[1]:
        raise ValueError("locator does not support this claim predicate")
    if fact.field == "municipality":
        preferred = (
            "/forretningsadresse/kommune" if document.get("forretningsadresse") else "/postadresse/kommune"
        )
        if locator.pointer != preferred:
            raise ValueError("municipality pointer differs from registered address scope")
    normalized = normalize_registry_value(raw, locator.normalization)
    if normalized is None or normalized == "unknown":
        raise ValueError("source value is unknown")
    if fact.field == "employee_count":
        if type(normalized) is not int or normalized < 0:
            raise ValueError("employee count must be a nonnegative integer, never a boolean")
    elif not isinstance(normalized, str) or not normalized.strip():
        raise ValueError("identity field must be a nonempty string")
    if fact.field == "registration_date":
        date.fromisoformat(normalized)
    if not _same(fact.value, normalized) or not _same(fact.normalized_value, normalized):
        raise ValueError("claim value differs from supported normalized value")
    # A structured field is displayed as a value, never presented as a verbatim quote.
    if evidence.evidence_text != json.dumps(raw, ensure_ascii=False, sort_keys=True):
        raise ValueError("structured evidence display differs from located value")

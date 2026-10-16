"""Snapshot-backed support checks; unsupported extraction formats fail closed."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from nordtrace.core.models import EvidenceRecord, Fact, SourceRecord
from nordtrace.core.orgnr import validate_orgnr
from nordtrace.core.repository import Repository

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


def _same(a: Any, b: Any) -> bool:
    # JSON types distinguish false from 0; numeric coercion must be declared.
    return json.dumps(a, sort_keys=True, ensure_ascii=False, allow_nan=False) == json.dumps(
        b, sort_keys=True, ensure_ascii=False, allow_nan=False
    )


def verify_snapshot_support(
    repo: Repository, fact: Fact, source: SourceRecord, evidence: EvidenceRecord,
) -> None:
    captured, body = repo.read_capture(source.source_id)
    for field in (
        "url", "requested_url", "final_url", "redirect_chain", "source_type", "org_number",
        "content_hash", "content_type", "http_status", "snapshot_representation", "retrieved_at",
        "authority_tier", "access_status",
    ):
        if getattr(captured, field) != getattr(source, field):
            raise ValueError("acquisition metadata disagrees with captured source")
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
    document = json.loads(body)
    raw = resolve_pointer(document, locator.pointer)
    if not _same(raw, locator.raw_value):
        raise ValueError("locator raw value differs from snapshot")
    if fact.category != "identity" or source.source_type != "registry" or source.authority_tier != 0:
        raise ValueError("claim predicate has no supported extraction rule")
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

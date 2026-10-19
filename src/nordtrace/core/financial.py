"""Exact source-number diagnostics; no implied monetary units or publication rule."""
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from nordtrace.core.evidence import decode_source_json
from nordtrace.core.models import EvidenceRecord, Fact, JsonPointerLocator, SourceRecord
from nordtrace.core.orgnr import validate_orgnr


@dataclass(frozen=True)
class JsonNumber:
    """Distinguish an actual JSON numeric token from strings and booleans."""

    lexeme: str

    def __post_init__(self) -> None:
        if len(self.lexeme) > 256:
            raise ValueError("financial JSON number token capacity exceeded")

    def decimal_text(self) -> str:
        try:
            value = Decimal(self.lexeme)
        except InvalidOperation as error:
            raise ValueError("unsupported financial JSON number") from error
        # Local supported range, not a Brreg schema assertion. Bound before
        # fixed-point formatting so a tiny exponent token cannot expand memory.
        exponent = value.as_tuple().exponent
        if (not value.is_finite() or not isinstance(exponent, int)
                or abs(exponent) > 36 or value.adjusted() > 35
                or len(value.as_tuple().digits) > 48 or exponent < -12):
            raise ValueError("financial source number outside supported exact range")
        return format(value, "f")


def parse_accounts_json(body: bytes) -> Any:
    """Keep all number lexemes internally; never inject Decimal into generic DTOs."""
    return decode_source_json(body, parse_float=JsonNumber, parse_int=JsonNumber)


STATEMENT_RULE = "brreg-statement-metadata-v1"


def _record_id(record: Any) -> str:
    value = record.get("id") if isinstance(record, dict) else None
    if (not isinstance(value, JsonNumber) or not re.fullmatch(r"[1-9][0-9]{0,9}", value.lexeme)
            or int(value.lexeme) > 2147483647):
        raise ValueError("statement requires a positive int32 record identifier")
    return value.lexeme


def statement_metadata(record: Any, orgnr: str) -> dict[str, str]:
    """Source-declared record attributes; never an amount, approval or latest-filing assertion."""
    record_id = _record_id(record)
    entity = record.get("virksomhet")
    raw_org = entity.get("organisasjonsnummer") if isinstance(entity, dict) else None
    subject = validate_orgnr(raw_org) if isinstance(raw_org, str) else None
    if (subject is None or not subject.valid or subject.value != orgnr
            or record.get("regnskapstype") != "SELSKAP"):
        raise ValueError("statement legal-entity subject or scope unresolved")
    currency = record.get("valuta")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("statement source currency missing")
    period = record.get("regnskapsperiode")
    if not isinstance(period, dict):
        raise ValueError("statement period missing")
    start, end = period.get("fraDato"), period.get("tilDato")
    if (not isinstance(start, str) or not isinstance(end, str)
            or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", start)
            or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", end)):
        raise ValueError("statement requires full source dates")
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError("statement period reversed")
    value = {"record_id": record_id, "currency": currency, "period_start": start, "period_end": end,
             "accounting_scope": "legal_entity"}
    journal = record.get("journalnr")
    if journal is not None:
        if (not isinstance(journal, str) or not journal.strip() or len(journal) > 128
                or any(ord(char) < 32 or ord(char) == 127 for char in journal)):
            raise ValueError("statement journal identifier malformed")
        value["journal_number"] = journal
    return value


def statement_entries(document: Any, orgnr: str) -> list[tuple[str, dict[str, str]]]:
    """Distinct record IDs, abstaining on contradictory bindings; no version ordering."""
    records = document if isinstance(document, list) else [document]
    if len(records) > 100:
        return []  # Local metadata output limit; no completeness/removal assertion.
    groups: dict[str, list[tuple[str, dict[str, str] | None]]] = {}
    for index, record in enumerate(records):
        try:
            record_id = _record_id(record)
        except ValueError:
            continue
        try:
            value = statement_metadata(record, orgnr)
        except ValueError:
            value = None
        pointer = (f"/{index}" if isinstance(document, list) else "") + "/id"
        groups.setdefault(record_id, []).append((pointer, value))
    return [(items[0][0], items[0][1]) for items in groups.values()
            if items[0][1] is not None and all(value == items[0][1] for _, value in items)]


def statement_locations(pointer: str, value: dict[str, str]) -> dict[str, str]:
    prefix = pointer[:-3]  # Only the producer/independent entries reader supplies /id pointers.
    result = {"record_id": pointer, "currency": prefix + "/valuta",
              "period_start": prefix + "/regnskapsperiode/fraDato",
              "period_end": prefix + "/regnskapsperiode/tilDato",
              "accounting_scope": prefix + "/regnskapstype",
              "subject": prefix + "/virksomhet/organisasjonsnummer"}
    if "journal_number" in value:
        result["journal_number"] = prefix + "/journalnr"
    return result


def statement_claims(
    document: Any, orgnr: str, run_id: str, source: SourceRecord,
) -> tuple[list[EvidenceRecord], list[Fact]]:
    evidence, facts = [], []
    for pointer, value in statement_entries(document, orgnr):
        ev = EvidenceRecord(
            source_id=source.source_id, source_type=source.source_type, authority_tier=source.authority_tier,
            url=source.url, org_number=orgnr, entity_verdict="VERIFIED", retrieved_at=source.retrieved_at,
            content_hash=source.content_hash,
            evidence_text=json.dumps(value, ensure_ascii=False, sort_keys=True),
            locator=JsonPointerLocator(pointer=pointer, raw_value=int(value["record_id"])),
            entity_match_details={"extraction_rule": STATEMENT_RULE,
                                  "supporting_pointers": statement_locations(pointer, value)},
        )
        evidence.append(ev)
        facts.append(Fact(
            org_number=orgnr, run_id=run_id, category="accounting_filings", field="statement", value=value,
            normalized_value=value, item_key=value["record_id"], subject_scope="legal_entity",
            reporting_period=value["period_start"] + "/" + value["period_end"],
            valid_from=value["period_start"], valid_to=value["period_end"],
            source_id=source.source_id, evidence_id=ev.evidence_id, retrieved_at=source.retrieved_at,
            entity_verdict="VERIFIED", status="EXTRACTED", fact_confidence=0.0,
        ))
    return evidence, facts


def verify_statement_support(fact: Fact, source: SourceRecord, evidence: EvidenceRecord, body: bytes) -> None:
    locator = evidence.locator
    if (fact.field != "statement" or not isinstance(locator, JsonPointerLocator)
            or locator.normalization != "identity" or type(locator.raw_value) is not int
            or fact.subject_scope != "legal_entity" or fact.unit is not None or fact.currency is not None
            or fact.entity_verdict != "VERIFIED" or evidence.entity_verdict != "VERIFIED"
            or evidence.entity_match_details.get("extraction_rule") != STATEMENT_RULE):
        raise ValueError("unsupported statement metadata contract")
    if (source.source_type != "registry_accounts" or source.authority_tier != 0
            or source.access_status != "success" or source.http_status != 200
            or source.snapshot_representation != "http-response-body-v1"
            or (source.content_type or "").split(";", 1)[0].strip().lower() != "application/json"):
        raise ValueError("statement metadata requires captured official JSON")
    root = "/regnskapsregisteret/regnskap/" + fact.org_number
    for url in (source.url, source.requested_url or source.url, source.final_url or source.url,
                *source.redirect_chain):
        if not url or any(ord(char) < 33 or ord(char) == 127 for char in url):
            raise ValueError("statement acquisition URL invalid")
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname != "data.brreg.no" or parsed.port not in (None, 443)
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment
                or parsed.path not in (root, root + "/" + str(locator.raw_value))):
            raise ValueError("statement metadata requires exact official company/record endpoint")
    supported = dict(statement_entries(parse_accounts_json(body), fact.org_number)).get(locator.pointer)
    if supported is None or str(locator.raw_value) != supported["record_id"]:
        raise ValueError("statement locator or record binding differs from capture")
    if (fact.value != supported or fact.normalized_value != supported
            or fact.item_key != supported["record_id"]
            or evidence.entity_match_details.get("supporting_pointers")
            != statement_locations(locator.pointer, supported)
            or fact.reporting_period != supported["period_start"] + "/" + supported["period_end"]
            or fact.valid_from != supported["period_start"] or fact.valid_to != supported["period_end"]
            or evidence.evidence_text != json.dumps(supported, ensure_ascii=False, sort_keys=True)):
        raise ValueError("statement attributes differ from independently resolved record")

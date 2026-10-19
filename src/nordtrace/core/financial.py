"""Exact source-number support: statement metadata and documented whole-unit registry amounts."""
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from nordtrace.core.evidence import decode_source_json
from nordtrace.core.models import EvidenceRecord, Fact, JsonNumberLocator, JsonPointerLocator, SourceRecord
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


def _require_accounts_capture(source: SourceRecord, orgnr: str, record_id: str) -> None:
    if (source.source_type != "registry_accounts" or source.authority_tier != 0
            or source.access_status != "success" or source.http_status != 200
            or source.snapshot_representation != "http-response-body-v1"
            or (source.content_type or "").split(";", 1)[0].strip().lower() != "application/json"):
        raise ValueError("account support requires captured official JSON")
    root = "/regnskapsregisteret/regnskap/" + orgnr
    for url in (source.url, source.requested_url or source.url, source.final_url or source.url,
                *source.redirect_chain):
        if not url or any(ord(char) < 33 or ord(char) == 127 for char in url):
            raise ValueError("account acquisition URL invalid")
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname != "data.brreg.no" or parsed.port not in (None, 443)
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment
                or parsed.path not in (root, root + "/" + record_id)):
            raise ValueError("account support requires exact official company/record endpoint")


def verify_statement_support(fact: Fact, source: SourceRecord, evidence: EvidenceRecord, body: bytes) -> None:
    locator = evidence.locator
    if (fact.field != "statement" or not isinstance(locator, JsonPointerLocator)
            or locator.normalization != "identity" or type(locator.raw_value) is not int
            or fact.subject_scope != "legal_entity" or fact.unit is not None or fact.currency is not None
            or fact.entity_verdict != "VERIFIED" or evidence.entity_verdict != "VERIFIED"
            or evidence.entity_match_details.get("extraction_rule") != STATEMENT_RULE):
        raise ValueError("unsupported statement metadata contract")
    _require_accounts_capture(source, fact.org_number, str(locator.raw_value))
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


AMOUNT_RULE = "brreg-account-amount-v1"
AMOUNT_UNIT = "currency_unit_x1"
# D-086: the RR-0002 filing guidance states that thousands/millions denominations
# are multiplied when Regnskapsregisteret receives the form set; the key-figure
# API exposes no denomination field. Multiplier 1 of the record's own currency.
AMOUNT_PATHS = {
    "total_operating_revenue": (
        "resultatregnskapResultat", "driftsresultat", "driftsinntekter", "sumDriftsinntekter",
    ),
    "operating_result": ("resultatregnskapResultat", "driftsresultat", "driftsresultat"),
    "annual_result": ("resultatregnskapResultat", "aarsresultat"),
    "total_assets": ("eiendeler", "sumEiendeler"),
    "equity": ("egenkapitalGjeld", "egenkapital", "sumEgenkapital"),
    "total_liabilities": ("egenkapitalGjeld", "gjeldOversikt", "sumGjeld"),
}


def canonical_amount(number: JsonNumber) -> str:
    """Exact fixed-point decimal string: no exponent, no trailing fraction zeros, no -0."""
    value = Decimal(number.decimal_text())
    if value == 0:
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def amount_entries(document: Any, orgnr: str) -> dict[str, dict[str, str]]:
    """Supported amounts keyed by exact field pointer; whole periods abstain on any competition.

    One legal-entity record per full period is required. Distinct records for one
    period, or a subject record whose period cannot be resolved, withhold amounts:
    no amendment, latest-filing or row-order precedence is asserted.
    """
    records = document if isinstance(document, list) else [document]
    if len(records) > 100:
        return {}
    by_period: dict[tuple[str, str], list[tuple[str, Any, dict[str, str] | None]]] = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            return {}
        entity = record.get("virksomhet")
        raw_org = entity.get("organisasjonsnummer") if isinstance(entity, dict) else None
        subject = validate_orgnr(raw_org) if isinstance(raw_org, str) else None
        if subject is None or not subject.valid or subject.value != orgnr:
            continue
        if record.get("regnskapstype") == "KONSERN":
            continue  # Group scope is a different claim; it never competes with SELSKAP.
        period = record.get("regnskapsperiode")
        start = period.get("fraDato") if isinstance(period, dict) else None
        end = period.get("tilDato") if isinstance(period, dict) else None
        try:
            if not isinstance(start, str) or not isinstance(end, str):
                raise ValueError("period")
            key = (date.fromisoformat(start).isoformat(), date.fromisoformat(end).isoformat())
            if key != (start, end):
                raise ValueError("period")
        except ValueError:
            return {}  # An unplaceable subject record could compete with any period.
        try:
            metadata: dict[str, str] | None = statement_metadata(record, orgnr)
        except ValueError:
            metadata = None
        if record.get("avviklingsregnskap") is not False:
            metadata = None  # Liquidation-basis or undeclared statements are withheld.
        prefix = f"/{index}" if isinstance(document, list) else ""
        by_period.setdefault(key, []).append((prefix, record, metadata))
    result: dict[str, dict[str, str]] = {}
    for items in by_period.values():
        prefix, record, metadata = items[0]
        if metadata is None or any(other != record for _, other, _ in items[1:]):
            continue
        for field, path in AMOUNT_PATHS.items():
            value: Any = record
            for part in path:
                value = value.get(part) if isinstance(value, dict) else None
            if not isinstance(value, JsonNumber):
                continue  # Absent, null, string or boolean values never become amounts.
            try:
                amount = canonical_amount(value)
            except ValueError:
                continue
            result[prefix + "/" + "/".join(path)] = {
                "field": field, "source_field": path[-1], "source_number": value.lexeme,
                "value": amount, "record_pointer": prefix, **metadata,
            }
    return result


def amount_display(entry: dict[str, str]) -> str:
    keys = ("source_field", "source_number", "value", "currency", "period_start", "period_end",
            "record_id", "journal_number", "accounting_scope")
    return json.dumps({key: entry[key] for key in keys if key in entry}, ensure_ascii=False, sort_keys=True)


def amount_claims(
    document: Any, orgnr: str, run_id: str, source: SourceRecord,
) -> tuple[list[EvidenceRecord], list[Fact]]:
    evidence, facts = [], []
    for pointer, entry in amount_entries(document, orgnr).items():
        ev = EvidenceRecord(
            source_id=source.source_id, source_type=source.source_type, authority_tier=source.authority_tier,
            url=source.url, source_title="Brønnøysundregistrene — Regnskapsregisteret",
            org_number=orgnr, entity_verdict="VERIFIED", retrieved_at=source.retrieved_at,
            content_hash=source.content_hash, evidence_text=amount_display(entry),
            locator=JsonNumberLocator(
                pointer=pointer, raw_value=entry["source_number"], record_pointer=entry["record_pointer"],
                record_id=entry["record_id"],
            ),
            entity_match_details={"extraction_rule": AMOUNT_RULE, "registry": "brreg_regnskap"},
        )
        evidence.append(ev)
        facts.append(Fact(
            org_number=orgnr, run_id=run_id, category="financials", field=entry["field"],
            value=entry["value"], normalized_value=entry["value"], currency=entry["currency"],
            unit=AMOUNT_UNIT, reporting_period=entry["period_start"] + "/" + entry["period_end"],
            subject_scope="legal_entity", valid_from=entry["period_start"], valid_to=entry["period_end"],
            source_id=source.source_id, evidence_id=ev.evidence_id, retrieved_at=source.retrieved_at,
            entity_verdict="VERIFIED", status="EXTRACTED", fact_confidence=0.0,
        ))
    return evidence, facts


def verify_amount_support(fact: Fact, source: SourceRecord, evidence: EvidenceRecord, body: bytes) -> None:
    locator = evidence.locator
    if (not isinstance(locator, JsonNumberLocator) or fact.category != "financials"
            or fact.field not in AMOUNT_PATHS or fact.subject_scope != "legal_entity"
            or fact.item_key is not None or fact.unit != AMOUNT_UNIT
            or fact.entity_verdict != "VERIFIED" or evidence.entity_verdict != "VERIFIED"
            or evidence.entity_match_details.get("extraction_rule") != AMOUNT_RULE):
        raise ValueError("unsupported monetary claim contract")
    _require_accounts_capture(source, fact.org_number, locator.record_id)
    entry = amount_entries(parse_accounts_json(body), fact.org_number).get(locator.pointer)
    if entry is None:
        raise ValueError("amount pointer is not an independently supported statement field")
    if (entry["field"] != fact.field or entry["source_number"] != locator.raw_value
            or entry["record_pointer"] != locator.record_pointer or entry["record_id"] != locator.record_id):
        raise ValueError("amount locator differs from retained statement")
    if (type(fact.value) is not str or fact.value != entry["value"] or fact.normalized_value != entry["value"]
            or fact.currency != entry["currency"]
            or fact.reporting_period != entry["period_start"] + "/" + entry["period_end"]
            or fact.valid_from != entry["period_start"] or fact.valid_to != entry["period_end"]
            or evidence.evidence_text != amount_display(entry)):
        raise ValueError("amount value or qualifiers differ from retained statement")

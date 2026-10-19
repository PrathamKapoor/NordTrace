"""Brreg (Brønnøysundregistrene) adapters — live, parsed, evidence-backed.

Endpoints used (all public, no credentials):
  /enheter/{orgnr}                    entity identity (Tier 0)
  /enheter/{orgnr}/roller             roles/board (Tier 0)
  /underenheter?overordnetEnhet=      branch units (Tier 0)
  /regnskapsregisteret/regnskap/{orgnr}  annual accounts (Tier 0)

Every successful retrieval becomes a SourceRecord + EvidenceRecord; extracted
data becomes Fact rows in the ledger. Nothing is fabricated: missing fields
are simply absent, and 404s produce not_found terminal states upstream.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlsplit

from nordtrace.core.budget import BudgetManager
from nordtrace.core.config import settings
from nordtrace.core.evidence import (
    IDENTITY_PATHS,
    normalize_registry_value,
    normalize_subunit,
    parse_json_body,
    require_registry_identity_acquisition,
    resolve_pointer,
)
from nordtrace.core.financial import JsonNumber, parse_accounts_json
from nordtrace.core.models import (
    CompanyIdentity,
    EvidenceRecord,
    Fact,
    FactStatus,
    JsonPointerLocator,
    MatchVerdict,
    SourceRecord,
    SourceType,
    utcnow,
)
from nordtrace.core.orgnr import validate_orgnr
from nordtrace.core.request_gateway import RequestGateway

ROLE_LABELS_NO = {
    "DAGL": "daglig leder",
    "LEDE": "styreleder",
    "MEDL": "styremedlem",
    "NEST": "nestleder",
    "VVAR": "varamedlem",
    "OBS": "observatør",
    "KOMP": "komplementar",
    "INNH": "innehaver",
    "BEST": "bestyrer",
    "BOBE": "bobestyrer",
    "BEDR": "bedriftsfører",
    "DTPA": "deltakende partner",
    "KONT": "kontaktperson",
    "HFOR": "hovedforetakrepresentant",
    "HFRE": "hovedforetakrepresentant",
    "SAMF": "samlagsleder",
    "SIFE": "signaturrett felles",
    "REVI": "revisor",
    "AREV": "revisor (godkjent)",
    "FREP": "revisor (regnskapsfører)",
}


@dataclass
class BranchResult:
    evidence: List[EvidenceRecord] = dc_field(default_factory=list)
    facts: List[Fact] = dc_field(default_factory=list)
    sources: List[SourceRecord] = dc_field(default_factory=list)
    rejected: List[dict] = dc_field(default_factory=list)
    page_states: Dict[str, str] = dc_field(default_factory=dict)
    state: str = "not_available"
    completeness: str = "unknown"
    reason: str = "No subunit acquisition completed."


def _address_line(addr: Optional[Dict[str, Any]]) -> Optional[str]:
    if not addr:
        return None
    parts = [
        " ".join(addr.get("adresse") or []),
        addr.get("postnummer"),
        addr.get("poststed"),
    ]
    return " ".join(str(p) for p in parts if p) or None


class BrregAdapter:
    """Tier-0 registry adapter. All HTTP via RequestGateway (budget-enforced)."""

    source_type = SourceType.REGISTRY.value
    authority_tier = 0

    def __init__(self, gateway: RequestGateway, budget: BudgetManager):
        self.gateway = gateway
        self.budget = budget

    # ------------------------------------------------------------------ entity
    async def fetch_entity(
        self, org_number: str, run_id: str
    ) -> Tuple[Optional[CompanyIdentity], Optional[SourceRecord], Optional[EvidenceRecord], str]:
        """Canonical identity. Returns (identity, source, evidence, terminal_hint).

        terminal_hint: 'found' | 'not_found' | 'failed' | 'blocked' | 'ambiguous'
        """
        url = f"{settings.brreg_base_url}/enheter/{org_number}"
        source = await self.gateway.fetch(
            url,
            stage="identity",
            company=org_number,
            source_type=self.source_type,
            authority_tier=0,
            allowed_domains=[urlsplit(url).hostname or ""],
            allowed_schemes=[urlsplit(url).scheme],
            allowed_origins=[f"{urlsplit(url).scheme}://{urlsplit(url).netloc}"],
        )
        if source.access_status == "success" or source.http_status == 404:
            try:
                require_registry_identity_acquisition(source, org_number)
            except ValueError as error:
                source.error_detail = str(error)
                return None, source, None, "ambiguous"
        if source.access_status != "success":
            hint = {
                "failed": "failed",
                "timeout": "failed",
                "blocked": "blocked",
                "robots_denied": "blocked",
                "rate_limited": "blocked",  # circuit OPEN: temporarily unavailable
            }.get(source.access_status, "failed")
            if source.http_status == 404:
                return None, source, None, "not_found"
            return None, source, None, hint

        cached = self.gateway.get_content(source.url or "")
        try:
            data = parse_json_body(cached.content if cached else b"")
        except ValueError as error:
            source.error_detail = f"registry identity JSON rejected: {error}"
            return None, source, None, "failed"

        if not isinstance(data, dict):
            source.error_detail = "registry identity schema mismatch"
            return None, source, None, "failed"
        returned = validate_orgnr(data.get("organisasjonsnummer", ""))
        requested = validate_orgnr(org_number)
        if not returned.valid or returned.value != requested.value:
            source.error_detail = (
                "registry response identifier absent, invalid or different from requested entity"
            )
            return None, source, None, "ambiguous"

        name = data.get("navn")
        if not isinstance(name, str) or not name.strip():
            source.error_detail = "registry identity name missing or invalid"
            return None, source, None, "failed"

        identity = self._parse_entity(data, org_number)
        evidence = EvidenceRecord(
            source_id=source.source_id,
            url=source.url,
            source_title="Brønnøysundregistrene — Enhetsregisteret",
            source_type=self.source_type,
            authority_tier=0,
            retrieved_at=source.retrieved_at,
            evidence_text=f"Enhetsregisteret: {data.get('navn', '')} (orgnr {org_number}), "
            f"organisasjonsform {data.get('organisasjonsform', {}).get('kode', '?')}",
            content_hash=source.content_hash,
            entity_verdict=MatchVerdict.VERIFIED.value,
            org_number=org_number,
            entity_match_details={"registry": "brreg", "orgnr": org_number},
        )
        return identity, source, evidence, "found"

    def _parse_entity(self, d: Dict[str, Any], org_number: str) -> CompanyIdentity:
        form = d.get("organisasjonsform") or {}
        nace = d.get("naeringskode1") or {}
        addr = d.get("forretningsadresse") or d.get("postadresse") or {}
        kap = d.get("kapital") or {}
        employees = d.get("antallAnsatte")
        under_avvikling = d.get("underAvvikling") if isinstance(d.get("underAvvikling"), bool) else None
        konkurs = d.get("konkurs") if isinstance(d.get("konkurs"), bool) else None
        status = normalize_registry_value(d, "brreg-status-v1")
        return CompanyIdentity(
            organisation_number=org_number,
            legal_name=d.get("navn") or "",
            organisation_form=form.get("kode"),
            organisation_form_description=form.get("beskrivelse"),
            status=status,
            registered_address=_address_line(d.get("forretningsadresse")),
            postal_address=_address_line(d.get("postadresse")),
            municipality=addr.get("kommune"),
            postal_code=addr.get("postnummer"),
            industry_code=nace.get("kode"),
            industry_description=nace.get("beskrivelse"),
            website=self._normalize_website(d.get("hjemmeside")),
            registration_date=d.get("registreringsdatoEnhetsregisteret"),
            employee_count=employees if type(employees) is int and employees >= 0 else None,
            share_capital=kap.get("belop"),
            share_capital_currency=kap.get("valuta"),
            number_of_shares=kap.get("antallAksjer"),
            is_part_of_concern=d.get("erIKonsern") if isinstance(d.get("erIKonsern"), bool) else None,
            bankrupt=konkurs,
            under_liquidation=under_avvikling,
            deleted_date=d.get("slettedato"),
            last_verified_at=utcnow().isoformat(),
        )

    def identity_claims(
        self, identity: CompanyIdentity, source: SourceRecord, run_id: str,
    ) -> tuple[List[EvidenceRecord], List[Fact]]:
        """One schema-qualified pointer per atomic field; never a generated quote."""
        cached = self.gateway.get_content(source.url or "")
        document = parse_json_body(cached.content if cached else b"")
        evidences: List[EvidenceRecord] = []
        facts: List[Fact] = []
        for field, (pointers, normalization) in IDENTITY_PATHS.items():
            for pointer in pointers:
                try:
                    raw = resolve_pointer(document, pointer)
                    value = normalize_registry_value(raw, normalization)
                except (ValueError, TypeError):
                    continue
                if value is None or value == "" or value == "unknown":
                    continue
                # The structured identity and claim must agree on normalization.
                if value != getattr(identity, field):
                    continue
                evidence = EvidenceRecord(
                    source_id=source.source_id, url=source.url,
                    source_title="Brønnøysundregistrene — Enhetsregisteret",
                    source_type=source.source_type, authority_tier=source.authority_tier,
                    retrieved_at=source.retrieved_at, content_hash=source.content_hash,
                    org_number=identity.organisation_number, entity_verdict=MatchVerdict.VERIFIED.value,
                    evidence_text=json.dumps(raw, ensure_ascii=False, sort_keys=True),
                    locator=JsonPointerLocator.model_validate({
                        "kind": "json_pointer", "pointer": pointer, "raw_value": raw,
                        "normalization": normalization,
                    }),
                    entity_match_details={"registry": "brreg", "orgnr": identity.organisation_number},
                )
                evidences.append(evidence)
                facts.append(Fact(
                    org_number=identity.organisation_number, run_id=run_id, category="identity", field=field,
                    subject_scope="legal_entity",
                    value=value, normalized_value=value, source_id=source.source_id,
                    evidence_id=evidence.evidence_id, retrieved_at=source.retrieved_at,
                    entity_verdict=MatchVerdict.VERIFIED.value, fact_confidence=0.99,
                ))
                break
        return evidences, facts

    @staticmethod
    def _normalize_website(raw: Optional[str]) -> Optional[str]:
        if not raw:
            return None
        w = raw.strip()
        if "://" not in w:
            w = "https://" + w
        # lowercase host only; keep path case
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(w)
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, "")) or None

    # ------------------------------------------------------------------ roles
    async def fetch_roles(
        self, org_number: str, run_id: str
    ) -> Tuple[List[EvidenceRecord], List[Fact], Optional[SourceRecord]]:
        """Board/management roles → leadership facts."""
        url = f"{settings.brreg_base_url}/enheter/{org_number}/roller"
        source = await self.gateway.fetch(
            url,
            stage="roles",
            company=org_number,
            source_type=self.source_type,
            authority_tier=0,
            allowed_domains=[urlsplit(url).hostname or ""],
            allowed_schemes=[urlsplit(url).scheme],
            allowed_origins=[f"{urlsplit(url).scheme}://{urlsplit(url).netloc}"],
        )
        if source.access_status != "success":
            return [], [], source
        cached = self.gateway.get_content(source.url or "")
        try:
            data = parse_json_body(cached.content if cached else b"")
        except ValueError as error:
            source.error_detail = f"registry roles JSON rejected: {error}"
            return [], [], source

        evidences: List[EvidenceRecord] = []
        facts: List[Fact] = []
        now = utcnow().isoformat()
        seen_persons: Dict[str, str] = {}  # dedupe roles per person

        for group in data.get("rollegrupper", []):
            grp_code = (group.get("type") or {}).get("kode", "")
            for rolle in group.get("roller", []):
                if rolle.get("avregistrert"):
                    continue
                person = rolle.get("person") or {}
                navn = person.get("navn") or {}
                fn_, mn_, en_ = navn.get("fornavn", ""), navn.get("mellomnavn", ""), navn.get("etternavn", "")
                name = " ".join(f"{fn_} {mn_} {en_}".split())
                if not name:
                    continue
                role_code = (rolle.get("type") or {}).get("kode", grp_code)
                role_desc = (rolle.get("type") or {}).get("beskrivelse") or ROLE_LABELS_NO.get(
                    role_code, role_code
                )
                slot = f"{role_code}|{name}"
                if slot in seen_persons:
                    continue
                seen_persons[slot] = name

                ev = EvidenceRecord(
                    source_id=source.source_id,
                    url=source.url,
                    source_title="Brønnøysundregistrene — Roller",
                    source_type=self.source_type,
                    authority_tier=0,
                    retrieved_at=source.retrieved_at,
                    evidence_text=f"{name} er registrert som {role_desc} (rollegruppe: {grp_code})",
                    content_hash=source.content_hash,
                    entity_verdict=MatchVerdict.VERIFIED.value,
                    org_number=org_number,
                    entity_match_details={"registry": "brreg_roller"},
                )
                evidences.append(ev)
                facts.append(
                    Fact(
                        org_number=org_number,
                        run_id=run_id,
                        category="leadership",
                        field=f"role:{role_code}:{name}",  # person-distinguished slot
                        value={
                            "name": name,
                            "role": role_desc,
                            "birth_year": person.get("fodselsaar")
                            or (person.get("fodselsdato") or "")[:4]
                            or None,
                        },
                        normalized_value=f"{role_desc}:{name}",
                        source_id=source.source_id,
                        evidence_id=ev.evidence_id,
                        retrieved_at=now,
                        entity_verdict=MatchVerdict.VERIFIED.value,
                        fact_confidence=0.99,
                        status=FactStatus.PUBLISHED.value,
                    )
                )
        return evidences, facts, source

    # ------------------------------------------------------------------ accounts
    async def fetch_accounts(
        self, org_number: str, run_id: str
    ) -> Tuple[List[EvidenceRecord], List[Fact], Optional[SourceRecord], str]:
        """Annual accounts from the public regnskapsregisteret.

        Returns (evidences, facts, source, status) where status is one of
        found/not_found/failed/blocked/ambiguous. Found means candidates only;
        monetary publication remains withheld pending units and value support.
        """
        url = f"{settings.brreg_regnskap_url}/{org_number}"
        source = await self.gateway.fetch(
            url,
            stage="financials",
            company=org_number,
            source_type=SourceType.REGISTRY_ACCOUNTS.value,
            authority_tier=0,
            allowed_domains=[urlsplit(url).hostname or ""],
            allowed_schemes=[urlsplit(url).scheme],
            allowed_origins=[f"{urlsplit(url).scheme}://{urlsplit(url).netloc}"],
        )
        if source.access_status != "success":
            if source.http_status in (404, 410):
                return [], [], source, "not_found"
            if source.access_status in ("blocked", "robots_denied", "rate_limited"):
                return [], [], source, "blocked"
            return [], [], source, "failed"

        cached = self.gateway.get_content(source.url or "")
        try:
            payload = parse_accounts_json(cached.content if cached else b"")
        except ValueError as error:
            source.error_detail = f"accounts JSON rejected: {error}"
            return [], [], source, "failed"
        items = payload if isinstance(payload, list) else [payload]
        if not items:
            return [], [], source, "not_found"

        if any(not isinstance(item, dict) for item in items):
            source.error_detail = "accounts response schema mismatch"
            return [], [], source, "failed"
        # Scope is selected before chronology: a newer consolidated report must
        # never become the legal entity's own accounts. Unknown qualifiers abstain.
        legal = []
        for index, record in enumerate(items):
            entity = record.get("virksomhet")
            if not isinstance(entity, dict):
                continue
            raw_org = entity.get("organisasjonsnummer")
            subject = validate_orgnr(raw_org) if isinstance(raw_org, str) else None
            if subject is None or not subject.valid or subject.value != org_number:
                continue
            if record.get("regnskapstype") == "SELSKAP":
                legal.append((index, record))
            elif record.get("regnskapstype") != "KONSERN":
                source.error_detail = "accounts entity scope is unresolved"
                return [], [], source, "ambiguous"
        if not legal:
            source.error_detail = "no exact legal-entity accounts record"
            return [], [], source, "ambiguous"

        def dates(record: dict) -> tuple[str, str]:
            period = record.get("regnskapsperiode")
            if not isinstance(period, dict):
                raise ValueError("accounting period missing")
            start, end = period.get("fraDato"), period.get("tilDato")
            if (not isinstance(start, str) or not isinstance(end, str)
                    or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", start)
                    or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", end)):
                raise ValueError("complete explicit accounting dates required")
            if date.fromisoformat(start) > date.fromisoformat(end):
                raise ValueError("accounting period reversed")
            return start, end

        try:
            periods = {index: dates(record) for index, record in legal}
        except ValueError as error:
            source.error_detail = f"accounts qualifiers unresolved: {error}"
            return [], [], source, "ambiguous"
        latest_end = max(periods[index][1] for index, _ in legal)
        newest = [(index, record) for index, record in legal if periods[index][1] == latest_end]
        if any(record != newest[0][1] for _, record in newest[1:]):
            source.error_detail = "competing accounts records for the same latest period"
            return [], [], source, "ambiguous"
        index, latest = newest[0]
        currency = latest.get("valuta")
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            source.error_detail = "explicit source currency missing or invalid"
            return [], [], source, "ambiguous"
        start, end = periods[index]
        period_label = f"{start}/{end}"
        periode = latest["regnskapsperiode"]

        # Financial diagnostics use per-field lexical numbers, not a rounded
        # whole-record locator. No supported unit/scale rule exists yet.
        paths = {
            "revenue": (
                "resultatregnskapResultat", "driftsresultat", "driftsinntekter", "sumDriftsinntekter",
            ),
            "operating_result": ("resultatregnskapResultat", "driftsresultat", "driftsresultat"),
            "annual_result": ("resultatregnskapResultat", "aarsresultat"),
            "total_assets": ("eiendeler", "sumEiendeler"),
            "equity": ("egenkapitalGjeld", "egenkapital", "sumEgenkapital"),
            "total_liabilities": ("egenkapitalGjeld", "gjeldOversikt", "sumGjeld"),
        }
        evidences, facts = [], []
        invalid = False
        for field, path in paths.items():
            value = latest
            for key in path:
                if value is None:
                    break
                if not isinstance(value, dict):
                    invalid = True
                    value = None
                    break
                value = value.get(key)
            if value is None:
                continue
            if not isinstance(value, JsonNumber):
                invalid = True
                continue
            try:
                exact = value.decimal_text()
            except ValueError:
                invalid = True
                continue
            pointer = (f"/{index}" if isinstance(payload, list) else "") + "/" + "/".join(path)
            journal = latest.get("journalnr")
            journal = journal.lexeme if isinstance(journal, JsonNumber) else journal
            if not isinstance(journal, str):
                journal = None
            display = {
                "source_number": value.lexeme, "currency": currency,
                "period_start": start, "period_end": end, "scope": latest["regnskapstype"],
            }
            ev = EvidenceRecord(
                source_id=source.source_id, url=source.url,
                source_title="Brønnøysundregistrene — Regnskapsregisteret",
                source_type=SourceType.REGISTRY_ACCOUNTS.value, authority_tier=0,
                retrieved_at=source.retrieved_at, content_hash=source.content_hash,
                evidence_text=json.dumps(display, ensure_ascii=False, sort_keys=True),
                org_number=org_number, entity_verdict=MatchVerdict.VERIFIED.value,
                entity_match_details={
                    "registry": "brreg_regnskap", "journalnr": journal,
                    "regnskapstype": latest["regnskapstype"], "publication_support": "unimplemented",
                    "unit_scale_basis": "unresolved", "field_pointer": pointer,
                    "raw_number_lexeme": value.lexeme, "number_representation": "json-number-decimal-v1",
                },
            )
            evidences.append(ev)
            facts.append(Fact(
                org_number=org_number, run_id=run_id, category="financials", field=field,
                value=exact, normalized_value=exact, currency=currency, reporting_period=period_label,
                subject_scope="legal_entity", valid_from=periode.get("fraDato"),
                valid_to=periode.get("tilDato"),
                source_id=source.source_id, evidence_id=ev.evidence_id, retrieved_at=source.retrieved_at,
                entity_verdict=MatchVerdict.VERIFIED.value, fact_confidence=0.0,
                status=FactStatus.EXTRACTED.value,
            ))
        if invalid:
            source.error_detail = "unsupported monetary value or accounting field shape"
        return evidences, facts, source, "found" if facts else "ambiguous" if invalid else "not_found"

    # ------------------------------------------------------------------ branches
    async def fetch_underenheter(
        self, org_number: str, run_id: str
    ) -> BranchResult:
        """Bounded pages of explicit parent→registered-subunit relationships.

        Construct page URLs ourselves; downloaded links have no execution authority.
        Already supported records survive incomplete pagination.
        """
        result = BranchResult()
        target = validate_orgnr(org_number)
        if not target.valid:
            result.state, result.reason = "ambiguous", "Invalid parent organisation number."
            return result
        seen: Dict[str, dict] = {}
        totals = None
        raw_count = 0
        for number in range(settings.brreg_branch_max_pages):
            if not self.budget.can_make_request():
                result.state, result.reason = "blocked", "Budget/deadline stopped subunit pagination."
                break
            query = urlencode({"overordnetEnhet": target.value, "size": settings.brreg_branch_page_size,
                               "page": number, "sort": "organisasjonsnummer,ASC"})
            url = f"{settings.brreg_base_url}/underenheter?{query}"
            source = await self.gateway.fetch(
                url, stage="locations", company=target.value, source_type=self.source_type, authority_tier=0,
                allowed_domains=[urlsplit(url).hostname or ""], allowed_schemes=[urlsplit(url).scheme],
                allowed_origins=[f"{urlsplit(url).scheme}://{urlsplit(url).netloc}"],
            )
            result.sources.append(source)
            result.page_states[source.source_id] = "available"
            if source.access_status != "success":
                result.state = "blocked" if source.access_status in (
                    "blocked", "robots_denied", "rate_limited",
                ) else "failed"
                if source.http_status in (404, 410):
                    result.state = "not_available"
                result.reason = source.error_detail or "Subunit page acquisition failed."
                result.page_states[source.source_id] = result.state
                break
            cached = self.gateway.get_content(source.url or "")
            try:
                data = parse_json_body(cached.content if cached else b"")
                embedded = data.get("_embedded", {})
                units = embedded.get("underenheter", [])
                if not isinstance(units, list):
                    raise ValueError("subunit collection must be a list")
            except (ValueError, AttributeError):
                result.state, result.reason = "failed", "Subunit response schema/JSON invalid."
                result.page_states[source.source_id] = "failed"
                break
            raw_count += len(units)
            metadata = data.get("page")
            declared_size = metadata.get("size") if isinstance(metadata, dict) else None
            if (len(units) > settings.brreg_branch_page_size or
                    (type(declared_size) is int and declared_size > settings.brreg_branch_page_size)):
                result.state, result.reason = "failed", "Response exceeds configured subunit page size."
                result.page_states[source.source_id] = "failed"
                break
            for index, raw in enumerate(units):
                try:
                    value = normalize_subunit(raw)
                    if value["parent_orgnr"] != target.value:
                        raise ValueError("subunit record belongs to another parent")
                except (ValueError, TypeError) as error:
                    result.page_states[source.source_id] = "ambiguous"
                    result.rejected.append({"source_id": source.source_id, "index": index,
                                            "reason": str(error)})
                    continue
                item = value["orgnr"]
                if item in seen:
                    result.page_states[source.source_id] = "ambiguous"
                    result.rejected.append({"source_id": source.source_id, "index": index,
                                            "reason": "Repeated subunit across pagination."})
                    if value == seen[item]:
                        continue
                seen[item] = value
                evidence = EvidenceRecord(
                    source_id=source.source_id, url=source.url,
                    source_title="Brønnøysundregistrene — Underenheter", source_type=self.source_type,
                    authority_tier=0, retrieved_at=source.retrieved_at,
                    evidence_text=json.dumps(raw, ensure_ascii=False, sort_keys=True),
                    content_hash=source.content_hash, entity_verdict=MatchVerdict.VERIFIED.value,
                    org_number=target.value,
                    locator=JsonPointerLocator(pointer=f"/_embedded/underenheter/{index}", raw_value=raw,
                                               normalization="brreg-subunit-v1"),
                    entity_match_details={"underenhet": item, "overordnetEnhet": value["parent_orgnr"]},
                )
                result.evidence.append(evidence)
                result.facts.append(Fact(
                    org_number=target.value, run_id=run_id, category="locations", field="branch",
                    item_key=item, subject_scope="legal_entity", value=value, normalized_value=value,
                    source_id=source.source_id, evidence_id=evidence.evidence_id,
                    retrieved_at=source.retrieved_at, entity_verdict=MatchVerdict.VERIFIED.value,
                    fact_confidence=0.99,
                ))
            metadata = data.get("page")
            if (not isinstance(metadata, dict) or any(type(metadata.get(key)) is not int for key in (
                "number", "size", "totalElements", "totalPages",
            )) or metadata["number"] != number or metadata["size"] <= 0
                    or metadata["totalPages"] < 0 or metadata["totalElements"] < 0):
                result.state, result.reason = "failed", "Subunit pagination metadata invalid."
                result.page_states[source.source_id] = "failed"
                break
            expected_pages = (metadata["totalElements"] + metadata["size"] - 1) // metadata["size"]
            if (len(units) > metadata["size"] or
                    metadata["totalPages"] not in ({0, 1} if expected_pages == 0 else {expected_pages})):
                result.state, result.reason = "failed", "Subunit page counts are inconsistent."
                result.page_states[source.source_id] = "failed"
                break
            current_totals = (metadata["totalElements"], metadata["totalPages"], metadata["size"])
            if totals is not None and totals != current_totals:
                result.state, result.reason = "ambiguous", "Subunit pagination changed during acquisition."
                result.page_states[source.source_id] = "ambiguous"
                break
            totals = current_totals
            if number + 1 >= metadata["totalPages"]:
                if raw_count != metadata["totalElements"] or result.rejected:
                    result.state = "ambiguous"
                    result.reason = "Subunit collection incomplete or rejected records."
                    break
                result.completeness = "complete"
                result.state = "available" if result.facts else "not_available"
                result.reason = "All reported subunit pages traversed and parent mappings validated."
                return result
        else:
            result.state, result.reason = "blocked", "Configured subunit page limit reached."
        result.completeness = "partial" if result.sources else "unknown"
        return result

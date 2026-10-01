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

from typing import Any, Dict, List, Optional, Tuple

from nordtrace.core.budget import BudgetManager
from nordtrace.core.config import settings
from nordtrace.core.models import (
    CompanyIdentity,
    EvidenceRecord,
    Fact,
    FactStatus,
    MatchVerdict,
    SourceRecord,
    SourceType,
    utcnow,
)
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

        terminal_hint: 'found' | 'not_found' | 'failed' | 'blocked'
        """
        url = f"{settings.brreg_base_url}/enheter/{org_number}"
        source = await self.gateway.fetch(
            url,
            stage="identity",
            company=org_number,
            source_type=self.source_type,
            authority_tier=0,
        )
        if source.access_status != "success":
            hint = {
                "failed": "failed",
                "timeout": "failed",
                "blocked": "blocked",
                "robots_denied": "blocked",
            }.get(source.access_status, "failed")
            if source.http_status == 404:
                return None, source, None, "not_found"
            return None, source, None, hint

        cached = self.gateway.get_content(source.url or "")
        text = cached.text if cached else ""
        try:
            import json

            data = json.loads(text)
        except ValueError:
            return None, source, None, "failed"

        # Registry 404s sometimes come as JSON with no navn
        if not data.get("navn") and source.http_status == 200:
            # registry returns 404 for missing; defensive
            return None, source, None, "not_found"

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
        slettet = bool(d.get("slettedato"))
        under_avvikling = bool(d.get("underAvvikling"))
        konkurs = bool(d.get("konkurs"))
        if slettet:
            status = "deleted"
        elif konkurs:
            status = "bankrupt"
        elif under_avvikling:
            status = "under_liquidation"
        else:
            status = "active"
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
            employee_count=d.get("antallAnsatte"),
            share_capital=kap.get("belop"),
            share_capital_currency=kap.get("valuta"),
            number_of_shares=kap.get("antallAksjer"),
            is_part_of_concern=bool(d.get("erIKonsern")),
            bankrupt=konkurs,
            under_liquidation=under_avvikling,
            deleted_date=d.get("slettedato"),
            last_verified_at=utcnow().isoformat(),
        )

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
        )
        if source.access_status != "success":
            return [], [], source
        cached = self.gateway.get_content(source.url or "")
        try:
            import json

            data = json.loads(cached.text if cached else "")
        except ValueError:
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
        found/not_found/failed/blocked. Currency + period always from the source.
        """
        url = f"{settings.brreg_regnskap_url}/{org_number}"
        source = await self.gateway.fetch(
            url,
            stage="financials",
            company=org_number,
            source_type=SourceType.REGISTRY_ACCOUNTS.value,
            authority_tier=0,
        )
        if source.access_status != "success":
            if source.http_status == 404:
                return [], [], source, "not_found"
            return [], [], source, "failed"

        cached = self.gateway.get_content(source.url or "")
        try:
            import json

            payload = json.loads(cached.text if cached else "")
        except ValueError:
            return [], [], source, "failed"
        items = payload if isinstance(payload, list) else [payload]
        if not items:
            return [], [], source, "not_found"

        # Use the latest accounting period available; the endpoint returns the
        # latest filed entry (multi-period entries become separate fact slots
        # via their reporting_period labels)
        def period_end(r: Dict[str, Any]) -> str:
            return (r.get("regnskapsperiode") or {}).get("tilDato", "")

        latest = max(items, key=period_end)
        # Sanity: the record must reference the requested orgnr
        v = latest.get("virksomhet") or {}
        if v.get("organisasjonsnummer") and v["organisasjonsnummer"] != org_number:
            return [], [], source, "not_found"

        periode = latest.get("regnskapsperiode") or {}
        currency = latest.get("valuta") or "NOK"
        period_str = periode.get("tilDato", "")
        period_label = f"FY{period_str[:4]}" if period_str else None

        ev = EvidenceRecord(
            source_id=source.source_id,
            url=source.url,
            source_title="Brønnøysundregistrene — Regnskapsregisteret",
            source_type=SourceType.REGISTRY_ACCOUNTS.value,
            authority_tier=0,
            retrieved_at=source.retrieved_at,
            evidence_text=(
                f"Årsregnskap {period_label or period_str} for "
                f"{v.get('organisasjonsnummer', org_number)} "
                f"({v.get('organisasjonsform', '')}), valuta {currency}, "
                f"journalnr {latest.get('journalnr', '?')}"
            ),
            content_hash=source.content_hash,
            entity_verdict=MatchVerdict.VERIFIED.value,
            org_number=org_number,
            entity_match_details={"registry": "brreg_regnskap", "journalnr": latest.get("journalnr")},
        )

        rr = latest.get("resultatregnskapResultat") or {}
        drift = rr.get("driftsresultat") or {}
        eg = latest.get("egenkapitalGjeld") or {}
        eiendeler = latest.get("eiendeler") or {}

        def fin_fact(field: str, value, unit: Optional[str] = None) -> Optional[Fact]:
            if value is None:
                return None
            return Fact(
                org_number=org_number,
                run_id=run_id,
                category="financials",
                field=field,
                value=value,
                normalized_value=value,
                currency=currency,
                reporting_period=period_label,
                valid_from=periode.get("fraDato"),
                valid_to=periode.get("tilDato"),
                source_id=source.source_id,
                evidence_id=ev.evidence_id,
                retrieved_at=utcnow().isoformat(),
                entity_verdict=MatchVerdict.VERIFIED.value,
                fact_confidence=0.99,
                status=FactStatus.PUBLISHED.value,
            )

        facts = [
            f
            for f in (
                fin_fact("revenue", drift.get("driftsinntekter", {}).get("sumDriftsinntekter")),
                fin_fact("operating_result", drift.get("driftsresultat")),
                fin_fact("annual_result", rr.get("aarsresultat")),
                fin_fact("total_assets", eiendeler.get("sumEiendeler")),
                fin_fact("equity", eg.get("egenkapital", {}).get("sumEgenkapital")),
                fin_fact("total_liabilities", eg.get("gjeldOversikt", {}).get("sumGjeld")),
            )
            if f
        ]
        return [ev], facts, source, "found" if facts else "not_found"

    # ------------------------------------------------------------------ branches
    async def fetch_underenheter(
        self, org_number: str, run_id: str
    ) -> Tuple[List[EvidenceRecord], List[Fact], Optional[SourceRecord]]:
        """Branch units (underenheter) — locations facts."""
        url = f"{settings.brreg_base_url}/underenheter?overordnetEnhet={org_number}&size=20"
        source = await self.gateway.fetch(
            url,
            stage="locations",
            company=org_number,
            source_type=self.source_type,
            authority_tier=0,
        )
        if source.access_status != "success":
            return [], [], source
        cached = self.gateway.get_content(source.url or "")
        try:
            import json

            data = json.loads(cached.text if cached else "")
        except ValueError:
            return [], [], source

        evidences: List[EvidenceRecord] = []
        facts: List[Fact] = []
        now = utcnow().isoformat()
        for unit in (data.get("_embedded") or {}).get("underenheter", []):
            u_orgnr = unit.get("organisasjonsnummer")
            u_name = unit.get("navn", "")
            addr = unit.get("forretningsadresse") or unit.get("postadresse") or {}
            municipality = addr.get("kommune")
            ev = EvidenceRecord(
                source_id=source.source_id,
                url=source.url,
                source_title="Brønnøysundregistrene — Underenheter",
                source_type=self.source_type,
                authority_tier=0,
                retrieved_at=source.retrieved_at,
                evidence_text=f"Underenhet {u_name} (orgnr {u_orgnr}) i {municipality or 'ukjent kommune'}",
                content_hash=source.content_hash,
                entity_verdict=MatchVerdict.VERIFIED.value,
                org_number=org_number,
                entity_match_details={"underenhet": u_orgnr},
            )
            evidences.append(ev)
            facts.append(
                Fact(
                    org_number=org_number,
                    run_id=run_id,
                    category="locations",
                    field="branch",
                    value={
                        "orgnr": u_orgnr,
                        "name": u_name,
                        "municipality": municipality,
                        "industry": (unit.get("naeringskode1") or {}).get("beskrivelse"),
                    },
                    normalized_value=f"{u_orgnr}:{municipality}",
                    source_id=source.source_id,
                    evidence_id=ev.evidence_id,
                    retrieved_at=now,
                    entity_verdict=MatchVerdict.VERIFIED.value,
                    fact_confidence=0.95,
                    status=FactStatus.PUBLISHED.value,
                )
            )
        return evidences, facts, source

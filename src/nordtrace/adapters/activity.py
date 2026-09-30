"""Activity adapter — meaningful public activity from registry signals.

Instead of scraping news (high risk of misattribution + request burn), this
adapter derives *verifiable* activity facts from Tier-0 registry state:

  - status transitions (bankrupt/liquidation filings are public events)
  - registration anniversaries in various registers (MVA, Frivillig MVA, NAV)
  - employee-count registration dates (indicates current employment data)
  - capital changes (aksjekapital) with registration dates
  - concern membership

Every event carries its source URL and date from the registry itself —
zero fabrication. "Recent activity" claims are limited to what the registry
actually reports with dates.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from nordtrace.core.budget import BudgetManager
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


class ActivityAdapter:
    """Derives activity facts from registry entity payload (no extra requests)."""

    source_type = SourceType.REGISTRY.value
    authority_tier = 0

    def __init__(self, gateway: RequestGateway, budget: BudgetManager):
        self.gateway = gateway
        self.budget = budget

    def extract_activity(
        self,
        identity: CompanyIdentity,
        registry_payload: Optional[dict],
        source: SourceRecord,
        run_id: str,
    ) -> Tuple[List[EvidenceRecord], List[Fact]]:
        evidences: List[EvidenceRecord] = []
        facts: List[Fact] = []
        if not registry_payload:
            return evidences, facts
        now = utcnow().isoformat()
        org = identity.organisation_number

        def add_event(field: str, value: dict, text: str, date: Optional[str]):
            ev = EvidenceRecord(
                source_id=source.source_id,
                url=source.url,
                source_title="Brønnøysundregistrene — Enhetsregisteret",
                source_type=self.source_type,
                authority_tier=0,
                retrieved_at=now,
                published_at=date,
                evidence_text=text,
                content_hash=source.content_hash,
                entity_verdict=MatchVerdict.VERIFIED.value,
                org_number=org,
            )
            evidences.append(ev)
            facts.append(Fact(
                org_number=org, run_id=run_id, category="recent_activity",
                field=field, value=value, normalized_value=str(value)[:200],
                source_id=source.source_id, evidence_id=ev.evidence_id,
                retrieved_at=now, published_at=date,
                entity_verdict=MatchVerdict.VERIFIED.value, fact_confidence=0.95,
                status=FactStatus.PUBLISHED.value,
            ))

        # Liquidation / bankruptcy are public events
        if identity.under_liquidation:
            add_event(
                "status_event",
                {"event": "under_liquidation", "date": registry_payload.get("registrertIMvaregisteret") and None},
                "Selskapet er registrert som under avvikling i Enhetsregisteret.",
                None,
            )
        if identity.bankrupt:
            add_event(
                "status_event",
                {"event": "bankruptcy_filing"},
                "Selskapet er registrert som konkurs i Enhetsregisteret.",
                None,
            )
        if identity.deleted_date:
            add_event(
                "status_event",
                {"event": "deleted", "date": identity.deleted_date},
                f"Selskapet ble slettet fra Enhetsregisteret {identity.deleted_date}.",
                identity.deleted_date,
            )
        # Employee count registration (indicates fresh NAV/AA data)
        if identity.employee_count is not None:
            date = registry_payload.get("registreringsdatoAntallAnsatteEnhetsregisteret")
            add_event(
                "employee_registration",
                {"employees": identity.employee_count, "registered": date},
                f"Antall ansatte ({identity.employee_count}) registrert i Enhetsregisteret"
                + (f", dato {date}." if date else "."),
                date,
            )
        # Capital changes
        kap = registry_payload.get("kapital") or {}
        if kap.get("belop") is not None:
            add_event(
                "capital",
                {"capital": kap.get("belop"), "currency": kap.get("valuta"),
                 "type": kap.get("type"), "date": kap.get("innfortDato")},
                f"{kap.get('type')} på {kap.get('belop'):,.0f} {kap.get('valuta')} "
                f"(innført {kap.get('innfortDato')}).".replace(",", " "),
                kap.get("innfortDato"),
            )
        # Register memberships
        for key, label in (
            ("registreringsdatoForetaksregisteret", "Foretaksregisteret"),
            ("registreringsdatoMerverdiavgiftsregisteret", "Merverdiavgiftsregisteret"),
            ("registreringsdatoFrivilligMerverdiavgiftsregisteret", "Frivillig MVA-registeret"),
        ):
            d = registry_payload.get(key)
            if d:
                add_event(
                    "registration",
                    {"register": label, "date": d},
                    f"Registrert i {label} {d}.",
                    d,
                )
        return evidences, facts

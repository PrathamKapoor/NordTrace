"""Legacy activity candidates from the retained official entity capture.

These candidates are withheld by publication validation: dated event semantics
and typed activity locators remain unimplemented. No accounts payload or mutable
URL cache may be substituted for the captured entity response.
"""

from __future__ import annotations

import json
from typing import List, Optional, Tuple

from nordtrace.core.budget import BudgetManager
from nordtrace.core.evidence import require_registry_identity_acquisition, verify_capture_metadata
from nordtrace.core.models import (
    CompanyIdentity,
    EvidenceRecord,
    Fact,
    FactStatus,
    JsonPointerLocator,
    MatchVerdict,
    SourceRecord,
    SourceType,
)
from nordtrace.core.orgnr import validate_orgnr
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
        source: SourceRecord,
        run_id: str,
    ) -> Tuple[List[EvidenceRecord], List[Fact]]:
        evidences: List[EvidenceRecord] = []
        facts: List[Fact] = []
        if self.gateway.repository is None:
            raise ValueError("Activity extraction requires a retained entity capture")
        captured, body = self.gateway.repository.read_capture(source.source_id)
        verify_capture_metadata(captured, source)
        org = identity.organisation_number
        require_registry_identity_acquisition(captured, org)
        if captured.access_status != "success":
            raise ValueError("Activity requires a successful entity acquisition")
        registry_payload = json.loads(body)
        if not isinstance(registry_payload, dict):
            raise ValueError("Activity entity capture must be an object")
        subject = validate_orgnr(registry_payload.get("organisasjonsnummer", ""))
        if not subject.valid or subject.value != org:
            raise ValueError("Activity capture subject differs from target entity")
        now = captured.retrieved_at

        def add_event(field: str, value: dict, text: str, date: Optional[str]):
            ev = EvidenceRecord(
                source_id=source.source_id,
                url=source.url,
                source_title="Brønnøysundregistrene — Enhetsregisteret",
                source_type=self.source_type,
                authority_tier=0,
                retrieved_at=now,
                published_at=date,
                evidence_text=json.dumps(registry_payload, ensure_ascii=False, sort_keys=True),
                locator=JsonPointerLocator(pointer="", raw_value=registry_payload),
                entity_match_details={
                    "candidate_interpretation": text, "publication_support": "unimplemented",
                },
                content_hash=source.content_hash,
                entity_verdict=MatchVerdict.VERIFIED.value,
                org_number=org,
            )
            evidences.append(ev)
            facts.append(
                Fact(
                    org_number=org,
                    run_id=run_id,
                    category="recent_activity",
                    field=field,
                    value=value,
                    normalized_value=str(value)[:200],
                    source_id=source.source_id,
                    evidence_id=ev.evidence_id,
                    retrieved_at=now,
                    published_at=date,
                    entity_verdict=MatchVerdict.VERIFIED.value,
                    fact_confidence=0.95,
                    status=FactStatus.EXTRACTED.value,
                )
            )

        # Liquidation / bankruptcy are public events
        if identity.under_liquidation:
            add_event(
                "status_event",
                {
                    "event": "under_liquidation",
                    "date": registry_payload.get("registrertIMvaregisteret") and None,
                },
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
                {
                    "capital": kap.get("belop"),
                    "currency": kap.get("valuta"),
                    "type": kap.get("type"),
                    "date": kap.get("innfortDato"),
                },
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

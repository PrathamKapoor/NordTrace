"""NAV Arbeidsplassen jobs adapter — live public search API.

Endpoint (public, no credentials): https://arbeidsplassen.nav.no/stillinger/api/search

Entity verification: employer names from NAV carry NO orgnr, so postings are
matched against the canonical identity via the resolver (name + municipality
corroboration). Same-name-different-company postings are rejected, never merged.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

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
    utcnow,
)
from nordtrace.core.request_gateway import RequestGateway

_BOARD_URL = "https://arbeidsplassen.nav.no/stillinger/stilling/{uuid}"


class NavJobsAdapter:
    source_type = SourceType.JOB_BOARD.value
    authority_tier = 2  # Norwegian public sector

    def __init__(self, gateway: RequestGateway, budget: BudgetManager, resolver: EntityResolver):
        self.gateway = gateway
        self.budget = budget
        self.resolver = resolver

    def search_url(self, identity: CompanyIdentity) -> str:
        name = identity.legal_name
        return f"{settings.nav_job_search_url}?q={quote(name)}&size=20"

    async def fetch_jobs(
        self, identity: CompanyIdentity, run_id: str, limit: int = 8
    ) -> Tuple[List[EvidenceRecord], List[Fact], Optional[SourceRecord], List[Dict]]:
        evidences: List[EvidenceRecord] = []
        facts: List[Fact] = []
        rejected: List[Dict] = []
        now = utcnow().isoformat()

        src = await self.gateway.fetch(
            self.search_url(identity),
            stage="jobs",
            company=identity.organisation_number,
            source_type=self.source_type,
            authority_tier=self.authority_tier,
        )
        if src.access_status != "success":
            return evidences, facts, src, rejected

        cached = self.gateway.get_content(src.url)
        try:
            import json

            data = json.loads(cached.text if cached else "")
        except ValueError:
            return evidences, facts, src, rejected

        hits = ((data.get("hits") or {}).get("hits")) or []
        published_count = 0
        for hit in hits:
            if published_count >= limit:
                break
            ad = hit.get("_source") or {}
            employer = ad.get("businessName") or ""
            title = ad.get("title") or ""
            if not employer or not title:
                continue
            # deterministic entity check: employer name must match target
            sim = self.resolver.evaluate(
                identity, candidate_name=employer, candidate_text=f"{employer} {title}",
            )
            if sim.verdict not in (MatchVerdict.VERIFIED.value, MatchVerdict.LIKELY.value):
                rejected.append({"employer": employer, "title": title,
                                 "reason": f"employer not verified: {sim.reason}"})
                continue

            locs = ad.get("locationList") or []
            municipality = (locs[0].get("municipal") if locs else None) or (locs[0].get("city") if locs else None)
            props = ad.get("properties") or {}
            deadline = props.get("applicationdue")
            ad_url = _BOARD_URL.format(uuid=hit.get("_id", ""))

            ev = EvidenceRecord(
                source_id=src.source_id,
                url=ad_url,
                source_title="NAV Arbeidsplassen — stilling",
                source_type=self.source_type,
                authority_tier=self.authority_tier,
                retrieved_at=now,
                published_at=(ad.get("published") or "")[:10] or None,
                evidence_text=f"{employer} søker {title} i {municipality or 'ukjent sted'}. "
                              f"Publisert {(ad.get('published') or '')[:10]}; søknadsfrist {deadline or 'ukjent'}.",
                content_hash=src.content_hash,
                entity_verdict=sim.verdict,
                org_number=identity.organisation_number,
                entity_match_details={"employer": employer, "match": sim.reason},
            )
            evidences.append(ev)
            facts.append(Fact(
                org_number=identity.organisation_number,
                run_id=run_id,
                category="jobs",
                field="job_posting",
                value={
                    "title": title,
                    "employer": employer,
                    "location": municipality,
                    "published": (ad.get("published") or "")[:10] or None,
                    "deadline": deadline,
                    "source": ad.get("source") or ad.get("medium"),
                    "url": ad_url,
                },
                normalized_value=f"{title}|{municipality}|{(ad.get('published') or '')[:10]}",
                source_id=src.source_id,
                evidence_id=ev.evidence_id,
                retrieved_at=now,
                published_at=(ad.get("published") or "")[:10] or None,
                entity_verdict=sim.verdict,
                fact_confidence=0.9 if sim.verdict == MatchVerdict.VERIFIED.value else 0.7,
                status=FactStatus.PUBLISHED.value,
            ))
            published_count += 1
        return evidences, facts, src, rejected

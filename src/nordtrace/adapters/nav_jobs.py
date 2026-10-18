"""NAV integration is disabled pending the documented feed and retention contract.

The former anonymous search route is retired. The current feed has employer.orgnr,
bearer authentication, update/withdrawal semantics and data-retention obligations.
A public experiment token exists; no token is fetched or used by this adapter.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from nordtrace.core.budget import BudgetManager
from nordtrace.core.entity import EntityResolver
from nordtrace.core.models import CompanyIdentity, EvidenceRecord, Fact, SourceRecord, SourceType, utcnow
from nordtrace.core.request_gateway import RequestGateway

_FEED_URL = "https://pam-stilling-feed.nav.no/api/v1/feed"


class NavJobsAdapter:
    source_type = SourceType.JOB_BOARD.value
    authority_tier = 2

    def __init__(self, gateway: RequestGateway, budget: BudgetManager, resolver: EntityResolver):
        self.gateway = gateway
        self.budget = budget
        self.resolver = resolver

    async def fetch_jobs(
        self, identity: CompanyIdentity, run_id: str, limit: int = 8,
    ) -> Tuple[List[EvidenceRecord], List[Fact], Optional[SourceRecord], List[Dict]]:
        """Return a local policy block, never an empty-vacancy finding or HTTP success."""
        reason = (
            "The documented NAV feed is not implemented: authenticated acquisition, "
            "employer.orgnr support and active/inactive update/retention handling are required. "
            "The retired anonymous search endpoint is disabled."
        )
        source = SourceRecord(
            url=_FEED_URL, source_type=self.source_type, authority_tier=self.authority_tier,
            org_number=identity.organisation_number, access_status="blocked", error_detail=reason,
            discovered_at=utcnow().isoformat(),
        )
        return [], [], source, [{"url": _FEED_URL, "code": "nav_feed_not_implemented", "reason": reason}]

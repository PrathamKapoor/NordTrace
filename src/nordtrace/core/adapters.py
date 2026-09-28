from __future__ import annotations

import requests
import httpx
from typing import Optional, Dict, Any, List
from abc import ABC, abstractmethod
from urllib.parse import urljoin

from .models import CompanyIdentity, Source, Evidence, Fact
from .config import settings


class SourceAdapter(ABC):
    source_type: str = "unknown"
    authority_tier: int = 4

    @abstractmethod
    async def resolve(self, org_nr: str, company_identity: Optional[CompanyIdentity] = None) -> List[Source]:
        ...

    @abstractmethod
    async def extract_facts(self, source: Source, company_identity: CompanyIdentity) -> List[Fact]:
        ...


class BrregAdapter(SourceAdapter):
    source_type = "registry"
    authority_tier = 0

    def __init__(self):
        self.url = settings.brreg_api_url
        self.timeout = settings.brreg_timeout

    async def resolve(self, org_nr: str, company_identity: Optional[CompanyIdentity] = None) -> List[Source]:
        url = f"{self.url}/{org_nr}"
        sources = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": settings.user_agent})
                if resp.status_code == 200:
                    data = resp.json()
                    content = resp.text
                    content_hash = Source(source_id=f"brreg_{org_nr}", url=url, domain="data.brreg.no",
                                          source_type="registry", authority_tier=0,
                                          retrieved_at=str(resp.headers.get("date")),
                                          http_status=resp.status_code, access_status="success").compute_hash(content)
                    source = Source(
                        source_id=f"brreg_{org_nr}",
                        url=url,
                        domain="data.brreg.no",
                        source_type="registry",
                        authority_tier=0,
                        retrieved_at=str(resp.headers.get("date")),
                        http_status=resp.status_code,
                        content_hash=content_hash,
                        access_status="success",
                    )
                    sources.append(source)
                    # Optionally build initial identity from data
                else:
                    source = Source(
                        source_id=f"brreg_{org_nr}",
                        url=url,
                        domain="data.brreg.no",
                        source_type="registry",
                        authority_tier=0,
                        retrieved_at=None,
                        http_status=resp.status_code,
                        content_hash=None,
                        access_status="failed",
                    )
                    sources.append(source)
        except Exception as e:
            source = Source(
                source_id=f"brreg_{org_nr}",
                url=url,
                domain="data.brreg.no",
                source_type="registry",
                authority_tier=0,
                access_status="timeout" if "timeout" in str(e).lower() else "failed",
            )
            sources.append(source)
        return sources

    async def extract_facts(self, source: Source, company_identity: CompanyIdentity) -> List[Fact]:
        facts: List[Fact] = []
        # In a real implementation, parse registry JSON into Fact objects.
        # For now, we create identity facts based on company_identity.
        from datetime import datetime
        facts.append(Fact(
            fact_id=f"identity_{company_identity.organisation_number}_registry",
            company_org_number=company_identity.organisation_number,
            category="identity",
            field="legal_name",
            value=company_identity.legal_name,
            source_id=source.source_id,
            evidence_id=f"evidence_{company_identity.organisation_number}_name",
            retrieved_at=str(datetime.now()),
            entity_confidence="VERIFIED",
            fact_confidence=0.99,
            status="PUBLISHED",
        ))
        facts.append(Fact(
            fact_id=f"identity_{company_identity.organisation_number}_org_form",
            company_org_number=company_identity.organisation_number,
            category="identity",
            field="organisation_form",
            value=company_identity.organisation_form,
            source_id=source.source_id,
            evidence_id=f"evidence_{company_identity.organisation_number}_form",
            retrieved_at=str(datetime.now()),
            entity_confidence="VERIFIED",
            fact_confidence=0.95,
            status="PUBLISHED",
        ))
        return facts

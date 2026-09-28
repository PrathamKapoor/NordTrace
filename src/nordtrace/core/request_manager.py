from __future__ import annotations

import httpx
import time
import hashlib
from typing import Optional, Dict, Any
from urllib.parse import urlparse

from nordtrace.core.budget import RequestBudget, CostTracker, RuntimeBudget
from nordtrace.core.config import settings


class RequestManager:
    def __init__(self, budget: RequestBudget):
        self.budget = budget
        self.session = httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers={
            "User-Agent": settings.user_agent,
        })
        self.request_log: list = []

    async def get(self, url: str, company: Optional[str] = None, domain: Optional[str] = None,
                  provider: Optional[str] = None, retry: int = 2) -> Optional[Dict[str, Any]]:
        if not self.budget.can_request(company=company, cost_estimate=1):
            return None
        domain = domain or urlparse(url).netloc
        for attempt in range(retry + 1):
            try:
                resp = await self.session.get(url, timeout=30.0)
                self.budget.record(company=company, domain=domain, provider=provider,
                                    success=resp.status_code == 200, retry=attempt > 0)
                if resp.status_code == 200:
                    text = resp.text
                    return {
                        "status_code": resp.status_code,
                        "text": text,
                        "hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "headers": dict(resp.headers),
                        "url": url,
                    }
                else:
                    return {
                        "status_code": resp.status_code,
                        "text": resp.text,
                        "hash": None,
                        "headers": dict(resp.headers),
                        "url": url,
                    }
            except Exception as e:
                self.budget.record(company=company, domain=domain, provider=provider,
                                    success=False, retry=attempt > 0)
                if attempt == retry:
                    return None
        return None

    async def close(self):
        await self.session.aclose()

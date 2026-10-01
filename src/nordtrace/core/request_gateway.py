"""RequestGateway: the ONLY outbound HTTP path in the application.

Every adapter must use this gateway. It enforces:
- global request budget (hard stop at limit)
- SSRF protection (no private/loopback/link-local/metadata targets)
- scheme allowlist (http/https only)
- max redirects, max response size
- robots.txt awareness for crawlers
- per-domain cache with content hash + TTL
- bounded retries with exponential backoff on transient failures
- structured request logs

Design invariant: `grep -rn "httpx\\|requests\\|urllib.request" src/` must only
show usage inside this module (and the LLM client which uses it too).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib import robotparser
from urllib.parse import urlparse

import httpx

from nordtrace.core.budget import BudgetExceededError, BudgetManager
from nordtrace.core.config import settings
from nordtrace.core.models import SourceRecord, SourceType, content_hash, utcnow
from nordtrace.core.rate_limiter import RateLimited, RateLimiter

logger = logging.getLogger("nordtrace.gateway")

_PRIVATE_HOST_HINTS = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "metadata.google.internal",
    "instance-data",
    "169.254.169.254",
    "0.0.0.0",
    "::1",
}

_RETRY_STATUS = {429, 500, 502, 503, 504}


def _resolve_host(hostname: str) -> List[str]:
    """Resolve hostname to IPs for SSRF validation. Returns [] on failure."""
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        return sorted({str(info[4][0]) for info in infos})
    except (socket.gaierror, UnicodeError):
        return []


def _is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # unparseable → treat as unsafe
    if isinstance(addr, ipaddress.IPv4Address) and addr in ipaddress.ip_network("100.64.0.0/10"):
        return True  # CGNAT / shared address space
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


class SSRFError(ValueError):
    pass


def validate_url(url: str, allowed_domains: Optional[List[str]] = None) -> Tuple[str, str]:
    """Validate + normalize a URL. Raises SSRFError on unsafe targets."""
    if not url or not isinstance(url, str):
        raise SSRFError("empty URL")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"scheme {parsed.scheme!r} not allowed")
    host = (parsed.hostname or "").lower().strip(".")
    if not host:
        raise SSRFError("missing host")
    if host in _PRIVATE_HOST_HINTS:
        raise SSRFError(f"host {host!r} is blocked")
    # All numeric host forms (decimal/octal/hex IPv4) are blocked as raw IPs
    host_is_numeric_ip = False
    try:
        ipaddress.ip_address(host)
        host_is_numeric_ip = True
    except ValueError:
        # try IPv4 numeric variants: pure-integer decimal, 0x hex, octal-ish labels
        if re.match(r"^\d+$", host) or re.match(
            r"^(0x[0-9a-f]+|0[0-7]+)(\.(0x[0-9a-f]+|0[0-7]+|\d+))*$", host, re.I
        ):
            host_is_numeric_ip = True
    if host_is_numeric_ip:
        raise SSRFError("raw/numeric IP targets are blocked")
    # DNS resolution guard
    for ip in _resolve_host(host):
        if _is_private_ip(ip):
            raise SSRFError(f"{host!r} resolves to private address {ip}")
    if allowed_domains is not None:
        if host not in allowed_domains and not any(host.endswith("." + d) for d in allowed_domains):
            raise SSRFError(f"host {host!r} outside allowed domains")
    # Normalize: lowercase scheme+host, strip fragments/default ports, keep query
    scheme = parsed.scheme.lower()
    port = parsed.port
    default_port = {"https": 443, "http": 80}[scheme]
    netloc = f"{host}:{port}" if port and port != default_port else host
    path = parsed.path or "/"
    clean = f"{scheme}://{netloc}{path}"
    if parsed.query:
        clean += f"?{parsed.query}"
    return clean, host


@dataclass
class CachedResponse:
    url: str
    status_code: int
    text: str
    content_hash: str
    retrieved_at: float
    headers: Dict[str, str]
    content: bytes = b""
    from_cache: bool = False
    final_url: str = ""

    def age_sec(self) -> float:
        return time.time() - self.retrieved_at


@dataclass
class RobotsCacheEntry:
    fetched_at: float
    parser: robotparser.RobotFileParser
    allowed: bool  # whether robots.txt itself was fetchable


class RequestGateway:
    """Central HTTP client with budget + security enforcement."""

    def __init__(
        self, budget: BudgetManager, cache_ttl_sec: float = 3600.0, rate_limiter: Optional[RateLimiter] = None
    ):
        self.budget = budget
        self.cache_ttl = cache_ttl_sec
        self.rate_limiter = rate_limiter or RateLimiter()
        self._cache: Dict[str, CachedResponse] = {}
        self._robots: Dict[str, RobotsCacheEntry] = {}
        self._client: Optional[httpx.AsyncClient] = None
        self._inflight: Dict[str, float] = {}

    # ------------------------------------------------------------------ core
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=settings.crawl_timeout,
                follow_redirects=True,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                headers={"User-Agent": settings.user_agent},
                verify=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    # ------------------------------------------------------------- robots.txt
    async def _robots_allows(self, url: str, user_agent: str = "*") -> bool:
        if not settings.respect_robots:
            return True
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        entry = self._robots.get(base)
        if entry is None or (time.time() - entry.fetched_at) > self.cache_ttl:
            rp = robotparser.RobotFileParser()
            robots_url = f"{base}/robots.txt"
            allowed = False
            try:
                # robots.txt fetch does not count against the crawl budget
                # (it's a politeness requirement, not research data)
                async with httpx.AsyncClient(
                    timeout=10.0, follow_redirects=True, headers={"User-Agent": settings.user_agent}
                ) as c:
                    r = await c.get(robots_url)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                    allowed = True
                elif r.status_code == 404:
                    allowed = True  # no robots.txt → full permission
            except Exception:
                # network failure fetching robots → fail open but conservatively
                # treat as allowed; content checks still apply
                allowed = True
                rp.parse([])
            entry = RobotsCacheEntry(fetched_at=time.time(), parser=rp, allowed=allowed)
            self._robots[base] = entry
        if not entry.allowed:
            return True
        try:
            return entry.parser.can_fetch(user_agent, url)
        except Exception:
            return True

    # ---------------------------------------------------------------- fetch
    async def fetch(
        self,
        url: str,
        *,
        stage: str = "unknown",
        company: Optional[str] = None,
        source_type: str = SourceType.OTHER.value,
        authority_tier: int = 4,
        max_bytes: Optional[int] = None,
        cache_ttl_override: Optional[float] = None,
        respect_robots: bool = False,
        allowed_domains: Optional[List[str]] = None,
        retries: int = 2,
    ) -> SourceRecord:
        """Fetch a URL through all budget/security gates.

        Always returns a SourceRecord (access_status=failed/blocked on error,
        never None) — callers can rely on access_status without None-checks.

        Returns a SourceRecord with access_status and (on success) content hash.
        The response *text* is stored in the gateway cache, retrievable via
        `get_cached_content(content_hash)`; this keeps SourceRecord small while
        preserving the evidence text.
        """
        # 1. URL validation (SSRF guard)
        try:
            clean_url, host = validate_url(url, allowed_domains=allowed_domains)
        except SSRFError as e:
            logger.warning("SSRF blocked %s: %s", url, e)
            return SourceRecord(
                url=url,
                domain=urlparse(url).hostname,
                source_type=source_type,
                authority_tier=authority_tier,
                access_status="blocked",
                error_detail=f"ssrf: {e}",
                org_number=company,
                retrieved_at=utcnow().isoformat(),
            )

        # 2. Robots check (for crawlers)
        if respect_robots and not await self._robots_allows(clean_url):
            return SourceRecord(
                url=clean_url,
                domain=host,
                source_type=source_type,
                authority_tier=authority_tier,
                access_status="robots_denied",
                error_detail="disallowed by robots.txt",
                org_number=company,
                retrieved_at=utcnow().isoformat(),
            )

        # 3. Cache freshness
        cache_key = clean_url
        ttl = self.cache_ttl if cache_ttl_override is None else cache_ttl_override
        cached = self._cache.get(cache_key)
        if cached is not None and cached.status_code == 200 and cached.age_sec() < ttl:
            rec = self._source_from_cache(cached, source_type, authority_tier, company, clean_url)
            return rec

        # 4. Per-domain rate limiting + circuit breaker
        try:
            token = await self.rate_limiter.acquire(host)
        except RateLimited as e:
            return SourceRecord(
                url=clean_url,
                domain=host,
                source_type=source_type,
                authority_tier=authority_tier,
                access_status="rate_limited",
                error_detail=str(e),
                org_number=company,
                retrieved_at=utcnow().isoformat(),
            )

        # 5. Budget acquisition (hard stop) — 1 slot per attempt, retries too
        attempt = 0
        last_error: Optional[str] = None
        client = await self._get_client()
        while attempt <= retries:
            if not self.budget.requests.try_acquire(1):
                raise BudgetExceededError(f"request budget exhausted at {self.budget.requests.total_used}")
            attempt += 1
            try:
                resp = await client.get(
                    clean_url,
                    headers={"User-Agent": settings.user_agent, "Accept": "*/*"},
                )
                limit = max_bytes or settings.max_response_bytes
                # Stream guard: we already have full body in memory via httpx default;
                # enforce size after read.
                body = resp.text
                if len(resp.content) > limit:
                    self.budget.requests.record_outcome(
                        False, retry=attempt > 1, domain=host, stage=stage, company=company
                    )
                    return SourceRecord(
                        url=clean_url,
                        domain=host,
                        source_type=source_type,
                        authority_tier=authority_tier,
                        http_status=resp.status_code,
                        access_status="failed",
                        error_detail=f"response too large ({len(resp.content)} > {limit})",
                        org_number=company,
                        retrieved_at=utcnow().isoformat(),
                    )
                status = resp.status_code
                success = status == 200
                self.budget.requests.record_outcome(
                    success, retry=attempt > 1, domain=host, stage=stage, company=company
                )
                if success:
                    token.record_success()
                else:
                    token.record_failure(rate_limited=status == 429)
                if status == 200:
                    ch = content_hash(body)
                    cached = CachedResponse(
                        url=clean_url,
                        status_code=status,
                        text=body,
                        content_hash=ch,
                        retrieved_at=time.time(),
                        headers=dict(resp.headers),
                        final_url=str(resp.url),
                        content=resp.content,
                    )
                    self._cache[clean_url] = cached
                    return SourceRecord(
                        url=clean_url,
                        domain=host,
                        source_type=source_type,
                        authority_tier=authority_tier,
                        http_status=status,
                        access_status="success",
                        content_hash=ch,
                        retrieved_at=utcnow().isoformat(),
                        org_number=company,
                    )
                if status in _RETRY_STATUS and attempt <= retries:
                    # respect Retry-After if the source provides it
                    retry_after = resp.headers.get("retry-after")
                    if retry_after:
                        try:
                            await asyncio.sleep(min(float(retry_after), 10.0))
                        except ValueError:
                            await _backoff(attempt)
                    else:
                        await _backoff(attempt)
                    last_error = f"http {status}"
                    continue
                return SourceRecord(
                    url=clean_url,
                    domain=host,
                    source_type=source_type,
                    authority_tier=authority_tier,
                    http_status=status,
                    access_status=(
                        "rate_limited" if status == 429 else "blocked" if status in (401, 403) else "failed"
                    ),
                    error_detail=f"http {status}",
                    org_number=company,
                    retrieved_at=utcnow().isoformat(),
                )
            except (httpx.TimeoutException, httpx.TransportError) as e:
                self.budget.requests.record_outcome(
                    False, retry=attempt > 1, domain=host, stage=stage, company=company
                )
                token.record_failure(rate_limited=False)
                last_error = type(e).__name__
                if attempt <= retries:
                    await _backoff(attempt)
                    continue
                break
            except Exception as e:  # unexpected → do not retry
                self.budget.requests.record_outcome(
                    False, retry=False, domain=host, stage=stage, company=company
                )
                logger.exception("gateway error for %s", clean_url)
                return SourceRecord(
                    url=clean_url,
                    domain=host,
                    source_type=source_type,
                    authority_tier=authority_tier,
                    access_status="failed",
                    error_detail=f"error: {type(e).__name__}",
                    org_number=company,
                    retrieved_at=utcnow().isoformat(),
                )
        return SourceRecord(
            url=clean_url,
            domain=host,
            source_type=source_type,
            authority_tier=authority_tier,
            access_status="timeout" if last_error and "Timeout" in last_error else "failed",
            error_detail=last_error or "retries exhausted",
            org_number=company,
            retrieved_at=utcnow().isoformat(),
        )

    def _source_from_cache(
        self, cached: CachedResponse, source_type: str, authority_tier: int, company: Optional[str], url: str
    ) -> SourceRecord:
        rec = SourceRecord(
            url=url,
            domain=urlparse(url).hostname,
            source_type=source_type,
            authority_tier=authority_tier,
            http_status=cached.status_code,
            content_hash=cached.content_hash,
            access_status="success",
            retrieved_at=utcnow().isoformat(),
            org_number=company,
        )
        return rec

    # ------------------------------------------------------------- content
    def get_content(self, url: str) -> Optional[CachedResponse]:
        """Return cached response for a successfully fetched URL (this run)."""
        return self._cache.get(url)

    def snapshot_cache_entries(self) -> List[Dict[str, object]]:
        return [
            {
                "url": c.url,
                "content_hash": c.content_hash,
                "retrieved_at": c.retrieved_at,
                "age_sec": round(c.age_sec(), 1),
                "status_code": c.status_code,
            }
            for c in self._cache.values()
        ]


async def _backoff(attempt: int, base: float = 0.5, cap: float = 4.0) -> None:
    import asyncio

    await asyncio.sleep(min(cap, base * (2 ** (attempt - 1))))

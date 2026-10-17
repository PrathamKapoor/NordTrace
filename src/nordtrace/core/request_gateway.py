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
import hashlib
import ipaddress
import logging
import re
import socket
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Dict, List, Optional, Tuple
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import httpx

from nordtrace.core.budget import BudgetExceededError, BudgetManager
from nordtrace.core.config import settings
from nordtrace.core.models import SourceRecord, SourceType, utcnow
from nordtrace.core.rate_limiter import RateLimited, RateLimiter
from nordtrace.core.repository import Repository

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


def validate_url(
    url: str, allowed_domains: Optional[List[str]] = None, allowed_schemes: Optional[List[str]] = None,
    allowed_origins: Optional[List[str]] = None,
) -> Tuple[str, str]:
    """Validate + normalize a URL. Raises SSRFError on unsafe targets."""
    if not url or not isinstance(url, str):
        raise SSRFError("empty URL")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"scheme {parsed.scheme!r} not allowed")
    if allowed_schemes is not None and parsed.scheme not in allowed_schemes:
        raise SSRFError("URL scheme outside source policy")
    if parsed.username or parsed.password:
        raise SSRFError("URL credentials are prohibited")
    host = (parsed.hostname or "").lower().strip(".")
    if not host:
        raise SSRFError("missing host")
    try:
        port = parsed.port
        if port == 0:
            raise ValueError("zero port")
        if allowed_origins is not None:
            default_ports = {"https": 443, "http": 80}
            permitted = []
            for candidate in allowed_origins:
                origin = urlparse(candidate)
                permitted.append((origin.scheme, origin.hostname,
                                  origin.port or default_ports[origin.scheme]))
            if (parsed.scheme, host, port or default_ports[parsed.scheme]) not in permitted:
                raise SSRFError("URL origin outside source policy")
    except (ValueError, KeyError) as error:
        raise SSRFError(f"invalid port/origin policy: {error}") from error
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
    addresses = _resolve_host(host)
    if not addresses:
        raise SSRFError("hostname could not be resolved safely")
    for ip in addresses:
        if _is_private_ip(ip):
            raise SSRFError(f"{host!r} resolves to private address {ip}")
    if allowed_domains is not None:
        if host not in allowed_domains and not any(host.endswith("." + d) for d in allowed_domains):
            raise SSRFError(f"host {host!r} outside allowed domains")
    # Normalize: lowercase scheme+host, strip fragments/default ports, keep query
    scheme = parsed.scheme.lower()
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
    redirect_chain: List[str] = field(default_factory=list)

    def age_sec(self) -> float:
        return time.time() - self.retrieved_at


@dataclass
class RobotsCacheEntry:
    fetched_at: float
    parser: robotparser.RobotFileParser
    allowed: bool  # whether robots.txt itself was fetchable


class ResponseLimitError(ValueError):
    pass


class PinnedTransport(httpx.AsyncBaseTransport):
    """Connect to a freshly validated numeric address, retaining TLS SNI/Host.

    The HTTP layer cannot independently re-resolve the hostname after validation.
    Environment proxy configuration is disabled on the owning client.
    """

    def __init__(self, retries: int = 0):
        self._retries = retries
        self._origins: Dict[tuple[str, str, Optional[int]], httpx.AsyncHTTPTransport] = {}

    async def aclose(self) -> None:
        await asyncio.gather(*(transport.aclose() for transport in self._origins.values()))
        self._origins.clear()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        addresses = _resolve_host(host)
        if not addresses or any(_is_private_ip(address) for address in addresses):
            raise SSRFError("connection destination could not be verified as public")
        extensions = dict(request.extensions)
        extensions["sni_hostname"] = host
        pinned = httpx.Request(
            request.method, request.url.copy_with(host=addresses[0]), headers=request.headers,
            stream=request.stream, extensions=extensions,
        )
        origin = (request.url.scheme, host, request.url.port)
        if origin not in self._origins:
            self._origins[origin] = httpx.AsyncHTTPTransport(retries=self._retries, trust_env=False)
        # Pool by the original TLS identity, never by a potentially shared IP.
        return await self._origins[origin].handle_async_request(pinned)


class RequestGateway:
    """Central HTTP client with budget + security enforcement."""

    def __init__(
        self, budget: BudgetManager, cache_ttl_sec: float = 3600.0,
        rate_limiter: Optional[RateLimiter] = None,
        repository: Optional[Repository] = None,
    ):
        self.budget = budget
        self.repository = repository
        self.cache_ttl = cache_ttl_sec
        self.rate_limiter = rate_limiter or RateLimiter()
        self._cache: Dict[str, CachedResponse] = {}
        self._robots: Dict[
            tuple[str, Optional[tuple[str, ...]], Optional[tuple[str, ...]], Optional[tuple[str, ...]]],
            RobotsCacheEntry,
        ] = {}
        self._client: Optional[httpx.AsyncClient] = None
        self._inflight: Dict[str, float] = {}

    # ------------------------------------------------------------------ core
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=settings.crawl_timeout, follow_redirects=False, trust_env=False,
                transport=PinnedTransport(retries=0),
                headers={"User-Agent": settings.user_agent},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def _robots_allows(
        self, url: str, *, company: Optional[str] = None,
        allowed_domains: Optional[List[str]] = None,
        allowed_schemes: Optional[List[str]] = None,
        allowed_origins: Optional[List[str]] = None,
    ) -> bool:
        if not settings.respect_robots:
            return True
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        key = (
            base, tuple(sorted(allowed_domains)) if allowed_domains is not None else None,
            tuple(sorted(allowed_schemes)) if allowed_schemes is not None else None,
            tuple(sorted(allowed_origins)) if allowed_origins is not None else None,
        )
        entry = self._robots.get(key)
        if entry is None or time.time() - entry.fetched_at > self.cache_ttl:
            robots_url = base + "/robots.txt"
            record = await self.fetch(
                robots_url, stage="robots", company=company, max_bytes=128 * 1024,
                retries=0, respect_robots=False, allowed_domains=allowed_domains,
                allowed_schemes=allowed_schemes,
                allowed_origins=allowed_origins,
            )
            parser = robotparser.RobotFileParser()
            cached = self.get_content(robots_url)
            if record.access_status == "success" and cached:
                parser.parse(cached.text.splitlines())
                allowed = True
            elif record.http_status in (404, 410):
                parser.parse([])
                allowed = True
            else:
                allowed = False
            entry = RobotsCacheEntry(time.time(), parser, allowed)
            self._robots[key] = entry
        return entry.allowed and entry.parser.can_fetch(settings.user_agent, url)

    async def _exchange(
        self, url: str, host: str, *, stage: str, company: Optional[str],
        max_bytes: int, retry: bool,
    ) -> httpx.Response:
        token = await self.rate_limiter.acquire(host)
        attempted = False
        reserved = False
        successful = False
        rate_limited = False
        try:
            self.budget.check()
            if not self.budget.requests.try_acquire():
                if self.budget.work_time_remaining() <= 0:
                    raise TimeoutError("shared run deadline reached during reservation")
                raise BudgetExceededError("request budget exhausted")
            reserved = True
            client = await self._get_client()
            if self.budget.work_time_remaining() <= 0:
                raise TimeoutError("run deadline reached before transport")
            attempted = True
            async with client.stream(
                "GET", url, follow_redirects=False,
                headers={"User-Agent": settings.user_agent, "Accept": "*/*", "Accept-Encoding": "identity"},
            ) as response:
                rate_limited = response.status_code == 429
                # Refuse unsolicited compression before decoding, bounding decompression allocation.
                if response.headers.get("content-encoding", "identity").lower() not in ("", "identity"):
                    raise ResponseLimitError("compressed response refused; identity encoding required")
                try:
                    length = int(response.headers.get("content-length", "0"))
                except ValueError:
                    length = 0
                if length > max_bytes:
                    raise ResponseLimitError(f"response too large ({length} > {max_bytes})")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > max_bytes:
                        raise ResponseLimitError(f"response too large (> {max_bytes})")
                    body.extend(chunk)
                successful = 200 <= response.status_code < 400
                return httpx.Response(
                    response.status_code, headers=response.headers, content=bytes(body),
                    request=httpx.Request("GET", url),
                )
        finally:
            try:
                if reserved:
                    self.budget.requests.record_outcome(
                        successful, retry=retry, domain=host, stage=stage, company=company, started=attempted,
                    )
            finally:
                if not attempted:
                    token.cancel()
                elif successful:
                    token.record_success()
                else:
                    token.record_failure(rate_limited=rate_limited)

    async def fetch(self, url: str, **kwargs) -> SourceRecord:
        """Bound all waits, retries and body reads by the monotonic run deadline."""
        remaining = self.budget.work_time_remaining()
        if remaining > 0:
            try:
                async with asyncio.timeout(remaining):
                    return await self._fetch(url, **kwargs)
            except TimeoutError:
                pass
        return SourceRecord(
            url=url, requested_url=url, source_type=kwargs.get("source_type", SourceType.OTHER.value),
            authority_tier=kwargs.get("authority_tier", 4), org_number=kwargs.get("company"),
            access_status="timeout", error_detail="absolute run deadline exceeded",
            retrieved_at=utcnow().isoformat(),
        )

    async def _fetch(
        self, url: str, *, stage: str = "unknown", company: Optional[str] = None,
        source_type: str = SourceType.OTHER.value, authority_tier: int = 4,
        max_bytes: Optional[int] = None, cache_ttl_override: Optional[float] = None,
        respect_robots: bool = False, allowed_domains: Optional[List[str]] = None, retries: int = 2,
        allowed_schemes: Optional[List[str]] = None,
        allowed_origins: Optional[List[str]] = None,
    ) -> SourceRecord:
        self.budget.check()
        chain: List[str] = []
        current = url

        def record(status: str, error: Optional[str] = None, response=None, **extra) -> SourceRecord:
            return SourceRecord(
                url=url, requested_url=url, final_url=current, redirect_chain=list(chain),
                domain=urlparse(current).hostname, source_type=source_type, authority_tier=authority_tier,
                org_number=company, retrieved_at=utcnow().isoformat(), access_status=status,
                error_detail=error, http_status=response.status_code if response else None,
                content_type=response.headers.get("content-type") if response else None, **extra,
            )

        try:
            clean, host = validate_url(url, allowed_domains, allowed_schemes, allowed_origins)
            url = current = clean
            chain = [clean]
            ttl = self.cache_ttl if cache_ttl_override is None else cache_ttl_override
            cached = self._cache.get(clean)
            if cached and cached.age_sec() < ttl:
                for cached_hop in cached.redirect_chain or [clean]:
                    validate_url(cached_hop, allowed_domains, allowed_schemes, allowed_origins)
                    if respect_robots and not await self._robots_allows(
                        cached_hop, company=company, allowed_domains=allowed_domains,
                        allowed_schemes=allowed_schemes,
                        allowed_origins=allowed_origins,
                    ):
                        return record("robots_denied", "robots policy denied or unavailable")
                source = self._source_from_cache(cached, source_type, authority_tier, company, clean)
                await self._retain(source, cached.content)
                return source
            attempts = min(max(retries, 0), self.rate_limiter.state_for(host).policy.max_retries) + 1
            url_attempts: Dict[str, int] = {}
            for attempt in range(attempts):
                current = clean
                chain = [clean]
                for hop in range(settings.max_redirects + 1):
                    current, hop_host = validate_url(
                        current, allowed_domains, allowed_schemes, allowed_origins,
                    )
                    if respect_robots and not await self._robots_allows(
                        current, company=company, allowed_domains=allowed_domains,
                        allowed_schemes=allowed_schemes,
                        allowed_origins=allowed_origins,
                    ):
                        return record("robots_denied", "robots policy denied or unavailable")
                    try:
                        url_attempts[current] = url_attempts.get(current, 0) + 1
                        hop_retry_limit = self.rate_limiter.state_for(hop_host).policy.max_retries
                        response = await self._exchange(
                            current, hop_host, stage=stage, company=company,
                            max_bytes=max_bytes if max_bytes is not None else settings.max_response_bytes,
                            retry=attempt > 0,
                        )
                    except (httpx.TimeoutException, httpx.TransportError) as error:
                        if attempt + 1 == attempts or url_attempts[current] > hop_retry_limit:
                            state = "timeout" if isinstance(error, httpx.TimeoutException) else "failed"
                            return record(state, type(error).__name__)
                        await _backoff(attempt + 1)
                        break
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location or hop == settings.max_redirects:
                            return record("failed", "redirect limit reached or missing Location", response)
                        current, _ = validate_url(
                            urljoin(current, location), allowed_domains, allowed_schemes, allowed_origins
                        )
                        if current in chain:
                            return record("failed", "redirect loop", response)
                        chain.append(current)
                        continue
                    if response.status_code == 200:
                        hashed = hashlib.sha256(response.content).hexdigest()
                        self._cache[clean] = CachedResponse(
                            url=clean, status_code=200, text=response.text, content_hash=hashed,
                            retrieved_at=time.time(), headers=dict(response.headers),
                            content=response.content,
                            final_url=current, redirect_chain=list(chain),
                        )
                        source = record(
                            "success", response=response, content_hash=hashed,
                            snapshot_representation="http-response-body-v1",
                        )
                        await self._retain(source, response.content)
                        return source
                    if (
                        response.status_code in _RETRY_STATUS and attempt + 1 < attempts
                        and url_attempts[current] <= hop_retry_limit
                    ):
                        try:
                            delay = max(0, min(float(response.headers.get("retry-after", "0")), 10))
                        except ValueError:
                            delay = 0
                        if delay:
                            await asyncio.sleep(delay)
                        else:
                            await _backoff(attempt + 1)
                        break
                    state = "rate_limited" if response.status_code == 429 else (
                        "blocked" if response.status_code in (401, 403) else "failed"
                    )
                    return record(state, f"http {response.status_code}", response)
            return record("failed", "retry exhaustion")
        except (SSRFError, RateLimited) as error:
            return record("blocked", str(error))
        except ResponseLimitError as error:
            return record("failed", str(error))
        except sqlite3.Error:
            return record("failed", "request accounting or snapshot storage unavailable")


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
            snapshot_representation="http-response-body-v1",
            access_status="success",
            retrieved_at=datetime.fromtimestamp(cached.retrieved_at, UTC).isoformat(),
            org_number=company,
            requested_url=url,
            final_url=cached.final_url or url,
            redirect_chain=cached.redirect_chain or [url],
            content_type=cached.headers.get("content-type"),
            cache_hit=True,
        )
        return rec

    # ------------------------------------------------------------- content
    async def _retain(self, source: SourceRecord, body: bytes) -> None:
        if self.repository is not None:
            await asyncio.to_thread(
                self.repository.save_capture, source, body,
                deadline=self.budget.runtime.started_at + self.budget.runtime.total_limit_sec,
            )

    def load_capture(self, source_id: str) -> CachedResponse:
        """Offline replay of acquisition bytes with their original retrieval time.

        No DNS, HTTP, cache-age refresh, extraction or new verified observation occurs.
        """
        if self.repository is None:
            raise ValueError("offline replay requires a repository")
        source, body = self.repository.read_capture(source_id)
        headers = {"content-type": source.content_type} if source.content_type else {}
        response = httpx.Response(source.http_status or 200, headers=headers, content=body)
        cached = CachedResponse(
            url=source.url or "", status_code=response.status_code, text=response.text,
            content_hash=source.content_hash or "", content=body,
            retrieved_at=(
                datetime.fromisoformat(source.retrieved_at).timestamp() if source.retrieved_at else 0
            ),
            headers=headers, from_cache=True, final_url=source.final_url or source.url or "",
            redirect_chain=list(source.redirect_chain),
        )
        self._cache[cached.url] = cached
        return cached

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

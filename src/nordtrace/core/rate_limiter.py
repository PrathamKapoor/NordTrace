"""Generic per-domain rate limiter + circuit breaker.

Works for any source (NAV, Brreg, arbitrary websites) — not a one-off hack.

SourcePolicy:
  - max_concurrent: in-flight request cap per domain
  - min_interval:   minimum seconds between request starts per domain
  - max_retries:    bounded retries on transient failures
  - circuit breaker: repeated failures (429/5xx/timeouts) OPEN the circuit;
    after a cooldown a controlled half-open retry is allowed; success CLOSES it

The global request budget remains intact (gateway consults it independently).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class SourcePolicy:
    max_concurrent: int = 4
    min_interval: float = 0.25  # seconds between request starts
    max_retries: int = 2
    breaker_threshold: int = 4  # consecutive failures → OPEN
    breaker_cooldown: float = 60.0  # seconds before half-open retry


@dataclass
class DomainState:
    policy: SourcePolicy
    _semaphore: Optional[asyncio.Semaphore] = None
    _last_start: float = 0.0
    consecutive_failures: int = 0
    circuit_open: bool = False
    _opened_at: float = 0.0
    rate_limited_events: int = 0
    total_requests: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @property
    def semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.policy.max_concurrent)
        return self._semaphore

    def breaker_allows(self) -> bool:
        """True if requests may proceed (CLOSED, or HALF-OPEN after cooldown)."""
        if not self.circuit_open:
            return True
        if (time.monotonic() - self._opened_at) >= self.policy.breaker_cooldown:
            # half-open: allow one controlled attempt
            return True
        return False

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.circuit_open = False

    def record_failure(self, rate_limited: bool = False) -> None:
        self.total_requests += 0  # counter handled by budget; this tracks health only
        if rate_limited:
            self.rate_limited_events += 1
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.policy.breaker_threshold:
            self.circuit_open = True
            self._opened_at = time.monotonic()

    def snapshot(self) -> Dict[str, object]:
        return {
            "circuit_open": self.circuit_open,
            "consecutive_failures": self.consecutive_failures,
            "rate_limited_events": self.rate_limited_events,
            "total_requests": self.total_requests,
        }


class RateLimiter:
    """Per-domain throttling + circuit breaker registry (async-safe)."""

    def __init__(self, default_policy: Optional[SourcePolicy] = None):
        self.default_policy = default_policy or SourcePolicy()
        self._domains: Dict[str, DomainState] = {}
        # Known-source presets (conservative; generic mechanism, tuned defaults)
        self._presets: Dict[str, SourcePolicy] = {
            "arbeidsplassen.nav.no": SourcePolicy(
                max_concurrent=1, min_interval=1.0, max_retries=3, breaker_threshold=3, breaker_cooldown=90.0
            ),
            "data.brreg.no": SourcePolicy(
                max_concurrent=2, min_interval=0.5, max_retries=3, breaker_threshold=5, breaker_cooldown=60.0
            ),
        }

    def state_for(self, domain: str) -> DomainState:
        if domain not in self._domains:
            policy = self._presets.get(domain, self.default_policy)
            self._domains[domain] = DomainState(policy=policy)
        return self._domains[domain]

    async def acquire(self, domain: str) -> RateLimitToken:
        """Throttle + circuit-check before a request. Raises RateLimited if the
        circuit is OPEN (caller should degrade gracefully, not hammer).

        The returned token HOLDS the per-domain semaphore until the caller
        records success/failure (which releases it) — enforcing max_concurrent
        across the full request duration."""
        state = self.state_for(domain)
        if not state.breaker_allows():
            raise RateLimited(
                f"circuit OPEN for {domain}; cooldown remains "
                f"{state.policy.breaker_cooldown - (time.monotonic() - state._opened_at):.0f}s"
            )
        await state.semaphore.acquire()
        try:
            # min-interval spacing
            async with state._lock:
                now = time.monotonic()
                wait = state._last_start + state.policy.min_interval - now
                if wait > 0:
                    await asyncio.sleep(wait)
                state._last_start = time.monotonic()
        except BaseException:
            state.semaphore.release()
            raise
        state.total_requests += 1
        return RateLimitToken(state)

    def snapshot(self) -> Dict[str, Dict[str, object]]:
        return {d: s.snapshot() for d, s in self._domains.items()}


class RateLimited(RuntimeError):
    """Circuit OPEN — the source is temporarily unavailable for this window."""


class RateLimitToken:
    """Holds the per-domain semaphore; records success/failure and releases."""

    def __init__(self, state: DomainState):
        self.state = state
        self._done = False

    def _release(self) -> None:
        try:
            self.state.semaphore.release()
        except Exception:
            pass

    def record_success(self) -> None:
        if not self._done:
            self.state.record_success()
            self._release()
            self._done = True

    def record_failure(self, rate_limited: bool = False) -> None:
        if not self._done:
            self.state.record_failure(rate_limited)
            self._release()
            self._done = True

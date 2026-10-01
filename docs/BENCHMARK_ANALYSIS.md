# Benchmark Analysis — 100-Company Live Run (v2)

**Timestamp:** 2026-10-01T12:34:01+00:00
**Companies attempted:** 100

## Terminal states (actual)

| State | Count |
|---|---|
| available | 88 |
| not_available | 12 |

## Coverage by category (actual, v2)

| Category | Coverage | v1 (registry-only discovery) |
|---|---|---|
| identity | 100% | 100% |
| business_description | 15% | 10% |
| industry | 88% | 88% |
| financials | 28% | 28% |
| leadership | 88% | 88% |
| locations | 0% | 0% |
| products_services | 7% | 2% |
| jobs | 7% | 4% |
| recent_activity | 13% | 13% |

## Budgets (actual)

- Requests: 924/2000 (v1: 449)
- Runtime: 280.0s / 2700s (v1: 178.2s)
- Cost: $0.0000 / $10.00 (deterministic extraction; LLM disabled)

## Source bottlenecks (actual)

| Domain | Total | Success | Failed | Rate-limited | Facts provided |
|---|---|---|---|---|---|
| data.brreg.no | 300 | 216 | 84 | 0 | 1146 |
| arbeidsplassen.nav.no | 100 | 0 | 100 | 100 | 0 |
| www.telenor.no | 50 | 18 | 32 | 0 | 3 |
| www.salmar.no | 18 | 18 | 0 | 0 | 8 |
| aibel.com | 16 | 16 | 0 | 0 | 4 |
| www.equinorpensjon.no | 14 | 1 | 13 | 0 | 1 |
| www.equinor.com | 11 | 11 | 0 | 0 | 2 |
| trondheim-telenor-bil.idrettenonline.no | 9 | 9 | 0 | 0 | 1 |
| www.telenorcyberdefence.com | 9 | 9 | 0 | 0 | 2 |
| www.salma.no | 9 | 9 | 0 | 0 | 2 |

## Key findings (actual)

1. **Requests**: 924/2000 (46%) — well within budget with the rate limiter active; v1 used 449 but skipped website discovery for companies without registry websites.
2. **Runtime**: 280s / 2700s (~10%) — comfortably within the 45-minute limit.
3. **Entity resolution**: 100/100 — deterministic, registry-anchored; zero ambiguity.
4. **Identity/industry/leadership**: 100%/88%/88% — registry provides these reliably.
5. **Business description**: 15% — limited by companies without discoverable websites (83/100 have no registry hjemmeside); name-derived candidates are conservative by design.
6. **Financials**: 28% — limited by regnskapsregisteret coverage (latest filed year; custom-layout filers unavailable).
7. **Jobs**: 7% — NAV rate limiting (circuit breaker active) + employer-name verification strictness.
8. **No fabrication**: all missing categories reported as not_available; zero invented values.
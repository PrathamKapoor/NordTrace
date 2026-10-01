# Coverage Improvement Report — Before/After (actual measurements)

**Dates:** v2 baseline 2026-10-01; v4 after improvements 2026-10-02.
**Method:** same 100-company live benchmark harness, fresh temp DB per run,
identical methodology. Companies fetched live from registry search (no hardcoding).

## Headline metrics

| Metric | v2 (before) | v4 (after) | Delta |
|---|---|---|---|
| Entity resolved | 100/100 | 100/100 | 0 |
| `available` | 88 | 88 | 0 |
| `not_available` | 12 | 12 | 0 |
| `failed` | 0 | 0 | 0 |
| Verified facts | 1,179 | **1,420** | **+241** |
| Evidence records | 643 | 662 | +19 |
| Rejected sources | 246 | 437 | +191 (tighter firewall + more candidates) |
| Requests | 924/2000 | 1,506/2000 | +582 (adaptive top-ups, still 75% of budget) |
| Runtime | 280s/2700s | 469.8s/2700s | +190s (still 17% of budget) |
| Cost | $0.00 | $0.00 | 0 |

## Facts by category (before → after)

| Category | v2 facts | v4 facts | Delta |
|---|---|---|---|
| identity | 778 | 778 | 0 |
| leadership | 192 | **406** | **+214** (person-distinguished slots publish all board members instead of 1 + CONFLICT spam) |
| financials | 164 | 164 | 0 (source-limited: 68 genuine registry 404s) |
| jobs | 4 | **20** | **+16** (careers-page extraction; NAV IP-blocked all run) |
| recent_activity | 14 | 20 | +6 |
| products_services | 2 | 17 | +15 |
| business_description | 10 | 15 | +5 |

## Coverage by category (before → after)

| Category | v2 | v4 |
|---|---|---|
| identity | 100% | 100% |
| industry | 88% | 88% |
| leadership | 88% | 88% |
| financials | 28% | 28% |
| business_description | 15% | 15% |
| jobs | 7% | 7% |
| recent_activity | 13% | 13% |
| products_services | 7% | 7% |
| locations | 0% | 0% |

**Note:** category coverage is flat because coverage counts *presence*, and the
missing categories are source-limited (see `COVERAGE_GAP_ANALYSIS.md`). The
improvement shows up as **facts per covered company** (+241 facts) and the
**regression recovery** (v3's 92 FAILED → v4's 0 FAILED).

## Regression recovered (critical)

v3 (mid-pass) measured **92/100 FAILED** when Brreg refused connections
(ConnectError cascade → circuit OPEN → `rate_limited` wrongly mapped to FAILED).
Fixed in this pass: registry `rate_limited` → BLOCKED terminal state (source
temporarily unavailable, not system failure); exponential cooldown capped at 4x
so the circuit recovers within a single run. v4: **0 FAILED**.

## Information-gain metrics (new in benchmark)

| Metric | v4 value |
|---|---|
| facts/company | 14.2 |
| verified facts/company | 14.2 |
| evidence/company | 6.6 |
| categories/company | 5.4 |
| requests/company | 15.1 |
| facts/request | 0.94 |

## Safety properties maintained

- 0 wrong-company publications (subsidiary brand-site attachment REJECTED; contamination gate at citation level)
- 0 fabricated values (all missing categories → `not_available`; financials only from registry/PDF with currency+period)
- 0 fabricated evidence (citation validator requires source retrieval + evidence text + org match)
- 0 budget bypasses (single gateway; 1,506/2,000 hard-enforced)
- 0 rate-limit violations (circuit breaker + Retry-After + exponential cooldown; NAV never hammered)

## Remaining levers (documented, not implemented)

1. **NAV block lift**: when the IP-level 429 block lifts, NAV queries resume
   automatically (circuit half-open → close on success). Jobs coverage should rise
   toward ~30-40% based on the earlier 15-company run (31 Telenor hits).
2. **Search-provider discovery** for companies without websites: requires a keyless
   or keyed provider; documented as optional integration (SOURCES.md Tier 4).
3. **OCR fallback** for scanned PDFs: honest failure kept (documented decision).

## Do NOT overfit

No company-specific handling: the benchmark companies were fetched live at
runtime from registry search; no orgnr-based special cases; the improvements
(candidate generation, careers extraction, adaptive top-ups) are generic and
apply to any company.

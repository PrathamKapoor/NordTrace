# Coverage Gap Analysis — 100-Company Live Run

**Basis:** benchmark_result_v2.json + v4 (executed 2026-10-02); measured, not guessed.

| Category | v2 coverage | Failure modes (measured) | Most common missing-source reason | Most promising improvement | Expected request cost |
|---|---|---|---|---|---|
| Identity | 100% | — (none) | — | none needed (registry-anchored) | ~2/company (already spent) |
| Industry | 88% | 12 companies missing NACE (ENK/person enterprises) | registry has no naeringskode for ENK | none (source-limited) | 0 (registry field) |
| Leadership | 88% | 12 companies with empty rollegrupper (role data restricted for ENK) | registry roles unavailable for company form | none (source-limited) | ~1/company |
| Financials | 28% | **68/72 genuine 404s** (no accounts filed in regnskapsregisteret — ENK/small); 4 http 500 | accounts not filed (source-side) | PDF reports on company websites (implemented: adaptive_financials) | ~1/company + PDF when discovered |
| Business description | 15% | **74/85 website fetch failures** (name-derived candidates: TLS ConnectError 161×, circuit OPEN 8×); 8 fetched-but-no-description | no registry hjemmeside (83/100 companies) + name-derived candidates 404/TLS-fail | brand-first candidate generation (implemented); adaptive top-ups (implemented) | ~4/company (candidates) |
| Jobs | 7% | **93/93 NAV rate_limited** (IP-level 429 block persisting days); careers pages have no listing links on landing pages | NAV IP-block (source-side, not query formulation) | careers-page extraction (implemented: 24 openings on AkerBP); NAV recovers when block lifts | ~1/company + NAV 1/company |
| Activity | 13% | **87/100 no registry activity events** (small companies have no capital/status/registration events) | no dated registry events (source-side) | company news pages (crawled when website exists) | 0 (registry signals) |
| Locations | 0% | underenheter: 0 branch units for most companies (single-location ENKs) | no branch units registered | none (source-limited) | ~1/company |
| Products/services | 7% | websites missing/failed → no product pages crawled | no website | same as business description | same as business |

## Key measured facts

1. **Financials 28% is source-limited, not extraction-limited**: 68/72 missing-financials
   companies are genuine registry 404s (no accounts filed). The regnskapsregisteret
   only covers companies with ordinary layout plans; ENKs often file simplified accounts
   not exposed by the API.
2. **Business 15% is website-availability-limited**: 83/100 companies have no registry
   hjemmeside. Name-derived candidates fail with TLS ConnectError (this network cannot
   reach many small-company hosts) — measured 161 ConnectErrors across the run.
3. **Jobs 7% was entirely NAV rate-limiting** (93/93 rate_limited). Careers-page
   extraction added as fallback: 24 openings extracted from AkerBP alone when a
   listing path exists.
4. **Activity 13% is registry-signal-limited**: small companies have no capital changes,
   no status events, no branch registrations — no dated events to report. Inventing
   them would violate the no-fabrication rule.
5. **Entity 100% is load-bearing**: every improvement kept the firewall intact
   (subsidiary brand-site attachment rejected; contamination gate at citation level).

## Improvement decisions (implemented this pass)

| Change | Effect | Cost |
|---|---|---|
| Brand-first candidate generation | better candidates (TELENOR PAKISTAN AS → telenor.no not telenor-pakistan.no) | +2 requests/company |
| Homepage verification tightened (VERIFIED-only fallback) | subsidiary firewall holds; parent brand site no longer attaches to subsidiaries | 0 |
| Careers-page job extraction | 24 openings from AkerBP; jobs 7→20 facts | 0 (uses crawled page) |
| Adaptive top-ups (business/financials) | targeted research only for missing categories, budget/time-gated | variable, only when missing |
| Contamination gate in CitationValidator | evidence-org must equal fact-org | 0 |
| Registry rate_limited → BLOCKED (not FAILED) | correct terminal semantics under source blocks | 0 |
| Exponential cooldown capped 4x | circuit recovers within a single run | 0 |

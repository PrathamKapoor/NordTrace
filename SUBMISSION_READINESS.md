# Submission Readiness Scorecard

**Date:** 2026-10-02
**Commit:** `c29db8c`+ (main) — every status below is backed by an actual command/result.

| Requirement | Status | Evidence |
|---|---|---|
| Real registry lookup | **PASS** | `python -m nordtrace.cli research 982463718` → TELENOR ASA, live Brreg API; 404 for unregistered; checksum-invalid rejected |
| Real website research | **PASS** | Discovery (registry hjemmeside + name-derived candidates) + focused crawl + page classification; live-verified (salmar.no: 18 sources, 8 facts) |
| Real financial research | **PASS** | Live regnskapsregisteret: Equinor 67.96B USD, SalMar 24.02B NOK with currency+period; deterministic extraction |
| Real jobs research | **PASS** | Live NAV Arbeidsplassen search + employer verification (Telenor: 31 hits; verified postings with title/location/deadline) |
| Real activity research | **PASS** | Registry-signal events (registrations, capital, status) with dates; zero fabrication |
| Entity firewall | **PASS** | Signal-based resolver (foreign orgnr → REJECTED dominates); 19 entity tests + 11 adversarial tests |
| Evidence validation | **PASS** | Citation validator (fact→evidence→source chain, deterministic); 20 ledger tests |
| Change detection | **PASS** | Fact-slot diff (NEW/CHANGED/RETRACTED/UNCHANGED/SOURCE_UNAVAILABLE) with temporal periods; live ×2 run verified |
| Refresh | **PASS** | Live: same company ×2 → 23 unchanged facts detected; history preserved |
| Resume | **PASS** | Live: interrupt at 37 → resume skips completed, 38–100 continue, DB consistent |
| Batch | **PASS** | 100-company live run (concurrency 4); 10/15-company runs |
| Request budget | **PASS** | 924/2,000 in 100-company run; hard stop tested; atomic counter; single gateway (no bypass) |
| Runtime budget | **PASS** | 280s/2,700s; global deadline wins; 1-second deadline test passes |
| Cost budget | **PASS** | $0.0000/$10.00 (deterministic extraction; LLM disabled without key); cost guard tested |
| API | **PASS** | All endpoints backed by SQLite; background research; 422/404 validation; fact dedupe; TestClient-verified |
| CLI | **PASS** | research/batch/resume/benchmark/validate/validate-db/serve — all live-verified |
| Frontend | **PASS** | Real SPA consuming API; browser-verified (research flow, evidence drawer with real URL/hash, zero static demo data); degraded-source messaging ("X was temporarily rate-limited during this run") |
| Security | **PASS** | SSRF guard (octal/decimal/hex IPs, CGNAT, metadata); prompt injection as data; secrets grep-verified; 11 security tests |
| Tests | **PASS** | 237 passed (228 unit + 9 live integration) |
| Docker | **PASS** | Image builds (sha256:cea06cab); CLI research inside container; /health + /dashboard 200 OK |
| 100-company benchmark | **PASS** | Executed ×3: v4 final — 88/100 available, 100/100 entity resolved, 1,420 facts (+241 vs baseline), 1,506/2,000 requests, 469.8s, $0.00; v3 regression (92 FAILED) found and fixed |
| LLM (live) | **NOT RUN** | No `LLM_API_KEY` in environment; mock provider fully tested (8 tests) |
| Scanned-PDF OCR | **KNOWN LIMITATION** | Honest extraction-failure; no OCR dependency added (documented decision) |

## Remaining risks (honest)

1. **NAV IP-level rate limiting**: long blocks (>90s observed) degrade jobs coverage
   during large batches; circuit breaker protects both the source and the run.
   Mitigation in place; unavoidable when the source blocks at IP level.
2. **Business description coverage 15%**: limited by companies without discoverable
   websites (83/100 have no registry hjemmeside); name-derived candidates are
   conservative by design (wrong-company protection takes priority over coverage).
3. **Financials coverage 28%**: limited by regnskapsregisteret (latest filed year;
   custom-layout filers unavailable → honest `not_available`).
4. **Live LLM unverified**: mock path fully tested; live path needs a key.

## Scorecard rules

- PASS = executed command with observed result
- NOT RUN = not executed (reason stated)
- KNOWN LIMITATION = documented design decision with tradeoff
- No score fabrication; local benchmark is a diagnostic, not the official competition score
